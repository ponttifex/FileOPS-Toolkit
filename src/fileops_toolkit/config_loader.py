"""Configuration loader for FileOps Toolkit.

Parses YAML configuration files and returns Python dictionaries.  This
wrapper centralises YAML parsing and provides basic validation of
required fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


REQUIRED_KEYS = ['sources', 'destination']


def load_config(path: Path) -> Dict[str, Any]:
    """Load and validate a YAML configuration file.

    Args:
        path: Path to the YAML file.

    Returns:
        A dictionary of configuration values.

    Raises:
        ValueError: If required keys are missing.
    """
    with path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    missing = [key for key in REQUIRED_KEYS if key not in cfg]
    if missing:
        raise ValueError(f'Missing required configuration keys: {missing}')
    if 'extensions' not in cfg and 'patterns' not in cfg:
        raise ValueError("Configuration must define either 'extensions' or 'patterns'.")
    return cfg
