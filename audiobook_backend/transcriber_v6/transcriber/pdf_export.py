"""
PDF and external tool integration.

Handles Audiveris (PDF→MusicXML OMR) and MuseScore (MusicXML→PDF)
with auto-detection of Java and MuseScore executables.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .constants import (
    AUDIVERIS_TIMEOUT,
    JAVA_SEARCH_ROOTS,
    JAVA_TIMEOUT,
    MUSESCORE_SEARCH_NAMES,
    MUSESCORE_SEARCH_PATHS,
    MUSESCORE_TIMEOUT,
    SETTINGS_PATH_NAME,
)

LogFn = Callable[[str], None]


# ═══════════════════════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════════════════════

def load_settings() -> Dict[str, Any]:
    """Load user settings from home directory."""
    try:
        with open(Path.home() / SETTINGS_PATH_NAME, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    """Save user settings to home directory."""
    try:
        with open(Path.home() / SETTINGS_PATH_NAME, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  JAVA DETECTION
# ═══════════════════════════════════════════════════════════════════════

def find_java_executable() -> Optional[str]:
    """Return path to a working Java executable, or None."""
    # 1. PATH
    java = shutil.which("java")
    if java and _java_works(java):
        return java

    # 2. JAVA_HOME
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        for name in ("java.exe", "java"):
            candidate = Path(java_home) / "bin" / name
            if candidate.exists() and _java_works(str(candidate)):
                return str(candidate)

    # 3. Common installation roots
    for root_str in JAVA_SEARCH_ROOTS:
        root = Path(root_str)
        if not root.exists():
            continue
        try:
            subdirs = sorted(root.iterdir(), reverse=True)
        except PermissionError:
            continue
        for sub in subdirs:
            for name in ("java.exe", "java"):
                candidate = sub / "bin" / name
                if candidate.exists() and _java_works(str(candidate)):
                    return str(candidate)

    return None


def _java_works(exe: str) -> bool:
    """Check if java executable responds to -version."""
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, timeout=JAVA_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
#  MUSESCORE DETECTION
# ═══════════════════════════════════════════════════════════════════════

def find_musescore_executable() -> Optional[str]:
    """Return path to a working MuseScore executable, or None."""
    for name in MUSESCORE_SEARCH_NAMES:
        exe = shutil.which(name)
        if exe and _mscore_works(exe):
            return exe

    for path_str in MUSESCORE_SEARCH_PATHS:
        p = Path(path_str)
        if p.exists() and _mscore_works(str(p)):
            return str(p)

    return None


def _mscore_works(exe: str) -> bool:
    """Check if MuseScore executable responds to --version."""
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
#  PDF CONVERSION
# ═══════════════════════════════════════════════════════════════════════

def convert_to_pdf(musicxml_path: str, pdf_path: str, mscore_exe: str, log_fn: Optional[LogFn] = None) -> None:
    """Convert MusicXML to PDF via MuseScore CLI."""
    if not mscore_exe:
        raise RuntimeError("MuseScore is not configured. Use 'PDF Setup' to specify the executable path.")

    cmd = [mscore_exe, "-o", pdf_path, musicxml_path]
    if log_fn:
        log_fn(f"  {Path(mscore_exe).name} -o {Path(pdf_path).name} ...")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MUSESCORE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError("MuseScore timed out after 2 minutes.")
    except FileNotFoundError:
        raise RuntimeError(f"MuseScore executable not found: {mscore_exe}")

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "(no output)")[-2000:]
        raise RuntimeError(f"MuseScore exited with code {proc.returncode}:\n{tail}")

    if not Path(pdf_path).exists():
        raise RuntimeError("MuseScore finished but the PDF file was not created.")


def run_audiveris(
    jar_path: str,
    pdf_path: str,
    output_dir: str,
    log_fn: Optional[LogFn] = None,
    java_exe: Optional[str] = None,
) -> str:
    """Convert PDF to MusicXML via Audiveris CLI.

    Returns:
        Path to the produced .mxl/.musicxml file.
    """
    java = java_exe or find_java_executable() or "java"

    cmd = [java, "-jar", jar_path, "-batch", "-export", "-output", output_dir, pdf_path]
    if log_fn:
        log_fn(f"  {Path(java).name} -jar {Path(jar_path).name} -batch -export ...")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=AUDIVERIS_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Audiveris timed out after 5 minutes.")
    except FileNotFoundError:
        raise RuntimeError(f"Java executable not found: {java}")

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "(no output)")[-2000:]
        raise RuntimeError(f"Audiveris exited with code {proc.returncode}:\n{tail}")

    # Find output
    output_dir_path = Path(output_dir)
    stem = Path(pdf_path).stem
    candidates = sorted(
        list(output_dir_path.rglob("*.mxl")) + list(output_dir_path.rglob("*.musicxml")),
        key=lambda p: (0 if stem.lower() in p.stem.lower() else 1, 0 if p.suffix.lower() == ".mxl" else 1),
    )

    if not candidates:
        raise RuntimeError(f"Audiveris finished but no MusicXML found under {output_dir}.")

    return str(candidates[0])
