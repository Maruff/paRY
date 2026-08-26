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

    print()
    name = cards[0]["name"] if cards else report.get("device", "unknown")
    label, rate = throughput_for(name)
    hours = FLOPS / rate / 3600
    print(f"Phase A is {FLOPS:.1e} FLOPs (45M parameters over {TOKENS / 1e6:.0f}M tokens).")
    print(f"At the rate a {label} realistically sustains, one run is about "
          f"{hours:.1f} hours.")

    memory_gb = (cards[0]["total_mb"] / 1024) if cards else report.get("total_gb", 0)
    print()
    if not cards and not report.get("cuda_available"):
        print("VERDICT: no usable CUDA GPU here. On CPU this model is days, not hours —")
        print("         rent an L40S for an hour instead (about $1).")
    elif memory_gb < 6:
        print(f"VERDICT: {memory_gb:.0f} GB is tight. It will train with a small batch and")
        print("         gradient accumulation, just slowly. Worth trying before renting.")
    elif hours > 6:
        print("VERDICT: it will train, but overnight rather than over lunch. Fine for the")
        print("         first run; rent for the ablations if you are iterating.")
    else:
        print("VERDICT: train here. No rental needed, and nothing leaves the machine.")

    print()
    print("Send this output back and the trainer will be written for this GPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
