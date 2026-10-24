# Contribute to Neyra

## Set up development

Install Git, uv, and Node.js 20 or newer. Use Python 3.12, as specified in
`.python-version`.

```sh
uv sync --locked --group dev
npm ci --omit=dev
uv run python -m neyra.main
```

On Linux, install PortAudio and PulseAudio-compatible system libraries for the
audio backends. Headless tests also need Xvfb and a running PulseAudio server.
The exact Ubuntu packages and commands are in
[the checks workflow](.github/workflows/checks.yml).

Read the [architecture guide](docs/architecture.md) before changing a subsystem.
See the [user guide](README.md) for model downloads and desktop permissions.

## Check changes

Run the same checks used for pull requests:

```sh
uv run --locked ruff check neyra scripts tests packaging/aur/check_generator.py
node --check neyra/voz_transcribe.mjs
node --check website/site.js
node scripts/check_voz.mjs
uv run --locked python scripts/check_piper.py
uv run --locked python -m unittest discover -s tests -v
uv run --locked python packaging/aur/check_generator.py
```

On headless Linux, prefix the regression command with `xvfb-run -a`. The tests
simulate devices and provider responses; they do not prove microphone capture,
desktop shortcuts, or real ChatGPT login works. Check those manually when your
change affects them, and report what you checked.

Ruff checks syntax and a small set of runtime errors. It does not require a
repository-wide formatting change. Keep unrelated changes out of your PR.

To require passing checks before merging, add `Checks on ubuntu-22.04` and
`Checks on windows-latest` as required status checks in a GitHub branch ruleset
for `main` after the workflow has run.

## Update dependencies

Use `uv add` or `uv lock --upgrade-package PACKAGE` for Python dependencies.
Commit `pyproject.toml` and `uv.lock` together when both change. Use npm to
update `package.json` and `package-lock.json` together. CI uses locked installs.
Dependabot proposes weekly updates for Python, npm, and GitHub Actions;
maintainers review and merge them after checks pass.

## Prepare a pull request

Use the [PR template](.github/pull_request_template.md) and follow the section
limits in [AGENTS.md](AGENTS.md). Include the problem, how the change fixes it,
verification results, and implementation attribution. Add a regression check
for a meaningful behavior change where practical.

Keep credentials, personal recordings, transcripts, downloaded models,
`output/`, and build artifacts out of commits.

## Prepare a release

Build on the target operating system; Nuitka does not cross-compile. See
[build instructions](README.md#build-with-nuitka-offline-model-included).

1. Update the version in `pyproject.toml`, refresh `uv.lock`, and review the
   release notes and download page.
2. Run the PR checks and build each supported package. The release workflow
   checks Windows PE, Linux ELF and archive contents, and macOS bundle metadata
   and Apple silicon architecture before uploading artifacts.
3. Open each built app on its target system. Check microphone selection,
   dictation, shortcut release, clipboard output, and quitting. Check optional
   features changed by the release. Record unsupported or untested behavior.
4. Push an approved `vVERSION` tag matching the project version to publish the
   release assets and AUR submission archive. Inspect the workflow result and
   attached files before announcing the release.

Package checks inspect files; they do not launch the app or replace target-system
testing. macOS packages are currently unsigned and not notarized.
