# Repository Guidelines

## Project Structure & Module Organization
All application code lives in `src/fileops_toolkit/`. Subpackages follow the pipeline flow: `discovery/`, `metadata/`, `deduplication/`, `transfer/`, `verification/`, `logging/`, `supervisor/`, and `console/` for the CLI surfaces. Shared helpers sit in `config_loader.py`, `pipeline.py`, and `prechecks.py`. Configuration samples live in `config/`, runtime logs in `logs/`, and sample datasets under `data/`. The executable wrapper `bin/fileops-toolkit` becomes available after running `./run.sh`.

## Build, Test, and Development Commands
Run `./run.sh` to create or refresh `.venv`, install dependencies in editable mode, and launch the interactive menu. Use `python -m fileops_toolkit.console.main precheck --config config/config.yml` to validate binaries, free space, and permissions. Execute `python -m fileops_toolkit.console.main run --config config/config.yml --dry-run` for a full simulated pipeline, or switch `--dry-run` to `--apply` for real transfers. `python -m compileall src` provides a quick importability check, and `pytest` (after `pip install -e .[dev]`) runs the automated suite.

## Coding Style & Naming Conventions
Adopt PEP 8 with four-space indentation. Modules and packages should use `snake_case`, classes `CamelCase`, and public functions describe actions (`run_pipeline`, `load_config`). Prefer `pathlib.Path` for filesystem access and keep Rich-based UI helpers declarative—no raw ANSI sequences. Centralise filesystem mutations inside the transfer or supervisor layers to keep policies deterministic.

## Testing Guidelines
Place new tests in `tests/`, mirroring the module hierarchy. Name files `test_<feature>.py` and functions `test_<behavior>()`. Rely on `pytest` fixtures to mock remote hosts or large data sets. Confirm both `python -m compileall src` and `pytest` pass before submitting changes. For manual smoke tests, run the CLI in both dry-run and apply modes to cover deduplication, mirror/flatten, and remote staging paths.

## Commit & Pull Request Guidelines
Commits must be imperative (`feat: add mirror mode hashing`) and scoped to a single concern. Each pull request should outline purpose, key changes, and verification evidence (e.g., `pytest`, `run --dry-run`, or log snippets). Note any config or documentation updates, link related issues, and include screenshots when altering console output or banners. Request review only after resolving TODOs in code or docs.

## Security & Configuration Tips
Do not commit secrets, SSH keys, or production host paths. Keep `.env`, `logs/`, `.venv/`, and temp staging directories ignored. When configuring `remote_sources`, verify `sshpass` exists for password-based flows and prefer SSH keys in production. Validate destination permissions and free space via `precheck` before running long transfers.
