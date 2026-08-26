"""A place to compile a candidate program where its imports resolve.

Most eTamil programs in the repository import like this:

    இறக்கு "../../nUlakam/paNam.qmz";

which only resolves from the file's own directory. Compiling the text through
stdin therefore fails for a reason that has nothing to do with the text — that
is why only 32 of 77 source files count as quotable, and it would make an eval
score the import path rather than the completion.

So a candidate is written at the same relative path inside a temporary tree
that has its own copy of `nUlakam`, and compiled there. Nothing is written into
the eTamil repository, which matters because another session works in it.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType

from .. import config


class Sandbox:
    """A throwaway tree with the standard library in it.

    Built once per run rather than per case: copying nUlakam is 41 files, and
    an eval with several hundred cases would otherwise spend most of its time
    on the copy.
    """

    def __init__(self) -> None:
        self._root: Path | None = None
        self._temp: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> "Sandbox":
        self._temp = tempfile.TemporaryDirectory(prefix="pary-eval-")
        self._root = Path(self._temp.name)
        shutil.copytree(config.ETAMIL_ROOT / "nUlakam", self._root / "nUlakam")
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._temp is not None:
            self._temp.cleanup()

    @property
    def root(self) -> Path:
        if self._root is None:
            raise RuntimeError("use the Sandbox as a context manager")
        return self._root

    def compiles(self, relative_path: str, text: str, timeout: float = 20.0) -> bool:
        """Write the text where the original lived, and compile it there."""
        binary = config.etamil_bin()
        if binary is None:
            raise SystemExit("the eTamil compiler is not built")

        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

        try:
            completed = subprocess.run(
                [str(binary), "--check", str(target)],
                capture_output=True,
                timeout=timeout,
                cwd=self.root,
            )
        except subprocess.TimeoutExpired:
            return False
        finally:
            target.unlink(missing_ok=True)

        return completed.returncode == 0
