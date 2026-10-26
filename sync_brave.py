from __future__ import annotations

import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrowserProfile:
    directory: str
    name: str
    bookmarks_path: Path


def _browser_data_dir(browser: str) -> Path:
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        if browser == "chrome":
            return local_app_data / "Google/Chrome/User Data"
        return local_app_data / "BraveSoftware/Brave-Browser/User Data"
    if system == "Darwin":
        if browser == "chrome":
            return home / "Library/Application Support/Google/Chrome"
        return home / "Library/Application Support/BraveSoftware/Brave-Browser"
    if browser == "chrome":
        chrome = home / ".config/google-chrome"
        return chrome if chrome.exists() else home / ".config/chromium"
    return home / ".config/BraveSoftware/Brave-Browser"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read browser data at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Browser data at {path} has an invalid format.")
    return data


def _profile_bookmarks_path(profile_path: Path) -> Path:
    for filename in ("Bookmarks", "AccountBookmarks"):
        bookmarks_path = profile_path / filename
        if bookmarks_path.is_file():
            return bookmarks_path
    return profile_path / "Bookmarks"


def discover_profiles(user_data_dir: Path) -> list[BrowserProfile]:
    state_path = user_data_dir / "Local State"
    info_cache = _read_json(state_path).get("profile", {}).get("info_cache", {})
    profiles: list[BrowserProfile] = []

    if isinstance(info_cache, dict):
        for directory, info in info_cache.items():
            if not isinstance(directory, str) or Path(directory).name != directory:
                continue
            profile_path = user_data_dir / directory
            if not profile_path.is_dir():
                continue
            name = info.get("name", directory) if isinstance(info, dict) else directory
            profiles.append(
                BrowserProfile(
                    directory=directory,
                    name=str(name),
                    bookmarks_path=_profile_bookmarks_path(profile_path),
                )
            )

    if not profiles:
        for profile_path in sorted(user_data_dir.iterdir()):
            if profile_path.is_dir() and (
                profile_path.name == "Default"
                or re.fullmatch(r"Profile \d+", profile_path.name)
            ):
                preferences_path = profile_path / "Preferences"
                name = profile_path.name
                if preferences_path.exists():
                    preferences = _read_json(preferences_path)
                    name = str(preferences.get("profile", {}).get("name", name))
                profiles.append(
                    BrowserProfile(
                        directory=profile_path.name,
                        name=name,
                        bookmarks_path=_profile_bookmarks_path(profile_path),
                    )
                )

    return profiles


def _profile_label(profile: BrowserProfile) -> str:
    return f"{profile.name} ({profile.directory})"


def select_item(message: str, choices: list[str]) -> int | None:
    try:
        import questionary
    except ImportError as exc:
        raise RuntimeError(
            "The CLI dependency is missing. Install with: uv tool install --editable ."
        ) from exc

    selected = questionary.select(
        message,
        choices=choices,
        instruction="(Use arrow keys, Enter to select)",
    ).ask()
    if selected is None:
        return None
    return choices.index(selected)


def _html_node(node: dict[str, Any], level: int = 0) -> list[str]:
    indent = "    " * level
    title = html.escape(str(node.get("name", "")), quote=False)
    node_type = node.get("type")
    if node_type == "url":
        url = html.escape(str(node.get("url", "")), quote=True)
        return [f'{indent}<DT><A HREF="{url}">{title}</A>']
    if node_type == "folder":
        children = node.get("children", [])
        if not isinstance(children, list):
            children = []
        lines = [f"{indent}<DT><H3>{title}</H3>", f"{indent}<DL><p>"]
        for child in children:
            if isinstance(child, dict):
                lines.extend(_html_node(child, level + 1))
        lines.append(f"{indent}</DL><p>")
        return lines
    return []


def export_bookmarks(bookmarks_path: Path, output_path: Path) -> None:
    data = _read_json(bookmarks_path)
    roots = data.get("roots", {})
    if not isinstance(roots, dict):
        raise RuntimeError(
            f"Bookmark roots are missing or invalid in {bookmarks_path}."
        )

    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
    ]
    for key, label in (
        ("bookmark_bar", "Bookmarks bar"),
        ("other", "Other bookmarks"),
        ("mobile", "Mobile bookmarks"),
    ):
        root = roots.get(key)
        if not isinstance(root, dict):
            continue
        children = root.get("children", [])
        if not isinstance(children, list):
            continue
        lines.extend((f"<DT><H3>{label}</H3>", "<DL><p>"))
        for child in children:
            if isinstance(child, dict):
                lines.extend(_html_node(child, 1))
        lines.append("</DL><p>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _merge_children(
    target_children: list[dict[str, Any]], source_children: list[dict[str, Any]]
) -> int:
    added = 0
    for source in source_children:
        node_type = source.get("type")
        if node_type == "url":
            url = source.get("url")
            if not isinstance(url, str):
                continue
            if any(
                existing.get("type") == "url" and existing.get("url") == url
                for existing in target_children
            ):
                continue
            target_children.append(source.copy())
            added += 1
        elif node_type == "folder":
            name = source.get("name")
            matching_folder = next(
                (
                    existing
                    for existing in target_children
                    if existing.get("type") == "folder" and existing.get("name") == name
                ),
                None,
            )
            if matching_folder is None:
                target_children.append(source.copy())
                added += _count_bookmarks(source)
            else:
                target_subtree = matching_folder.get("children")
                source_subtree = source.get("children")
                if isinstance(target_subtree, list) and isinstance(
                    source_subtree, list
                ):
                    added += _merge_children(target_subtree, source_subtree)
    return added


