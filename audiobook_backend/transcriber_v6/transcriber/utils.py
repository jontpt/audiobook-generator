"""
Utility helpers shared across engine and PDF modules.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .constants import SETTINGS_PATH_NAME


def load_settings() -> Dict[str, Any]:
    """Load user settings from the home directory."""
    try:
        settings_path = Path.home() / SETTINGS_PATH_NAME
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    """Save user settings to the home directory."""
    try:
        settings_path = Path.home() / SETTINGS_PATH_NAME
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass
