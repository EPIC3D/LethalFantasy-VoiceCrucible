# Developing

Read [ARCHITECTURE.md](ARCHITECTURE.md) first. Rules: small modules with one job, a short English docstring
on every module/class/function, type hints, no module over ~300 lines, game-specific code only in
`voicecrucible/lethalfantasy/`.

## Setup

```
uv sync --extra dev                                                  # core + tests (no torch)
uv sync --extra dev --extra checks --extra chatterbox --extra qwen   # everything for real renders
uv run pytest                                                        # tests (no GPU, no network needed)
uvx ruff check voicecrucible tests tools                             # lint
```

## Add an engine

1. `voicecrucible/engines/<name>.py`: a class implementing `engines.base.Engine` (`load`, `render`, `unload`)
   and `ENGINE = <class>`. Import heavy libraries inside `load()`. Raise `OutOfMemory` on GPU OOM.
2. Register it in `engines/base.py` (`_MODULES`).
3. Engine settings per line come from `line.params` – fill them in `lethalfantasy/emotions.py`.
4. Its dependencies go into a new extra in `pyproject.toml` and a component in `downloads.toml`
   (source, license, sizes) and [DOWNLOADS.md](DOWNLOADS.md). Only packages with ready wheels – users have
   no C compiler.

GPL code must never be imported by Voice Crucible: run it as a separate process (see `engines/seedvc.py` and
the GPL bridge in `voicecrucible/vc_bridge/`).

## Add a check

`voicecrucible/checks/<name>.py` implementing `checks.base.Check` (`run(take) -> CheckResult`, optional
`load`), `CHECK = <class>`, register in `checks/base.py`. Thresholds come from `job.settings` (coordinator's
`[checks]` section), so every worker judges alike.

## Protocol changes

Bump `core/protocol.PROTOCOL_VERSION` and keep the coordinator serving the previous protocol
(`MIN_COMPATIBLE`), so workers can be updated before the coordinator.

## Releasing

1. Version in `pyproject.toml` and `voicecrucible/__init__.py` (PEP 440: `0.1.0b1`), CHANGELOG.
2. Build the release zip (program files + `uv.exe`, no `runtime\`, `work\`, `output\`, `logs\`).
3. Sign it: `python tools/sign_release.py sign <key file> <zip>` → `<zip>.sig` (key: passphrase-protected,
   kept outside the repository).
4. GitHub release with tag `v0.1.0-beta.1`, upload the zip and the `.sig`.
