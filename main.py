#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _ensure_venv() -> None:
    """Re-exec inside project .venv automatically if launched from system Python."""
    if os.environ.get("_KISSKH_REEXEC") == "1":
        return
    if importlib.util.find_spec("kisskh_downloader") is not None:
        return

    project_root = Path(__file__).resolve().parent
    candidates = [
        project_root / ".venv" / "bin" / "python",
        project_root / ".venv" / "Scripts" / "python.exe",
    ]
    for venv_python in candidates:
        if venv_python.is_file():
            os.environ["_KISSKH_REEXEC"] = "1"
            cmd = [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]]
            if sys.platform == "win32":
                sys.exit(subprocess.call(cmd))
            os.execv(str(venv_python), cmd)


_ensure_venv()

from kisskh_app.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
