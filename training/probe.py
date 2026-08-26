"""What can this machine actually train?

Run it on the Ubuntu box. It reports the GPU, how much memory is really usable,
and what that means for Phase A — then says whether to train there or rent an
hour of something bigger.

    python3 training/probe.py

Nothing is installed and nothing is downloaded. If PyTorch is not there yet it
says so and carries on with what `nvidia-smi` knows.

The reason this exists: "NVIDIA with shared VRAM" can mean three very different
machines. A discrete card with 8–24 GB of its own memory trains this model
comfortably. A laptop chip sharing system RAM through the driver will train it
too, several times slower. An AMD integrated GPU with no CUDA at all cannot,
and knowing that before writing a trainer is worth five minutes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

# Phase A, from docs/ARCHITECTURE.md: 12 layers, d_model 512, ~45M parameters.
PARAMS = 45_000_000
TOKENS = 300_000_000          # the middle of the 200–500M plan
FLOPS = 6 * PARAMS * TOKENS   # the standard estimate for a training run

# Rough achievable bf16 throughput, not the marketing number: about a third of
# peak is what a small model with short sequences really gets.
THROUGHPUT = {
    "4090": 60e12, "4080": 40e12, "3090": 35e12, "3080": 28e12,
    "4070": 25e12, "3070": 20e12, "3060": 12e12, "2060": 8e12,
    "A100": 120e12, "L40S": 70e12, "T4": 8e12, "unknown": 15e12,
}


def run(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        completed = subprocess.run(command, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip()


def nvidia() -> list[dict]:
    output = run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,driver_version,compute_cap",
        "--format=csv,noheader,nounits",
    ])
    if not output:
        return []
    cards = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 5:
            cards.append({
                "name": parts[0],
                "total_mb": int(parts[1]),
                "used_mb": int(parts[2]),
                "driver": parts[3],
                "compute": parts[4],
            })
    return cards


def torch_report() -> dict:
    try:
        import torch
    except ImportError:
        return {"installed": False}

    report = {
        "installed": True,
        "version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": getattr(torch.version, "cuda", None),
    }
    if torch.cuda.is_available():
        report["device"] = torch.cuda.get_device_name(0)
        free, total = torch.cuda.mem_get_info()
        report["free_gb"] = round(free / 1024**3, 2)
        report["total_gb"] = round(total / 1024**3, 2)
    return report


def throughput_for(name: str) -> tuple[str, float]:
    for key, value in THROUGHPUT.items():
        if key.lower() in name.lower():
            return key, value
    return "unknown", THROUGHPUT["unknown"]


def benchmark(device: str, size: int = 2048, repeats: int = 6) -> float | None:
    """Measure what this machine really does, rather than look it up.

    A big matmul is most of what training is, so timing one gives an estimate
    good enough to decide between "train here overnight" and "rent an hour".
    Returns FLOPs per second, or None if the device is unusable.
    """
    try:
        import torch
    except ImportError:
        return None
    if device == "cuda" and not torch.cuda.is_available():
        return None

    import time

    try:
        left = torch.randn(size, size, device=device)
        right = torch.randn(size, size, device=device)
    except (RuntimeError, AssertionError):
        return None

    # One untimed pass: the first call allocates and warms the kernels up.
    torch.matmul(left, right)
    if device == "cuda":
        torch.cuda.synchronize()

    started = time.perf_counter()
    for _ in range(repeats):
        torch.matmul(left, right)
    if device == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    # A matmul of two n×n matrices is 2n³ floating-point operations.
    return (2 * size**3 * repeats) / elapsed


def plan(rate: float) -> list[tuple[str, int, int, float]]:
    """How long each sensible run takes at a measured rate.

    Training compute is 6 × parameters × tokens. The pilot is there because the
    first thing worth knowing is whether the pipeline works end to end, and that
    question does not need a full-sized model or a full corpus.
    """
    configurations = [
        # Not a model anyone would ship — a run short enough to prove the
        # pipeline end to end on whatever hardware is in front of you.
        ("smoke", 3_000_000, 3_000_000),
        ("pilot", 10_000_000, 20_000_000),
        ("small", 45_000_000, 50_000_000),
        ("Phase A", 45_000_000, 300_000_000),
    ]
    return [
        (name, params, tokens, (6 * params * tokens) / rate / 3600)
        for name, params, tokens in configurations
    ]


def main() -> int:
    print("paRY — what can this machine train?\n")

    cards = nvidia()
    if not cards:
        print("  no nvidia-smi, or no NVIDIA GPU visible")
    for card in cards:
        print(f"  GPU        {card['name']}")
        print(f"  memory     {card['total_mb'] / 1024:.1f} GB total, "
              f"{card['used_mb'] / 1024:.1f} GB already in use")
        print(f"  driver     {card['driver']}   compute capability {card['compute']}")

    print()
    report = torch_report()
    if not report["installed"]:
        print("  PyTorch    not installed yet")
        print("             pip install torch --index-url https://download.pytorch.org/whl/cu124")
    else:
        print(f"  PyTorch    {report['version']}, CUDA {report['cuda_version']}")
        print(f"  usable     {'yes' if report['cuda_available'] else 'NO — CPU only'}")
        if report.get("free_gb") is not None:
            print(f"  free VRAM  {report['free_gb']} GB of {report['total_gb']} GB")

    # Memory is the question everyone asks first, and it is the wrong one.
    print()
    print("What training this actually needs:")
    print("  parameters + gradients + Adam states   ~0.9 GB")
    print("  activations at batch 8 x 1024 tokens   ~1.0 GB")
    print("  ------------------------------------------------")
    print("  about 2-3 GB. 16 GB of system RAM is not the constraint.")

    print()
    print("Measuring this machine rather than guessing…")
    cpu_rate = benchmark("cpu")
    gpu_rate = benchmark("cuda")
    if cpu_rate:
        print(f"  CPU   {cpu_rate / 1e9:>8,.0f} GFLOP/s measured")
    if gpu_rate:
        print(f"  GPU   {gpu_rate / 1e9:>8,.0f} GFLOP/s measured")
    elif report.get("installed"):
        print("  GPU   unusable from PyTorch")

    # Training sustains well under a bare matmul's rate: attention, the
    # optimiser and data loading all cost time that this benchmark does not.
    rate = (gpu_rate or cpu_rate or THROUGHPUT["unknown"]) * 0.35
    if not cpu_rate and not gpu_rate:
        _, rate = throughput_for(cards[0]["name"] if cards else "unknown")

    print()
    print(f"{'run':<10}{'params':>10}{'tokens':>10}{'hours':>10}")
    for name, params, tokens, hours in plan(rate):
        print(f"{name:<10}{params / 1e6:>9,.0f}M{tokens / 1e6:>9,.0f}M{hours:>10.1f}")

    print()
    if gpu_rate:
        print("VERDICT: CUDA works here. Train on this machine — nothing leaves it,")
        print("         and the ablations cost nothing but time.")
    elif cpu_rate:
        print("VERDICT: no usable CUDA GPU, so this would be CPU training.")
        print("         Run the pilot here overnight to prove the pipeline works end")
        print("         to end, then rent an L40S for about $1 for the real run.")
        print("         Renting is worth it once you are comparing runs, not before.")
    else:
        print("VERDICT: install PyTorch and run this again — nothing can be measured yet.")

    print()
    print("Send this output back and the trainer will be written for what it says.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