def _count_bookmarks(node: dict[str, Any]) -> int:
    if node.get("type") == "url":
        return 1
    children = node.get("children", [])
    if not isinstance(children, list):
        return 0
    return sum(_count_bookmarks(child) for child in children if isinstance(child, dict))


def merge_bookmarks(source_path: Path, target_path: Path) -> int:
    source_data = _read_json(source_path)
    target_data = _read_json(target_path)
    source_roots = source_data.get("roots", {})
    target_roots = target_data.get("roots", {})
    if not isinstance(source_roots, dict) or not isinstance(target_roots, dict):
        raise RuntimeError("Source or destination bookmark roots are invalid.")

    added = 0
    for root_name in ("bookmark_bar", "other", "mobile"):
        source_root = source_roots.get(root_name)
        if not isinstance(source_root, dict):
            continue
        target_root_name = root_name if root_name in target_roots else "other"
        target_root = target_roots.get(target_root_name)
        if not isinstance(target_root, dict):
            continue
        source_children = source_root.get("children", [])
        target_children = target_root.setdefault("children", [])
        if isinstance(source_children, list) and isinstance(target_children, list):
            valid_sources = [
                child for child in source_children if isinstance(child, dict)
            ]
            added += _merge_children(target_children, valid_sources)

    if added == 0:
        return 0

    backup_path = target_path.with_name(
        f"{target_path.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    )
    shutil.copy2(target_path, backup_path)
    content = json.dumps(target_data, ensure_ascii=False, separators=(",", ":")) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target_path.parent, delete=False
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, target_path)
    except OSError as exc:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        raise RuntimeError(f"Could not update Brave bookmarks: {exc}") from exc
    return added


def _brave_running() -> bool:
    if platform.system() == "Windows":
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq brave.exe"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not check whether Brave is running: {result.stderr}"
            )
        return "brave.exe" in result.stdout.lower()

    pgrep = shutil.which("pgrep")
    if pgrep is None:
        raise RuntimeError(
            "Cannot safely check whether Brave is running (pgrep is missing)."
        )
    for process_name in ("brave", "brave-browser", "Brave Browser"):
        result = subprocess.run(
            [pgrep, "-x", process_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True
        if result.returncode not in (1,):
            raise RuntimeError(
                f"Could not check whether Brave is running: {result.stderr}"
            )
    return False


def _brave_executable() -> str:
    candidates = (
        ("brave.exe", "brave-browser.exe")
        if platform.system() == "Windows"
        else ("brave-browser", "brave")
        if platform.system() == "Linux"
        else ("brave", "Brave Browser")
    )
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable is not None:
            return executable
    raise RuntimeError("Could not find the installed Brave browser executable.")


def sync_profile(chrome_profile: BrowserProfile, brave_profile: BrowserProfile) -> None:
    if not chrome_profile.bookmarks_path.is_file():
        raise RuntimeError(
            f"No Chrome bookmarks file found for {_profile_label(chrome_profile)}."
        )
    if not brave_profile.bookmarks_path.is_file():
        raise RuntimeError(
            f"No Brave bookmarks file found for {_profile_label(brave_profile)}."
        )

    if _brave_running():
        raise RuntimeError(
            "Brave is currently running. Close all Brave windows and try again so the "
            "browser cannot overwrite its profile while bookmarks are being updated."
        )

    output_path = (
        Path.cwd() / "bookmarks" / f"chrome_{_safe_filename(chrome_profile.name)}.html"
    )
    export_bookmarks(chrome_profile.bookmarks_path, output_path)
    added = merge_bookmarks(chrome_profile.bookmarks_path, brave_profile.bookmarks_path)

    command = [
        _brave_executable(),
        f"--user-data-dir={_browser_data_dir('brave')}",
        f"--profile-directory={brave_profile.directory}",
        "--new-window",
    ]
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise RuntimeError(
            f"Bookmarks were updated, but Brave could not be opened: {exc}"
        ) from exc

    print(f"\nExported Chrome bookmarks to: {output_path}")
    print(
        f"Added {added} bookmark(s) to Brave profile {_profile_label(brave_profile)}."
    )
    if added:
        print("A backup of the previous Brave bookmarks file was saved beside it.")


def _safe_filename(name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._@+-]+", "_", name.strip()).strip("._")
    return safe_name or "profile"


def run_cli() -> None:
    while True:
        selection = select_item("Sync Brave through Chrome", ["Sync bookmarks", "Exit"])
        if selection is None or selection == 1:
            return

        chrome_dir = _browser_data_dir("chrome")
        brave_dir = _browser_data_dir("brave")
        if not chrome_dir.is_dir():
            raise RuntimeError(f"Chrome profile directory was not found: {chrome_dir}")
        if not brave_dir.is_dir():
            raise RuntimeError(f"Brave profile directory was not found: {brave_dir}")

        chrome_profiles = discover_profiles(chrome_dir)
        brave_profiles = discover_profiles(brave_dir)
        if not chrome_profiles:
            raise RuntimeError(f"No Chrome profiles were found in {chrome_dir}")
        if not brave_profiles:
            raise RuntimeError(f"No Brave profiles were found in {brave_dir}")

        chrome_index = select_item(
            "Choose a Chrome profile to export",
            [_profile_label(profile) for profile in chrome_profiles],
        )
        if chrome_index is None:
            continue
        brave_index = select_item(
            "Choose a Brave profile to receive the bookmarks",
            [_profile_label(profile) for profile in brave_profiles],
        )
        if brave_index is None:
            continue
        sync_profile(chrome_profiles[chrome_index], brave_profiles[brave_index])
        return


def main() -> None:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(
            "Usage: sync-brave\n\nInteractively export Chrome bookmarks and merge them into Brave."
        )
        return
    try:
        run_cli()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except (RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
