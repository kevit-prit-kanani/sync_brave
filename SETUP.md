# Package and PyPI publishing setup

This guide covers building, testing, and publishing `sync-brave` to TestPyPI
and PyPI.

## Requirements

- A [uv installation](https://docs.astral.sh/uv/).
- A PyPI account for production publishing.
- A TestPyPI account for the optional test upload.
- The project name must be available on the target index. The current name is
  `sync-brave`; check [PyPI](https://pypi.org/project/sync-brave/) before the
  first production release. If it is unavailable, change `name` in
  `pyproject.toml`. The command name (`sync-brave`) can remain unchanged.

## 1. Prepare a release

Review `pyproject.toml`, including the package name, version, Python
requirement, license, and dependencies. Every release must use a version that
has not already been uploaded.

From the project directory, run the tests and build both distribution formats:

```sh
uv run --no-project python -m unittest discover -s tests -v
uv build
```

The wheel and source archive are written to `dist/`. Inspect their contents
before upload. They should include the application and its documentation and
license, but not personal browser data, generated bookmark exports, or local
error logs.

## 2. Test on TestPyPI (recommended)

Create an account and account-scoped upload token at
[test.pypi.org](https://test.pypi.org/). A project-scoped token cannot be
created until the project exists on that index.

In Bash, enter the token at a hidden prompt and upload the artifacts:

```sh
read -s -p 'TestPyPI token: ' UV_PUBLISH_TOKEN
printf '\n'
export UV_PUBLISH_TOKEN
uv publish --publish-url https://test.pypi.org/legacy/
unset UV_PUBLISH_TOKEN
```

Try installing the TestPyPI package. The additional index allows uv to get
dependencies that are available on regular PyPI:

```sh
uv tool install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ sync-brave
```

Use a TestPyPI token for this step, never your production PyPI token.

## 3. Publish to PyPI

Create a PyPI account and upload token at [pypi.org](https://pypi.org/). For
the first upload, use an account-scoped token. Once the project exists, revoke
that token and use a project-scoped token for later releases.

Keep the token private. Do not place it in source code, a file committed to
version control, or a command that will be saved in shell history. In Bash,
enter the token at a hidden prompt and publish:

```sh
read -s -p 'PyPI token: ' UV_PUBLISH_TOKEN
printf '\n'
export UV_PUBLISH_TOKEN
uv publish
unset UV_PUBLISH_TOKEN
```

`uv publish` uploads the distributions in `dist/`. After a successful upload,
the project is available at `https://pypi.org/project/sync-brave/`.

## 4. Verify the published installation

Install the published command and check that it starts:

```sh
uv tool install sync-brave
sync-brave --help
```

For repeatable releases, consider setting up PyPI Trusted Publishing from a CI
workflow instead of storing an API token.
