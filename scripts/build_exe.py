"""PyInstaller helper: produces a single-file Windows binary for the tray app.

Run from the project root with the dev/build extras installed:

    pip install -e ".[build]"
    python scripts/build_exe.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "scripts" / "run_app.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _sync_package_metadata() -> None:
    """Re-register this project's dist-info so the version bundled into the
    EXE matches ``pyproject.toml``.

    The version checker reads ``importlib.metadata.version("mi-monitor-light-tray")``
    at runtime, which comes from the pip-installed dist-info directory — not
    from ``pyproject.toml``. If the developer bumps ``pyproject.toml`` without
    re-running ``pip install -e .``, dist-info stays on the old version and
    the EXE self-reports the wrong version (and keeps showing "update
    available"). CI does not hit this because every run is a fresh venv.

    ``pip install -e . --no-deps`` is idempotent and quick — it only rewrites
    the local project's dist-info, without touching dependencies.
    """
    print("Syncing package metadata with pyproject.toml ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps", "--quiet"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        print(
            "WARNING: pip install -e . failed; the EXE may report a stale "
            "version. Continue anyway.",
            file=sys.stderr,
        )


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "PyInstaller is not installed in this interpreter. Run: "
            "pip install -e \".[build]\"",
            file=sys.stderr,
        )
        return 1

    _sync_package_metadata()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "MiMonitorLightTray",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        # python-miio ships YAML/JSON specs alongside its modules. PyInstaller
        # only picks up imported Python files by default, so the device-info
        # parser crashes at runtime without this. ``--collect-data`` walks the
        # package and bundles every non-Python file.
        "--collect-data",
        "miio",
        # Hidden imports for token extractor
        "--hidden-import",
        "Crypto.Cipher.ARC4",
        "--hidden-import",
        "Crypto.Random",
        "--hidden-import",
        "requests",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
        str(ENTRY),
    ]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
