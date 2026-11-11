#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _configure_windows_console() -> None:
    """Ensure UTF-8 output and ANSI VT support on Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
                handle = kernel32.GetStdHandle(handle_id)
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass


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
_configure_windows_console()

from kisskh_app.ui import KissKHConsoleApp  # noqa: E402


def main() -> None:
    initial_query = " ".join(sys.argv[1:]).strip() or None
    app = KissKHConsoleApp()
    app.run(initial_query=initial_query)


if __name__ == "__main__":
    main()
