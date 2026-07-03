"""GitHub Release version checker for automatic update notifications."""

from __future__ import annotations

import logging
import threading
from typing import Optional, Tuple
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def get_current_version() -> str:
    """Get the current version from pyproject.toml or package metadata.

    Returns:
        Version string like "1.3.9"
    """
    # Try to get version from installed package metadata first (works in EXE)
    try:
        from importlib.metadata import version
        return version("mi-monitor-light-tray")
    except Exception:
        pass

    # Fallback: try reading pyproject.toml with tomllib/tomli
    try:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                tomllib = None

        if tomllib:
            project_root = Path(__file__).parent.parent
            toml_path = project_root / "pyproject.toml"

            if toml_path.exists():
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "unknown")
    except Exception as exc:
        log.debug("Failed to read version from pyproject.toml: %s", exc)

    # Last resort: manual parsing
    return _parse_version_manually()


def _parse_version_manually() -> str:
    """Manually parse version from pyproject.toml without toml library."""
    try:
        project_root = Path(__file__).parent.parent
        toml_path = project_root / "pyproject.toml"

        if toml_path.exists():
            content = toml_path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("version"):
                    # Extract version from: version = "1.3.2"
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        version = parts[1].strip().strip('"').strip("'")
                        return version
    except Exception as exc:
        log.debug("Manual version parsing failed: %s", exc)

    return "unknown"


def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse version string to tuple for comparison.

    Args:
        version_str: Version like "1.3.2" or "v1.3.2"

    Returns:
        Tuple like (1, 3, 2)
    """
    # Remove 'v' prefix if present
    version_str = version_str.lstrip("v")

    try:
        parts = version_str.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0,)


def check_for_updates(
    repo: str = "Martlnez/MiMonitorLightTray",
    timeout: int = 5
) -> Optional[dict]:
    """Check GitHub Releases for newer versions.

    Args:
        repo: GitHub repository in format "owner/repo"
        timeout: Request timeout in seconds

    Returns:
        Dict with update info if newer version available, None otherwise.
        Format: {"version": "1.4.0", "url": "https://...", "body": "..."}
    """
    current_version = get_current_version()

    if current_version == "unknown":
        log.warning("Cannot determine current version, skipping update check")
        return None

    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        headers = {"Accept": "application/vnd.github.v3+json"}

        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        latest_version = data.get("tag_name", "").lstrip("v")

        if not latest_version:
            log.debug("No release version found in API response")
            return None

        # Compare versions
        current_tuple = parse_version(current_version)
        latest_tuple = parse_version(latest_version)

        if latest_tuple > current_tuple:
            log.info("Update available: %s -> %s", current_version, latest_version)
            return {
                "version": latest_version,
                "url": data.get("html_url", ""),
                "body": data.get("body", ""),
                "download_url": _extract_exe_url(data),
            }
        else:
            log.debug("Already on latest version: %s", current_version)
            return None

    except requests.RequestException as exc:
        log.debug("GitHub API request failed: %s", exc)
        return None
    except Exception as exc:
        log.warning("Update check failed: %s", exc)
        return None


def _extract_exe_url(release_data: dict) -> Optional[str]:
    """Extract the .exe download URL from release assets.

    Args:
        release_data: GitHub release API response

    Returns:
        Download URL for .exe file, or None if not found
    """
    assets = release_data.get("assets", [])
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(".exe"):
            return asset.get("browser_download_url")
    return None


class VersionChecker:
    """Background version checker that runs on a separate thread."""

    def __init__(self, repo: str = "Martlnez/MiMonitorLightTray"):
        self.repo = repo
        self._update_info: Optional[dict] = None
        self._checked = False

    def check_async(self) -> None:
        """Start an async check in the background."""
        thread = threading.Thread(target=self._check_thread, daemon=True)
        thread.start()

    def _check_thread(self) -> None:
        """Background thread that performs the check."""
        self._update_info = check_for_updates(self.repo)
        self._checked = True

    def get_update_info(self) -> Optional[dict]:
        """Get the cached update info, if any.

        Returns:
            Update info dict if newer version available, None otherwise
        """
        return self._update_info

    def has_checked(self) -> bool:
        """Check if the async check has completed."""
        return self._checked
