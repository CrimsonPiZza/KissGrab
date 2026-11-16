from __future__ import annotations

import sys


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


def main(args: list[str] | None = None) -> int:
    """CLI entry point for KissGrab."""
    _configure_windows_console()
    if args is None:
        args = sys.argv[1:]

    raw_query = " ".join(args).strip()
    if raw_query in ("-v", "--version"):
        from kisskh_app import APP_NAME, __version__

        print(f"{APP_NAME} {__version__}")
        return 0

    if raw_query in ("-h", "--help"):
        from kisskh_app import APP_NAME, __version__

        print(f"{APP_NAME} {__version__} — Interactive console downloader for kisskh.do")
        print()
        print("Usage:")
        print("  kissgrab                     Launch interactive menu")
        print("  kissgrab <query or URL>      Search drama or open URL directly")
        print("  kissgrab --version           Show version")
        print("  kissgrab --help              Show this help message")
        return 0

    from kisskh_app.ui import KissKHConsoleApp

    initial_query = raw_query or None
    app = KissKHConsoleApp()
    app.run(initial_query=initial_query)
    return 0


if __name__ == "__main__":
    sys.exit(main())

