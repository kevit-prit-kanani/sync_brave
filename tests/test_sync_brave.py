import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_brave
from sync_brave import (
    BrowserProfile,
    _safe_filename,
    discover_profiles,
    export_bookmarks,
    merge_bookmarks,
    sync_profile,
)


def bookmark_file(children: list[dict]) -> dict:
    return {
        "version": 1,
        "roots": {
            "bookmark_bar": {"name": "Bookmarks bar", "children": children},
            "other": {"name": "Other bookmarks", "children": []},
            "synced": {"name": "Mobile bookmarks", "children": []},
        },
    }


class BookmarkSyncTests(unittest.TestCase):
    def test_discovers_named_profiles_from_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Default").mkdir()
            (root / "Profile 1").mkdir()
            (root / "Local State").write_text(
                json.dumps(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {"name": "Main"},
                                "Profile 1": {"name": "Work"},
                                "Missing": {"name": "Not installed"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            profiles = discover_profiles(root)
            self.assertEqual(
                [(profile.directory, profile.name) for profile in profiles],
                [("Default", "Main"), ("Profile 1", "Work")],
            )

    def test_discovers_account_bookmarks_when_standard_file_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "Profile 1"
            profile_path.mkdir()
            (profile_path / "AccountBookmarks").write_text(
                json.dumps(bookmark_file([])),
                encoding="utf-8",
            )
            (root / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Profile 1": {"name": "Work"}}}}),
                encoding="utf-8",
            )

            [profile] = discover_profiles(root)

            self.assertEqual(profile.bookmarks_path, profile_path / "AccountBookmarks")

    def test_prefers_standard_bookmarks_file_to_account_bookmarks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "Default"
            profile_path.mkdir()
            (profile_path / "Bookmarks").write_text("{}", encoding="utf-8")
            (profile_path / "AccountBookmarks").write_text("{}", encoding="utf-8")
            (root / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Default": {"name": "Main"}}}}),
                encoding="utf-8",
            )

            [profile] = discover_profiles(root)

            self.assertEqual(profile.bookmarks_path, profile_path / "Bookmarks")

    def test_exports_netscape_bookmarks_html_with_escaped_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Bookmarks"
            output = root / "bookmarks" / "chrome_Main.html"
            source.write_text(
                json.dumps(
                    bookmark_file(
                        [
                            {
                                "type": "folder",
                                "name": "News & Notes",
                                "children": [
                                    {
                                        "type": "url",
                                        "name": "A < B",
                                        "url": "https://example.test/?a=1&b=2",
                                    }
                                ],
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            export_bookmarks(source, output)
            html_text = output.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE NETSCAPE-Bookmark-file-1>", html_text)
            self.assertIn("News &amp; Notes", html_text)
            self.assertIn('HREF="https://example.test/?a=1&amp;b=2"', html_text)
            self.assertIn("A &lt; B", html_text)

    def test_merges_new_bookmarks_and_keeps_existing_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "chrome" / "Bookmarks"
            target_path = root / "brave" / "Bookmarks"
            source_path.parent.mkdir()
            target_path.parent.mkdir()
            source_path.write_text(
                json.dumps(
                    bookmark_file(
                        [
                            {"type": "url", "name": "Existing", "url": "https://same.test"},
                            {"type": "url", "name": "New", "url": "https://new.test"},
                            {
                                "type": "folder",
                                "name": "Reading",
                                "children": [
                                    {"type": "url", "name": "Article", "url": "https://article.test"}
                                ],
                            },
                        ]
                    )
                ),
                encoding="utf-8",
            )
            target_path.write_text(
                json.dumps(
                    bookmark_file(
                        [
                            {
                                "type": "url",
                                "name": "Existing in Brave",
                                "url": "https://same.test",
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )

            added = merge_bookmarks(source_path, target_path)
            updated = json.loads(target_path.read_text(encoding="utf-8"))
            urls = [
                node["url"]
                for node in updated["roots"]["bookmark_bar"]["children"]
                if node.get("type") == "url"
            ]
            self.assertEqual(added, 2)
            self.assertEqual(urls, ["https://same.test", "https://new.test"])
            self.assertTrue(list(target_path.parent.glob("Bookmarks.backup-*")))

    def test_existing_folder_merges_contents_without_duplicate_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.json"
            target_path = root / "target.json"
            source_path.write_text(
                json.dumps(
                    bookmark_file(
                        [
                            {
                                "type": "folder",
                                "name": "Reading",
                                "children": [
                                    {"type": "url", "name": "Same", "url": "https://same.test"},
                                    {"type": "url", "name": "New", "url": "https://new.test"},
                                ],
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            target_path.write_text(
                json.dumps(
                    bookmark_file(
                        [
                            {
                                "type": "folder",
                                "name": "Reading",
                                "children": [
                                    {
                                        "type": "url",
                                        "name": "Already there",
                                        "url": "https://same.test",
                                    }
                                ],
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            added = merge_bookmarks(source_path, target_path)
            self.assertEqual(added, 1)
            updated = json.loads(target_path.read_text(encoding="utf-8"))
            children = updated["roots"]["bookmark_bar"]["children"][0]["children"]
            self.assertEqual([node["url"] for node in children], ["https://same.test", "https://new.test"])

    def test_sanitizes_profile_names_for_output_path(self) -> None:
        self.assertEqual(_safe_filename("../Main Profile"), "Main_Profile")
        self.assertEqual(_safe_filename("prit.kanani@kevit.io"), "prit.kanani@kevit.io")

    def test_sync_exports_to_the_current_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chrome_dir = root / "chrome"
            brave_dir = root / "brave"
            chrome_dir.mkdir()
            brave_dir.mkdir()
            chrome_bookmarks = chrome_dir / "Bookmarks"
            brave_bookmarks = brave_dir / "Bookmarks"
            content = json.dumps(bookmark_file([]))
            chrome_bookmarks.write_text(content, encoding="utf-8")
            brave_bookmarks.write_text(content, encoding="utf-8")
            chrome_profile = BrowserProfile("Default", "Chrome", chrome_bookmarks)
            brave_profile = BrowserProfile("Default", "Brave", brave_bookmarks)

            with (
                patch.object(Path, "cwd", return_value=root),
                patch.object(sync_brave, "_brave_running", return_value=False),
                patch.object(sync_brave, "_brave_executable", return_value="/usr/bin/brave"),
                patch.object(sync_brave, "_browser_data_dir", return_value=root / "brave-data"),
                patch("sync_brave.subprocess.Popen"),
            ):
                sync_profile(chrome_profile, brave_profile)

            self.assertTrue((root / "bookmarks/chrome_Chrome.html").is_file())


if __name__ == "__main__":
    unittest.main()
