# FileOps Toolkit – Python CLI Edition

⚙️ Modular, parallel, and policy-driven deduplication & transfer framework for large media archives, ISO libraries, and cold-storage workflows.

```
╔════════════════════════════════════════════════════════════════════════╗
║   ______ _ _        _ _____           _____         _ _ _              ║
║  |  ____(_) |      | |  __ \         / ____|       | (_) |             ║
║  | |__   _| | _____| | |__) |__  ___| (___   ___ __| |_| |_ ___  _ __  ║
║  |  __| | | |/ / _ \ |  ___/ _ \/ __|\___ \ / __/ _` | | __/ _ \| '__| ║
║  | |    | |   <  __/ | |  |  __/ (__ ____) | (_| (_| | | || (_) | |    ║
║  |_|    |_|_|\_\___|_|_|   \___|\___|_____/ \___\__,_|_|\__\___/|_|    ║
╚════════════════════════════════════════════════════════════════════════╝
 █████▒ ██▓ ██▓    ▓█████  ▒█████   ██▓███   ▄▄▄       ▄████▄  ▄▄▄█████▓
▓██   ▒▓██▒▓██▒    ▓█   ▀ ▒██▒  ██▒▓██░  ██▒▒████▄    ▒██▀ ▀█  ▓  ██▒ ▓▒
▒████ ░▒██▒▒██░    ▒███   ▒██░  ██▒▓██░ ██▓▒▒██  ▀█▄  ▒▓█    ▄ ▒ ▓██░ ▒░
░▓█▒  ░░██░▒██░    ▒▓█  ▄ ▒██   ██░▒██▄█▓▒ ▒░██▄▄▄▄██ ▒▓▓▄ ▄██▒░ ▓██▓ ░
░▒█░   ░██░░██████▒░▒████▒░ ████▓▒░▒██▒ ░  ░ ▓█   ▓██▒▒ ▓███▀ ░  ▒██▒ ░
 ▒ ░   ░▓  ░ ▒░▓  ░░░ ▒░ ░░ ▒░▒░▒░ ▒▓▒░ ░  ░ ▒▒   ▓▒█░░ ░▒ ▒  ░  ▒ ░░
 ░      ▒ ░░ ░ ▒  ░ ░ ░  ░  ░ ▒ ▒░ ░▒ ░       ▒   ▒▒ ░  ░  ▒       ░
 ░ ░    ▒ ░  ░ ░      ░   ░ ░ ░ ▒  ░░         ░   ▒   ░            ░
        ░      ░  ░   ░  ░    ░ ░                 ░  ░░ ░
                                                     ░

Author: PierringShot Electronics — https://github.com/pierringshot
```

## 🧭 Feature Highlights

- 🔍 **Pattern-aware discovery** – mix glob and regex inclusion filters (`*.iso`, `/home/*/pie*/*.md`, etc.) with case sensitivity controls.
- 📦 **Dual operation modes** – `flatten` for central archives; `mirror` to retain relative source layout while streaming dedupe-aware metadata.
- 🧠 **Deterministic dedup logic** – compares name → size → `mtime` → multi-algorithm checksums (`md5`, `sha1`, `xxh128`), with actions `skip`, `archive`, or `delete`.
- 🚛 **Retrying transfer engine** – `rsync`-first with resumable flags, exponential backoff, and local copy fallback.
- 🧰 **Interactive Rich menu** – configure sources, policies, verbosity, and dry-run safety from a guided console with colour-coded feedback.
- 📊 **Structured telemetry** – CSV / JSON artifacts, error funnel, live progress bars, and summarised run dashboards.
- 🛡️ **Preflight & verification** – dependency checks, free-space validation, optional checksum verification after transfer.
- 🌐 **Remote staging pipeline** – rsync/SSH targets staged into a local cache with key/password auth, parallel sync, and menu-driven management.

## 🗂️ Repository Layout

```
FileOPS-Toolkit/
  src/fileops_toolkit/
    console/        # CLI entrypoints, Rich menu, interactive config editor, banner
    discovery/      # Pattern-aware file walkers (glob/regex, fd/find integration)
    metadata/       # Stat collection + checksum hashing
    deduplication/  # Policy engine (prefer_newer, keep_both_with_suffix, etc.)
    transfer/       # rsync/rclone wrappers with retry + mode-aware dispatch
    verification/   # Post-transfer size/hash validation helpers
    logging/        # CSV/JSON writers, error reporting, verbosity routing
    supervisor/     # ThreadPool orchestration, retry queue management
    pipeline.py     # End-to-end executor for discovery → logging
    prechecks.py    # Dependency/permission/freespace validation
    config_loader.py
  config/config.yml # Example configuration mirroring production settings
  bin/              # Convenience launcher (`fileops-toolkit`)
  logs/             # Runtime logs (ignored by git)
  data/             # Sample data/duplicates folders (ignored by git)
  run.sh            # Bootstrap helper (venv + editable install + menu)
  requirements.txt
  setup.py
  LICENSE
  AGENTS.md         # Full AI/DevOps training brief
```

## 🏗️ Architecture Map

| Module | Purpose |
| --- | --- |
| **Discovery Engine** | Walks source trees using native `pathlib`, `find`, or `fd`, honoring glob/regex filters and extension allow-lists. |
| **Metadata Scanner** | Captures stat info, normalises timestamps, and calculates configured checksums in worker executors. |
| **Deduplication Core** | Applies deterministic precedence (name → size → mtime → hash) with configurable collision policies and duplicate actions. |
| **Transfer Engine** | Launches resumable `rsync` (or fallback copy), coordinates flatten/mirror routing, and applies exponential retry logic. |
| **Verification Module** | Validates size/hash parity after transfer, recording verification status in logs. |
| **Logging & Analytics** | Streams CSV/JSON audit logs, maintains error funnel, respects verbosity preferences. |
| **Interactive Console** | Rich/Click CLI: `scan`, `precheck`, `run`, `show-config`, and full-screen menu with sub-menus for config/log review. |
| **Supervisor / Scheduler** | ThreadPool manager with retry queue, progress callbacks, and SSH-source awareness. |
| **Preflight Checks** | Ensures binaries exist, directories are writable, and free-space & checksum dependencies pass before execution. |

## 🧮 Deduplication & Transfer Workflow

1. **Discovery** – enumerate candidate files via patterns/extensions from configured sources.
2. **Metadata Scan** – gather size, `mtime`, ownership, and checksum(s).
3. **Dedup Decision** – compare with destination candidates; pick action (`copy`, `skip`, `archive duplicate`, `delete duplicate`).
4. **Transfer** – invoke `rsync`/copy respecting flatten vs mirror mode and dry-run flag.
5. **Verification** – optional checksum + size parity confirmation.
6. **Logging** – emit CSV/JSON entries, update progress, record failures to the retry queue.

## 🧩 Operation Modes & Policies

- **Flatten mode** (default): deposits all matches directly under `destination`, driving dedup decisions for every collision. Duplicate actions follow the configured policy (`skip`, `archive`, `delete`).
- **Mirror mode**: preserves relative source paths inside `destination`. Dedup decision widgets are dimmed/disabled; focus shifts to structural replication.
- **Duplicate actions**:
  - `skip` – leave destination copy untouched, record duplicate.
  - `archive` – move duplicate to `duplicates_archive_dir`.
  - `delete` – remove duplicate from source after verification (honours `dry_run`).

## 🌐 Remote Sources

- Define remote rsync/SSH paths under `remote_sources`. Each entry accepts `target` (`user@host:/path`), optional `name`, `identity_file`, `password` (requires `sshpass`), `ssh_options`, and bespoke `rsync_args`.
- Remote targets are staged into `remote_staging_dir` before discovery. The toolkit reuses your standard dedup/transfer policy once files are cached locally.
- `remote_rsync_args` sets shared defaults (e.g., `-avz --info=progress2`), while `remote_parallel_workers` controls how many remotes sync concurrently.
- Manage remote endpoints via the menu: `menu → Remote source management` (or Configuration Editor option `9`). Add/update/remove targets, tweak staging, and adjust parallelism without editing YAML manually.
- For password auth, install `sshpass` or rely on SSH agents/keys. Staging honours `dry_run`, but remote dry-runs only list metadata—they do not fetch binaries.
- `scan` command previews local sources only; run `precheck` or `run` to stage remote content when required.

## 🔍 Pattern Matching

The discovery layer supports both simple extension filters and complex patterns:

- `patterns`: list of glob or regex strings.  
- `pattern_mode`: `glob` _(default)_ or `regex`.  
- `pattern_case_sensitive`: toggle case sensitivity for regex/glob evaluation.

Mix with `extensions` for deterministic filtering, e.g. `*.iso`, `*.img`, or `^.*backup.*\.iso$`.

## 🎛️ CLI & Menu

```bash
python -m fileops_toolkit.console.main --help
python -m fileops_toolkit.console.main precheck --config config/config.yml
python -m fileops_toolkit.console.main scan --config config/config.yml --verbosity maximal
python -m fileops_toolkit.console.main run --config config/config.yml --dry-run
python -m fileops_toolkit.console.main run --config config/config.yml --apply
python -m fileops_toolkit.console.main menu
```

Prefer seamless access? After running `./run.sh`, use the bundled launcher: `./bin/fileops-toolkit menu`.

The interactive menu contains dedicated sub-menus for:

- Adding/removing sources and destination folders.
- Switching flatten ↔ mirror modes.
- Editing duplicate handling (skip/archive/delete + archive location).
- Managing pattern lists (glob/regex) with validation.
- Toggling verbosity (`minimal`, `standard`, `maximal`) and default dry-run behaviour.
- Inspecting the most recent pipeline summary, dedup decisions, logs, and retry queue.

## ⚙️ Configuration

`config/config.yml` ships as a live example aligned with the CLI menu. Key options:

```yaml
sources:
  - /mnt/c
  - /mnt/d
  - /mnt/f
  - /mnt/h
remote_sources:
  - target: pierringshot@10.249.162.31:~/Desktop/WABACore.AI/
    name: wabacore-ai
    rsync_args: ['-avz', '--info=progress2']
destination: /mnt/e
extensions: ['iso', 'ISO']
patterns: ['*.iso', '*.ISO']
pattern_mode: glob          # glob or regex
pattern_case_sensitive: false
operation_mode: flatten     # flatten or mirror
mirror_prefix_with_root: true
parallel_workers: 24
checksum_algo: ['md5']      # list of algorithms (md5, sha1, xxh128, ...)
deduplication_policy: prefer_newer
duplicates_policy: delete   # skip | archive | delete
duplicates_archive_dir: ./data/duplicates  # required when duplicates_policy: archive
remote_staging_dir: ./data/remote_staging
remote_rsync_args: ['-avz', '--info=progress2']
remote_parallel_workers: 2
transfer_tool: rsync
rsync_args:
  - "-aHAX"
  - "--sparse"
  - "--preallocate"
  - "--partial"
  - "--info=progress2,stats4"
max_retries: 3
retry_backoff_seconds: 1.0
retry_backoff_multiplier: 2.0
logging:
  dir: ./logs
  csv_file: operations-$(date +%F_%T).csv
  json_file: summary-$(run_id).json
  errors_file: errors.log
dry_run: false
verify_after_transfer: true
backup_duplicates_to: ./data/backup
min_free_bytes: 10737418240
verbosity: maximal
```

Update values via the interactive editor (`menu → 3`) or edit the file by hand; the CLI keeps menu and YAML in sync.

## 📒 Logging Schema

| Column | Description |
| --- | --- |
| `run_id` | UUIDv4 identifier for the pipeline execution. |
| `timestamp` | UTC timestamp per operation. |
| `worker` | Worker ID / thread name handling the transfer. |
| `src_path`, `dst_path` | Source and destination paths resolved during transfer. |
| `size_bytes` | File size at the time of decision. |
| `mtime_unix` | Source modification timestamp (seconds). |
| `hash` | Selected checksum(s) joined by `;`. |
| `decision` | `copied`, `skipped`, `replaced`, `duplicate`, `archived`, `deleted`. |
| `reason` | `size_diff`, `newer`, `hash_match`, `policy_skip`, `error`, etc. |
| `note` | Additional context (e.g. archive location). |
| `duration_ms` | Transfer duration in milliseconds. |
| `rsync_exit` | Exit code from `rsync` (or local copy sentinel). |
| `error_msg` | Captured stderr or exception message when failures occur. |
| `tool` | Transfer backend used (`rsync`, `shutil-copy`). |
| `attempts` | Number of retries attempted. |
| `verified` | `true/false` result of post-transfer verification. |

JSON summaries mirror CSV entries and power dashboards or analytics pipelines. `errors.log` captures failure-only events for quick triage.

## ✅ Preflight & Verification

- Checks existence and permissions for sources, destination, duplicate archive, and backup directories (auto-creates when allowed).
- Validates dependencies: `find`, `rsync`, `xargs`, configured checksum binaries, and optional `fd`.
- Confirms free-space thresholds before transfers.
- Offers per-run verification to assert size/hash parity after `rsync`.

## 🚀 Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh              # boots venv, installs editable package, launches menu
./bin/fileops-toolkit run --config config/config.yml --dry-run
```

## 🧪 Validation Tips

- Use `python -m compileall src` or the provided smoke tests before large runbooks.
- Exercise both `flatten` and `mirror` modes with sample data to validate duplicate policies (`archive` moves files into `duplicates_archive_dir`).
- When enabling remote sources, manage targets via `menu → Remote source management`; run `precheck` to confirm staging prereqs and `sshpass` availability when storing passwords.
- For destructive duplicate actions (`delete`), confirm `dry_run: false` is intentional.

## 📜 License

MIT License © 2025 — FileOps Toolkit Authors
