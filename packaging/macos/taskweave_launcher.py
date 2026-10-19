"""Frozen macOS desktop entry. Dispatch workers before importing the application."""

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()

    from taskweave.desktop.bundle import main
    raise SystemExit(main())
