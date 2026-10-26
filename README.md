# Sync Brave bookmarks from Chrome

`sync-brave` is an interactive command-line tool that exports bookmarks from a
local Google Chrome profile, merges them into a local Brave profile, and opens
the selected Brave profile. It uses the browsers installed on your computer;
it does not download or run a bundled browser.

## Features

- Select a Chrome source profile and Brave destination profile in an arrow-key
  interface.
- Export bookmarks as Netscape-format HTML to
  `bookmarks/chrome_<profile_name>.html` in the current project directory.
- Read Chrome's standard `Bookmarks` file, or use `AccountBookmarks` when the
  standard file is absent.
- Merge into Brave without replacing its existing bookmarks; existing URLs are
  not added a second time.
- Save a timestamped backup of Brave's bookmark data before making changes.
- Open the selected profile in the installed Brave browser.

## Requirements

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/).
- Google Chrome (or Chromium on Linux) and Brave installed with local profiles.
- Close all Brave windows before syncing. The tool refuses to change Brave's
  profile while Brave is running.

Chrome does not need to be open. The program reads its bookmark data directly
from the local profile directory. It does not access browser passwords,
cookies, or other profile data.

## Install

After this project has been published to PyPI:

```sh
uv tool install sync-brave
```

This installs the `sync-brave` command so it can be run from any terminal.

To use a local checkout during development:

```sh
uv tool install --editable .
```

To update a published installation:

```sh
uv tool upgrade sync-brave
```

## Use

```sh
sync-brave
```

Use the arrow keys and Enter to:

1. Choose **Sync bookmarks**.
2. Select the Chrome profile to export from.
3. Select the Brave profile to merge into.

The HTML export is written to `bookmarks/` in the current working directory.
To save it in a particular project folder, run `sync-brave` from that folder.
The bookmark data is merged into Brave's selected profile, backed up, and
Brave is opened on that profile.

## Release setup

For instructions to build, test, and publish this package to TestPyPI or PyPI,
see [SETUP.md](SETUP.md).

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE).
