"""Command-line interface for FileOps Toolkit."""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from enum import Enum
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
import yaml

from ..config_loader import load_config
from ..deduplication.engine import Decision, DedupResult
from ..discovery.engine import DiscoveredFile, discover_files
from ..metadata.scanner import get_file_metadata
from ..pipeline import OperationOutcome, PipelineStats, execute_pipeline
from ..prechecks import PreflightReport, run_prechecks
from ..remote import extract_remote_sources, sanitize_label, is_remote_target
from .banner import BANNER_ART, BANNER_TITLE, BANNER_AUTHOR

LAST_STATS: Optional[PipelineStats] = None
LAST_RESULTS: List[DedupResult] = []
LAST_OUTCOMES: List[OperationOutcome] = []


class Verbosity(Enum):
    MINIMAL = 'minimal'
    STANDARD = 'standard'
    MAXIMAL = 'maximal'


CURRENT_VERBOSITY: Verbosity = Verbosity.STANDARD
_BANNER_SHOWN = False


def _resolve_verbosity(value: Optional[str], *, fallback: Optional[str] = None) -> Verbosity:
    if value is None and fallback is not None:
        value = fallback
    if value is None:
        return Verbosity.STANDARD
    for option in Verbosity:
        if option.value == value:
            return option
    raise click.BadParameter(f'Unsupported verbosity: {value}')


def _maybe_show_banner(console: Console, force: bool = False) -> None:
    global _BANNER_SHOWN
    if _BANNER_SHOWN and not force:
        return
    console.print(BANNER_ART, highlight=False)
    console.print(BANNER_TITLE, style='bold cyan')
    console.print(BANNER_AUTHOR, style='dim')
    _BANNER_SHOWN = True


def _store_session(stats: PipelineStats, results: List[DedupResult], outcomes: List[OperationOutcome]) -> None:
    global LAST_STATS, LAST_RESULTS, LAST_OUTCOMES
    LAST_STATS = stats
    LAST_RESULTS = results
    LAST_OUTCOMES = outcomes


def _save_config(cfg_path: Path, cfg: dict) -> None:
    with cfg_path.open('w', encoding='utf-8') as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)


def _entry_target(entry: object) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        target = entry.get('target')
        if target:
            return target
        host = entry.get('host') or entry.get('user') or entry.get('username')
        path = entry.get('path')
        if host and path:
            return f'{host}:{path}'
    return ''


def _human_size(num_bytes: int) -> str:
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} PB'


