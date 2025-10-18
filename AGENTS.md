# Repository Guidelines

## Project Structure & Module Organization
Source lives under `src/fileops_toolkit/`, grouped by domain: `discovery/`, `metadata/`, `deduplication/`, `transfer/`, `verification/`, `logging/`, `supervisor/`, and `console/` for the CLI. Shared configuration helpers sit in `src/fileops_toolkit/config_loader.py`, `pipeline.py`, and `prechecks.py`. Example configs reside in `config/`, runtime artefacts in `logs/`, and sample data under `data/` for local experiments. Console entry points are exposed via `bin/fileops-toolkit` after bootstrapping.

## Build, Test, and Development Commands
- `./run.sh` — create/refresh `.venv`, install dependencies in editable mode, then open the interactive menu.
- `python -m fileops_toolkit.console.main precheck --config config/config.yml` — verify binaries, disk space, and directory permissions before a run.
- `python -m fileops_toolkit.console.main run --config config/config.yml --dry-run` — exercise the full pipeline without writing to the destination.
- `python -m compileall src` — quick smoke check that modules import successfully; run before submitting PRs.
- `pip install -e .[dev]` — optional editable install with planned dev extras once added.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation. Modules and packages use `snake_case`; classes follow `CamelCase`; command functions should read like verbs (`run_pipeline`). Keep Rich UI helpers declarative and avoid inline ANSI codes. Prefer pathlib over os.path, and centralise filesystem mutations in the relevant engine modules.

## Testing Guidelines
Add unit tests beside new modules under `tests/` (create the directory if missing) using `pytest`. Name files `test_<feature>.py` and functions `test_<behavior>()`. Include integration exercises for discovery, deduplication, and transfer flows where feasible, mocking remote hosts when secrets would otherwise be required. Ensure `python -m compileall src` and `pytest` both succeed before requesting review.

## Commit & Pull Request Guidelines
Write commits in imperative mood (`feat: add mirror mode hashing`). Group related changes; avoid mixing refactors with feature work. Pull requests should include: purpose summary, testing evidence (`pytest`, CLI dry-run, or pipeline logs), mention of updated docs/configs, and any follow-up todos. Link GitHub issues when applicable and attach screenshots or terminal snippets for UI/menu adjustments.

## Security & Configuration Tips
Never commit real API tokens, SSH passwords, or production paths. Mask secrets in examples, rely on `.env` or user-specific overrides, and ensure `.gitignore` excludes logs, temp staging areas, and virtual environments. Use the `remote_sources` staging directory in configs for SSH transfers and confirm `sshpass` availability when password auth is required.
