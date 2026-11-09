#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
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
            os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


_ensure_venv()

from kisskh_app.ui import KissKHConsoleApp  # noqa: E402


def main() -> None:
    initial_query = " ".join(sys.argv[1:]).strip() or None
    app = KissKHConsoleApp()
    app.run(initial_query=initial_query)


if __name__ == "__main__":
    main()