def _format_mtime(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


def _size_style(size_bytes: int) -> str:
    if size_bytes >= 8 * 1024**3:
        return 'bold magenta'
    if size_bytes >= 1 * 1024**3:
        return 'magenta'
    if size_bytes >= 512 * 1024**2:
        return 'cyan'
    return 'bright_cyan'


def _checksum_display(value: Optional[str], verbose: bool) -> str:
    if not value:
        return ''
    if verbose or len(value) <= 12:
        return value
    return f'{value[:8]}…{value[-4:]}'


def _build_table(verbose: bool) -> Table:
    table = Table(
        title='Discovered files',
        box=box.SIMPLE_HEAVY,
        header_style='bold cyan',
        highlight=True,
    )
    table.add_column('Path', overflow='fold', style='bright_white')
    table.add_column('Relative', overflow='fold', style='white')
    table.add_column('Size', justify='right', style='magenta')
    table.add_column('Modified', justify='right', style='green')
    checksum_header = 'Checksum' if verbose else 'Checksum (short)'
    table.add_column(checksum_header, justify='left', style='yellow')
    return table


def _render_precheck(console: Console, report: PreflightReport, title: str = 'Preflight Report') -> None:
    table = Table(box=box.SIMPLE, header_style='bold cyan')
    table.add_column('Status', style='bold white')
    table.add_column('Message', style='white', overflow='fold')
    for message in report.info:
        table.add_row('[cyan]info[/cyan]', message)
    for message in report.warnings:
        table.add_row('[yellow]warning[/yellow]', message)
    for message in report.errors:
        table.add_row('[red]error[/red]', message)
    console.print(Panel(table, title=title, border_style='bright_blue'))


def _render_stats(console: Console, stats: PipelineStats, verbosity: Verbosity) -> None:
    if verbosity == Verbosity.MINIMAL:
        console.print(f'[bold cyan]Run:[/bold cyan] {stats.run_id}  '
                      f'[bold green]files:[/bold green] {stats.discovered_files}  '
                      f'[bold magenta]duration:[/bold magenta] {stats.duration_seconds:.2f}s  '
                      f'[bold yellow]errors:[/bold yellow] {stats.errors}')
        return

    summary = Table(box=box.SIMPLE_HEAVY, header_style='bold cyan')
    summary.add_column('Field', style='bold white')
    summary.add_column('Value', style='white', overflow='fold')
    summary.add_row('Run ID', stats.run_id)
    summary.add_row('Dry run', 'yes' if stats.dry_run else 'no')
    summary.add_row('Duration', f'{stats.duration_seconds:.2f} seconds')
    summary.add_row('Discovered files', str(stats.discovered_files))
    summary.add_row('Metadata collected', str(stats.metadata_collected))
    summary.add_row('Errors', str(stats.errors))
    summary.add_row('CSV log', str(stats.csv_log))
    summary.add_row('JSON log', str(stats.json_log))
    console.print(Panel(summary, title='Pipeline Summary', border_style='bright_green'))

    counts_table = Table(box=box.SIMPLE, header_style='bold cyan')
    counts_table.add_column('Decision')
    counts_table.add_column('Count', justify='right')
    for decision, count in sorted(stats.decision_counts.items()):
        counts_table.add_row(decision, str(count))
    console.print(counts_table)

    if verbosity != Verbosity.MAXIMAL and not (stats.report.warnings or stats.report.errors):
        return
    _render_precheck(console, stats.report, title='Preflight Recap')


def _render_decisions(console: Console, results: List[DedupResult], limit: int = 15, *, verbosity: Verbosity) -> None:
    if verbosity == Verbosity.MINIMAL:
        return
    if not results:
        console.print('[yellow]No deduplication results to display.[/yellow]')
        return
    limit = len(results) if verbosity == Verbosity.MAXIMAL else limit
    actionable = [r for r in results if r.decision in {Decision.COPY, Decision.REPLACE, Decision.COPY_WITH_SUFFIX}]
    duplicates = [r for r in results if r.decision == Decision.DUPLICATE]

    table = Table(title='Planned Transfers', box=box.SIMPLE_HEAVY, header_style='bold cyan')
    table.add_column('Decision', style='green')
    table.add_column('Source', overflow='fold', style='bright_white')
    table.add_column('Destination', overflow='fold', style='white')
    table.add_column('Reason', style='yellow')
    for entry in actionable[:limit]:
        table.add_row(entry.decision.name.lower(), str(entry.src.path), str(entry.dest_path), entry.reason)
    console.print(table)

    if duplicates and verbosity != Verbosity.MINIMAL:
        dup_table = Table(title='Duplicates Skipped', box=box.SIMPLE, header_style='bold cyan')
        dup_table.add_column('Source', overflow='fold', style='bright_white')
        dup_table.add_column('Reason', style='yellow')
        for entry in duplicates[:limit]:
            detail = entry.reason
            if entry.duplicate_action != 'skip':
                detail += f' ({entry.duplicate_action})'
            dup_table.add_row(str(entry.src.path), detail)
        console.print(dup_table)


def _render_failures(console: Console, outcomes: List[OperationOutcome], *, verbosity: Verbosity) -> None:
    failures = [o for o in outcomes if o.transfer and not o.transfer.success]
    if not failures:
        if verbosity != Verbosity.MINIMAL:
            console.print('[green]No transfer failures recorded.[/green]')
        return
    table = Table(title='Failed Transfers', box=box.SIMPLE_HEAVY, header_style='bold red')
    table.add_column('Source', overflow='fold')
    table.add_column('Destination', overflow='fold')
    table.add_column('Attempts', justify='right')
    table.add_column('Error', overflow='fold')
    for outcome in failures:
        transfer = outcome.transfer
        table.add_row(
            str(outcome.result.src.path),
            str(outcome.result.dest_path),
            str(transfer.attempts if transfer else 0),
            transfer.error_message if transfer else 'unknown error',
        )
    console.print(table)


def _show_logs(console: Console) -> None:
    if not LAST_STATS:
        console.print('[yellow]No pipeline run recorded yet.[/yellow]')
        return
    for path in (LAST_STATS.csv_log, LAST_STATS.json_log):
        if not path.exists():
            console.print(f'[yellow]Log file not found:[/yellow] {path}')
            continue
        console.print(Panel.fit(f'{path.name}\n{path}', border_style='bright_blue'))
        content = path.read_text(encoding='utf-8')
        lines = content.splitlines()
        preview = '\n'.join(lines[-20:]) if len(lines) > 20 else content
        console.print(preview or '[dim]Log file is empty.[/dim]')


def _show_retry_queue(console: Console) -> None:
    failures = [o for o in LAST_OUTCOMES if o.transfer and not o.transfer.success]
    if not failures:
        console.print('[green]Retry queue is empty.[/green]')
        return
    table = Table(title='Retry Queue', box=box.SIMPLE_HEAVY, header_style='bold cyan')
    table.add_column('Source', overflow='fold')
    table.add_column('Destination', overflow='fold')
    table.add_column('Attempts', justify='right')
    table.add_column('Last error', overflow='fold')
    for outcome in failures:
        transfer = outcome.transfer
        table.add_row(
            str(outcome.result.src.path),
            str(outcome.result.dest_path),
            str(transfer.attempts if transfer else 0),
            transfer.error_message if transfer else 'unknown error',
        )
    console.print(table)
    console.print('[dim]Re-run the pipeline to attempt failed transfers again.[/dim]')


def _remote_sources_menu(console: Console, cfg_path: Path) -> None:
    while True:
        cfg = load_config(cfg_path)
        remote_entries = list(cfg.get('remote_sources', []))
        _, remote_configs = extract_remote_sources(cfg)
        remote_by_target = {config.target: config for config in remote_configs}
        staging_dir = Path(cfg.get('remote_staging_dir', './data/remote_staging')).expanduser()
        default_args = ' '.join(cfg.get('remote_rsync_args', [])) if cfg.get('remote_rsync_args') else '<default>'
        parallel = cfg.get('remote_parallel_workers', cfg.get('parallel_workers', 1))

        table = Table(title='Remote Source Manager', box=box.SIMPLE_HEAVY, header_style='bold cyan')
        table.add_column('#', justify='right', style='bold white')
        table.add_column('Name', style='white')
        table.add_column('Target', style='white', overflow='fold')
        table.add_column('Staging dir', style='white', overflow='fold')
        table.add_column('Auth', style='white')
        table.add_column('Rsync args', style='white', overflow='fold')

        if remote_entries:
            for idx, entry in enumerate(remote_entries, start=1):
                target = _entry_target(entry)
                config = remote_by_target.get(target)
                alias = entry.get('name', '') if isinstance(entry, dict) else ''
                alias = alias or (config.name if config else sanitize_label(target))
                staging_path = staging_dir / alias
                auth = 'password' if isinstance(entry, dict) and entry.get('password') else 'key/agent'
                args = ' '.join(entry.get('rsync_args', [])) if isinstance(entry, dict) and entry.get('rsync_args') else '<default>'
                table.add_row(
                    str(idx),
                    alias,
                    target or '<invalid>',
                    str(staging_path),
                    auth,
                    args,
                )
        else:
            table.add_row('-', '<none>', '<none>', str(staging_dir), '-', default_args)

        console.print(table)
        console.print(f'[dim]Staging directory:[/dim] {staging_dir}')
        console.print(f'[dim]Default rsync args:[/dim] {default_args}')
        console.print(f'[dim]Parallel workers:[/dim] {parallel}')

        inline_remote = [
            str(src) for src in cfg.get('sources', [])
            if isinstance(src, str) and is_remote_target(src)
        ]
        inline_only = [src for src in inline_remote if src not in { _entry_target(entry) for entry in remote_entries }]
        if inline_only:
            console.print('[yellow]Inline remote entries detected under "sources":[/yellow]')
            for src in inline_only:
                console.print(f'  - {src}')
            console.print('[dim]Remove inline entries or re-add them via this menu for full management.[/dim]')

        options = {
            '1': 'Add remote source',
            '2': 'Remove remote source',
            '3': 'Set staging directory',
            '4': 'Set default rsync args',
            '5': 'Set remote parallel workers',
            '0': 'Back',
        }
        opt_table = Table(box=box.SIMPLE, header_style='bold cyan')
        opt_table.add_column('Option', justify='right', style='bold white')
        opt_table.add_column('Description', style='white')
        for key, desc in options.items():
            opt_table.add_row(key, desc)
        console.print(opt_table)

        choice = Prompt.ask('Select option', choices=list(options.keys()), default='0')
        if choice == '0':
            break
        if choice == '1':
            target = Prompt.ask('Remote rsync target (e.g. user@host:/path)')
            if not target:
                continue
            if not is_remote_target(target):
                confirm = Prompt.ask(
                    'Target does not look like an rsync/SSH path. Continue?',
                    choices=['y', 'n'],
                    default='n',
                )
                if confirm.lower() != 'y':
                    continue
            alias_default = sanitize_label(target)
            alias = Prompt.ask('Local alias (folder name under staging dir)', default=alias_default)
            identity = Prompt.ask('Identity file (blank to skip)', default='').strip()
            use_password = Prompt.ask('Store SSH password? [y/N]', choices=['y', 'n'], default='n')
            password = ''
            if use_password.lower() == 'y':
                password = getpass('Enter SSH password (input hidden): ') or ''
            ssh_opts_raw = Prompt.ask('Additional ssh options (space separated, blank to skip)', default='')
            rsync_args_raw = Prompt.ask(
                'Custom rsync args (space separated, blank for default)',
                default='',
            )
            entry_dict: Dict[str, Any] = {'target': target}
            if alias:
                entry_dict['name'] = alias
            if identity:
                entry_dict['identity_file'] = identity
            if password:
                entry_dict['password'] = password
            if ssh_opts_raw.strip():
                entry_dict['ssh_options'] = shlex.split(ssh_opts_raw)
            if rsync_args_raw.strip():
                entry_dict['rsync_args'] = shlex.split(rsync_args_raw)

            existing_targets = {_entry_target(item) for item in remote_entries}
            if target in existing_targets:
                console.print('[yellow]A remote source with this target already exists and will be updated.[/yellow]')
                for idx, item in enumerate(remote_entries):
                    if _entry_target(item) == target:
                        remote_entries[idx] = entry_dict
                        break
            else:
                remote_entries.append(entry_dict)
            cfg['remote_sources'] = remote_entries
            _save_config(cfg_path, cfg)
            console.print('[green]Remote source saved.[/green]')
        elif choice == '2':
            if not remote_entries:
                console.print('[yellow]No remote sources to remove.[/yellow]')
                continue
            selection = Prompt.ask('Enter number to remove (0 to cancel)', default='0')
            if selection.isdigit():
                idx = int(selection)
                if 1 <= idx <= len(remote_entries):
                    removed = remote_entries.pop(idx - 1)
                    cfg['remote_sources'] = remote_entries
                    _save_config(cfg_path, cfg)
                    console.print(f"[red]Removed remote[/red] {_entry_target(removed) or '<unknown>'}")
        elif choice == '3':
            current = str(cfg.get('remote_staging_dir', './data/remote_staging'))
            path_value = Prompt.ask('Remote staging directory', default=current)
            if path_value:
                cfg['remote_staging_dir'] = path_value
                _save_config(cfg_path, cfg)
                console.print(f'[green]Staging directory set to[/green] {path_value}')
        elif choice == '4':
            current = ' '.join(cfg.get('remote_rsync_args', []))
            default_prompt = current or '-avz --info=progress2'
            args_value = Prompt.ask('Default remote rsync args (blank to reset)', default=default_prompt)
            if args_value.strip():
                cfg['remote_rsync_args'] = shlex.split(args_value)
            else:
                cfg.pop('remote_rsync_args', None)
            _save_config(cfg_path, cfg)
            console.print('[green]Default remote rsync args updated.[/green]')
        elif choice == '5':
            current = str(cfg.get('remote_parallel_workers', cfg.get('parallel_workers', 1)))
            value = Prompt.ask('Remote parallel workers', default=current)
            try:
                remote_workers = max(1, int(value))
            except ValueError:
                console.print('[red]Please enter a positive integer.[/red]')
                continue
            cfg['remote_parallel_workers'] = remote_workers
            _save_config(cfg_path, cfg)
            console.print('[green]Remote parallel workers updated.[/green]')

        console.print()


@click.group()
def cli() -> None:
    """FileOps Toolkit CLI."""


@cli.command()
@click.option('--config', 'config_path', type=click.Path(exists=True), default='config/config.yml', show_default=True, help='Path to configuration file.')
@click.option('-v', '--verbose', is_flag=True, default=False, help='Alias for --verbosity maximal.')
@click.option('--verbosity', 'verbosity_option', type=click.Choice([v.value for v in Verbosity]), default=None, help='Adjust console output detail.')
@click.option('--no-color', is_flag=True, default=False, help='Disable coloured output.')
def scan(config_path: str, verbose: bool, verbosity_option: Optional[str], no_color: bool) -> None:
    """Scan configured sources and display discovered files."""
    console = Console(no_color=no_color)
    cfg = load_config(Path(config_path))
    _maybe_show_banner(console)
    global CURRENT_VERBOSITY
    verbosity = Verbosity.MAXIMAL if verbose else _resolve_verbosity(verbosity_option, fallback=cfg.get('verbosity'))
    CURRENT_VERBOSITY = verbosity

    local_sources, remote_sources = extract_remote_sources(cfg)
    sources = local_sources
    if remote_sources:
        console.print('[yellow]Remote sources detected. Scan previews local paths only; use precheck/run to stage remote data.[/yellow]')
    if not sources:
        console.print('[bold yellow]No local sources configured to scan.[/bold yellow]')
        return
    extensions = cfg.get('extensions')
    checksum_algo = cfg.get('checksum_algo')
    patterns = cfg.get('patterns')
    pattern_mode = cfg.get('pattern_mode', 'glob')
    case_sensitive = bool(cfg.get('pattern_case_sensitive', False))

    discovered = list(
        discover_files(
            sources,
            extensions,
            patterns=patterns,
            pattern_mode=pattern_mode,
            case_sensitive=case_sensitive,
        )
    )
    if not discovered:
        console.print('[bold yellow]No matching files were found.[/bold yellow]')
        return

    table = _build_table(verbosity == Verbosity.MAXIMAL)
    metadata = []
    progress_columns = (
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    )
    with Progress(*progress_columns, console=console, transient=True, disable=verbosity == Verbosity.MINIMAL) as progress:
        task_id: Optional[int] = None
        if verbosity != Verbosity.MINIMAL:
            task_id = progress.add_task('Collecting metadata', total=len(discovered))
        for item in discovered:
            meta = get_file_metadata(
                item.path,
                checksum_algo,
                source_root=item.root,
                relative_path=item.relative_path,
            )
            metadata.append(meta)
            if verbosity != Verbosity.MINIMAL and task_id is not None:
                path_text = Text(str(meta.path), style='bright_white')
                relative_text = Text(str(meta.relative_path or ''), style='white')
                size_text = Text(_human_size(meta.size_bytes), style=_size_style(meta.size_bytes))
                mtime_text = Text(_format_mtime(meta.mtime), style='green')
                checksum_text = Text(_checksum_display(meta.checksum, verbosity == Verbosity.MAXIMAL), style='yellow')
                table.add_row(path_text, relative_text, size_text, mtime_text, checksum_text)
                progress.advance(task_id)

    if verbosity != Verbosity.MINIMAL:
        console.print(table)
    total_size = sum(item.size_bytes for item in metadata)
    summary = Text()
    summary.append('Sources: ', style='bold cyan')
    summary.append(', '.join(sources) + '\n')
    summary.append('Patterns: ', style='bold cyan')
    summary.append(', '.join(patterns or ['<none>']) + '\n')
    summary.append('Files: ', style='bold green')
    summary.append(f'{len(metadata)}\n')
    summary.append('Total size: ', style='bold magenta')
    summary.append(_human_size(total_size))
    console.print(Panel(summary, title='Scan summary', border_style='bright_blue'))
    if verbosity != Verbosity.MINIMAL:
        algo = checksum_algo or '<disabled>'
        console.print(f'[dim]Checksum algorithm(s): {algo}[/dim]')
        console.print('[dim]Tip: use --no-color if capturing output to a file.[/dim]')


@cli.command()
@click.option('--config', 'config_path', type=click.Path(exists=True), default='config/config.yml', show_default=True, help='Path to configuration file.')
@click.option('--no-color', is_flag=True, default=False, help='Disable coloured output.')
def precheck(config_path: str, no_color: bool) -> None:
    """Run environment pre-checks."""
    console = Console(no_color=no_color)
    cfg = load_config(Path(config_path))
    _maybe_show_banner(console)
    local_sources, remote_sources = extract_remote_sources(cfg)
    precheck_cfg = dict(cfg)
    precheck_cfg['sources'] = local_sources
    report = run_prechecks(precheck_cfg, remote_sources=remote_sources)
    _render_precheck(console, report)
    if report.errors:
        raise click.ClickException('Prechecks reported blocking issues.')


@cli.command()
@click.option('--config', 'config_path', type=click.Path(exists=True), default='config/config.yml', show_default=True)
@click.option('--apply', is_flag=True, help='Override configuration dry_run and perform transfers.')
@click.option('--dry-run', 'force_dry_run', is_flag=True, help='Force dry-run regardless of configuration.')
@click.option('--show-decisions/--hide-decisions', default=True, help='Toggle dedup decision table output.')
@click.option('--decision-limit', type=int, default=15, show_default=True, help='Maximum rows to show per decision table.')
@click.option('-v', '--verbose', is_flag=True, default=False, help='Alias for --verbosity maximal.')
@click.option('--verbosity', 'verbosity_option', type=click.Choice([v.value for v in Verbosity]), default=None, help='Adjust console output detail.')
@click.option('--no-color', is_flag=True, default=False, help='Disable coloured output.')
def run(
    config_path: str,
    apply: bool,
    force_dry_run: bool,
    show_decisions: bool,
    decision_limit: int,
    verbose: bool,
    verbosity_option: Optional[str],
    no_color: bool,
) -> None:
    """Execute the full pipeline."""
    if apply and force_dry_run:
        raise click.BadParameter('Cannot use --apply and --dry-run together.')
    dry_override: Optional[bool] = None
    if apply:
        dry_override = False
    elif force_dry_run:
        dry_override = True

    console = Console(no_color=no_color)
    cfg = load_config(Path(config_path))
    _maybe_show_banner(console)
    global CURRENT_VERBOSITY
    verbosity = Verbosity.MAXIMAL if verbose else _resolve_verbosity(verbosity_option, fallback=cfg.get('verbosity'))
    CURRENT_VERBOSITY = verbosity

    stats, results, outcomes = execute_pipeline(cfg, console=console, dry_run_override=dry_override)
    _store_session(stats, results, outcomes)
    _render_stats(console, stats, verbosity)
    if show_decisions and verbosity != Verbosity.MINIMAL:
        display_limit = decision_limit if verbosity != Verbosity.MAXIMAL else len(results)
        _render_decisions(console, results, limit=display_limit, verbosity=verbosity)
    _render_failures(console, outcomes, verbosity=verbosity)


@cli.command('show-config')
@click.option('--config', 'config_path', type=click.Path(exists=True), default='config/config.yml', show_default=True)
@click.option('--no-color', is_flag=True, default=False, help='Disable coloured output.')
def show_config(config_path: str, no_color: bool) -> None:
    """Print the current configuration."""
    cfg = load_config(Path(config_path))
    console = Console(no_color=no_color)
    _maybe_show_banner(console)
    console.print_json(json.dumps(cfg, indent=2))


@cli.command()
@click.option('--config', 'config_path', type=click.Path(exists=True), default='config/config.yml', show_default=True)
@click.option('--no-color', is_flag=True, default=False)
def menu(config_path: str, no_color: bool) -> None:
    """Interactive management menu."""
    console = Console(no_color=no_color)
    _maybe_show_banner(console)
    cfg_path = Path(config_path)
    global CURRENT_VERBOSITY
    menu_options = {
        '1': 'Start full scan & collect',
        '2': 'Dry-run mode (simulation)',
        '3': 'Edit configuration (interactive)',
        '4': 'Show current progress',
        '5': 'Review dedup decisions',
        '6': 'View CSV/JSON logs',
        '7': 'Manage retry queue',
        '8': 'Remote source management',
        '9': 'Stop / Resume operations',
        '0': 'Exit',
    }

    def _print_menu(cfg: dict) -> None:
        disabled = set()
        if cfg.get('operation_mode', 'flatten') == 'mirror':
            disabled.update({'5', '7'})
        table = Table(title='FileOps Toolkit Menu', box=box.SIMPLE_HEAVY, header_style='bold cyan')
        table.add_column('Option', justify='right', style='bold white')
        table.add_column('Description', style='white')
        for key, desc in menu_options.items():
            if key in disabled:
                table.add_row(key, f'[dim]{desc}[/dim]')
            else:
                table.add_row(key, desc)
        table.add_row('', f'[dim]Current verbosity: {CURRENT_VERBOSITY.value}[/dim]')
        console.print(table)

    while True:
        cfg = load_config(cfg_path)
        if CURRENT_VERBOSITY is None:
            CURRENT_VERBOSITY = _resolve_verbosity(None, fallback=cfg.get('verbosity'))
        _print_menu(cfg)
        choice = Prompt.ask('Select option', choices=list(menu_options.keys()), default='0')
        if choice == '0':
            console.print('[green]Goodbye![/green]')
            break
        if cfg.get('operation_mode', 'flatten') == 'mirror' and choice in {'5', '7'}:
            console.print('[yellow]Option unavailable in mirror mode.[/yellow]')
            console.print()
            continue
        if choice == '1':
            stats, results, outcomes = execute_pipeline(cfg, console=console)
            _store_session(stats, results, outcomes)
            _render_stats(console, stats, CURRENT_VERBOSITY)
            _render_failures(console, outcomes, verbosity=CURRENT_VERBOSITY)
        elif choice == '2':
            stats, results, outcomes = execute_pipeline(cfg, console=console, dry_run_override=True)
            _store_session(stats, results, outcomes)
            _render_stats(console, stats, CURRENT_VERBOSITY)
            _render_decisions(console, results, limit=25, verbosity=CURRENT_VERBOSITY)
        elif choice == '3':
            _interactive_config_menu(console, cfg_path)
            cfg = load_config(cfg_path)
            CURRENT_VERBOSITY = _resolve_verbosity(None, fallback=cfg.get('verbosity'))
        elif choice == '4':
            if LAST_STATS:
                _render_stats(console, LAST_STATS, CURRENT_VERBOSITY)
            else:
                console.print('[yellow]No run available yet.[/yellow]')
        elif choice == '5':
            if LAST_RESULTS:
                _render_decisions(console, LAST_RESULTS, limit=25, verbosity=CURRENT_VERBOSITY)
            else:
                console.print('[yellow]No dedup decisions recorded yet.[/yellow]')
        elif choice == '6':
            _show_logs(console)
        elif choice == '7':
            _show_retry_queue(console)
        elif choice == '8':
            _remote_sources_menu(console, cfg_path)
        elif choice == '9':
            console.print('[dim]Pipeline runs synchronously; restart a run to resume operations.[/dim]')
        console.print()


if __name__ == '__main__':  # pragma: no cover
    cli()
def _interactive_config_menu(console: Console, cfg_path: Path) -> None:
    cfg = load_config(cfg_path)

    while True:
        overview = Table(title='Configuration Editor', box=box.SIMPLE_HEAVY, header_style='bold cyan')
        overview.add_column('Key', style='bold white')
        overview.add_column('Value', style='white', overflow='fold')
        overview.add_row('Sources', ', '.join(cfg.get('sources', [])))
        overview.add_row('Destination', str(cfg.get('destination')))
        overview.add_row('Patterns', ', '.join(cfg.get('patterns', []) or ['<none>']))
        overview.add_row('Extensions', ', '.join(cfg.get('extensions', []) or ['<none>']))
        overview.add_row('Operation mode', cfg.get('operation_mode', 'flatten'))
        overview.add_row('Duplicates policy', cfg.get('duplicates_policy', 'skip'))
        overview.add_row('Duplicates archive dir', str(cfg.get('duplicates_archive_dir', '<unset>')))
        remote_count = len(cfg.get('remote_sources', []))
        overview.add_row('Remote sources', str(remote_count))
        overview.add_row('Remote staging dir', str(cfg.get('remote_staging_dir', './data/remote_staging')))
        overview.add_row('Verbosity', cfg.get('verbosity', 'standard'))
        overview.add_row('Dry run', str(cfg.get('dry_run', True)))
        console.print(overview)

        options: Dict[str, str] = {
            '1': 'Add source path',
            '2': 'Remove source path',
            '3': 'Set destination',
            '4': 'Set operation mode',
            '5': 'Configure duplicate handling',
            '6': 'Edit file patterns',
            '7': 'Set verbosity',
            '8': 'Toggle dry-run default',
            '9': 'Manage remote sources',
            '0': 'Back to main menu',
        }
        opt_table = Table(box=box.SIMPLE, header_style='bold cyan')
        opt_table.add_column('Option', justify='right', style='bold white')
        opt_table.add_column('Description', style='white')
        for key, desc in options.items():
            opt_table.add_row(key, desc)
        console.print(opt_table)

        choice = Prompt.ask('Select option', choices=list(options.keys()), default='0')
        if choice == '0':
            return
        if choice == '1':
            new_source = Prompt.ask('Enter new source path')
            if new_source:
                path = Path(new_source).expanduser()
                path.mkdir(parents=True, exist_ok=True)
                sources = list(cfg.get('sources', []))
                if new_source not in sources:
                    sources.append(new_source)
                    cfg['sources'] = sources
                    _save_config(cfg_path, cfg)
                    console.print('[green]Source added.[/green]')
                else:
                    console.print('[yellow]Source already present.[/yellow]')
            continue
        if choice == '2':
            sources = list(cfg.get('sources', []))
            if not sources:
                console.print('[yellow]No sources to remove.[/yellow]')
                continue
            for idx, src in enumerate(sources, start=1):
                console.print(f'{idx}) {src}')
            selection = Prompt.ask('Enter number to remove (0 to cancel)', default='0')
            if selection.isdigit():
                idx = int(selection)
                if 1 <= idx <= len(sources):
                    removed = sources.pop(idx - 1)
                    cfg['sources'] = sources
                    _save_config(cfg_path, cfg)
                    console.print(f'[red]Removed[/red] {removed}')
                else:
                    console.print('[yellow]Selection out of range.[/yellow]')
            else:
                console.print('[yellow]Invalid selection.[/yellow]')
            continue
        if choice == '3':
            destination = Prompt.ask('Destination path', default=str(cfg.get('destination')))
            if destination:
                dest_path = Path(destination).expanduser()
                dest_path.mkdir(parents=True, exist_ok=True)
                cfg['destination'] = destination
                _save_config(cfg_path, cfg)
                console.print('[green]Destination updated.[/green]')
            continue
        if choice == '4':
            mode = Prompt.ask('Operation mode', choices=['flatten', 'mirror'], default=cfg.get('operation_mode', 'flatten'))
            cfg['operation_mode'] = mode
            if mode == 'mirror':
                prefix = Prompt.ask(
                    'Prefix preserved structure with source root name?',
                    choices=['yes', 'no'],
                    default='yes' if cfg.get('mirror_prefix_with_root', True) else 'no',
                )
                cfg['mirror_prefix_with_root'] = prefix == 'yes'
            _save_config(cfg_path, cfg)
            console.print('[green]Operation mode updated.[/green]')
            continue
        if choice == '5':
            policy = Prompt.ask('Duplicates policy', choices=['skip', 'archive', 'delete'], default=cfg.get('duplicates_policy', 'skip'))
            cfg['duplicates_policy'] = policy
            if policy == 'archive':
                archive_dir = Prompt.ask('Archive duplicates to directory', default=str(cfg.get('duplicates_archive_dir', './logs/duplicates')))
                Path(archive_dir).expanduser().mkdir(parents=True, exist_ok=True)
                cfg['duplicates_archive_dir'] = archive_dir
            else:
                cfg.pop('duplicates_archive_dir', None)
            _save_config(cfg_path, cfg)
            console.print('[green]Duplicate handling updated.[/green]')
            continue
        if choice == '6':
            current = ','.join(cfg.get('patterns', []) or [])
            response = Prompt.ask('Enter comma-separated patterns (empty to clear)', default=current)
            if response.strip():
                patterns = [item.strip() for item in response.split(',') if item.strip()]
                cfg['patterns'] = patterns
            else:
                cfg.pop('patterns', None)
            _save_config(cfg_path, cfg)
            console.print('[green]Patterns updated.[/green]')
            continue
        if choice == '7':
            verbosity = Prompt.ask('Verbosity', choices=[v.value for v in Verbosity], default=cfg.get('verbosity', 'standard'))
            cfg['verbosity'] = verbosity
            _save_config(cfg_path, cfg)
            console.print('[green]Verbosity updated.[/green]')
            continue
        if choice == '8':
            cfg['dry_run'] = not cfg.get('dry_run', True)
            _save_config(cfg_path, cfg)
            console.print(f"[cyan]dry_run set to[/cyan] {cfg['dry_run']}")
            continue
        if choice == '9':
            _remote_sources_menu(console, cfg_path)
            cfg = load_config(cfg_path)
            continue
        console.print('[yellow]Unknown option.[/yellow]')
