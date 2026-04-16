"""
Instrument database, tessitura definitions, and ensemble configurations.

All instrument metadata, tessitura tiers, ensemble definitions, and
free-text parsing logic live here.
"""

import re
from typing import Dict, List, NamedTuple, Optional, Tuple


class InstrumentInfo(NamedTuple):
    """Metadata for a target brass instrument.

    Attributes:
        display_name: Human-readable name (e.g. "Trumpet in Bb")
        m21_class: music21 instrument class name
        family: Instrument family string
        low_midi: Lowest playable MIDI pitch (concert/sounding)
        high_midi: Highest playable MIDI pitch (concert/sounding)
        transposition_semitones: Semitones LOWER the instrument sounds
            than written (0 = concert pitch, 2 = Bb instrument, 7 = F instrument)
    """
    display_name: str
    m21_class: str
    family: str
    low_midi: int
    high_midi: int
    transposition_semitones: int


# ═══════════════════════════════════════════════════════════════════════
#  INSTRUMENT DATABASE
# ═══════════════════════════════════════════════════════════════════════

INSTRUMENT_DB: Dict[str, InstrumentInfo] = {
    "Trumpet":       InstrumentInfo("Trumpet in Bb", "Trumpet",  "brass", 55, 82,  2),
    "French Horn":   InstrumentInfo("Horn in F",     "Horn",     "brass", 34, 77,  7),
    "Trombone":      InstrumentInfo("Trombone",      "Trombone", "brass", 34, 72,  0),
    "Tuba":          InstrumentInfo("Tuba",          "Tuba",     "brass", 22, 60,  0),
    "Cornet":        InstrumentInfo("Cornet in Bb",  "Trumpet",  "brass", 55, 82,  2),
    "Euphonium":     InstrumentInfo("Euphonium",     "Tuba",     "brass", 29, 67,  0),
    "Flugelhorn":    InstrumentInfo("Flugelhorn",    "Trumpet",  "brass", 52, 79,  2),
}


# ═══════════════════════════════════════════════════════════════════════
#  TESSITURA TIERS  (concert/sounding MIDI)
# ═══════════════════════════════════════════════════════════════════════

class TessituraTier(NamedTuple):
    """Safe and extended pitch ranges for an instrument role.

    'safe'     = comfortable; always target this band first.
    'extended' = used silently when needed; no flag raised.
    """
    safe: Tuple[int, int]
    extended: Tuple[int, int]


# Key: (instrument_name, role)
TESSITURA_TIERS: Dict[Tuple[str, str], TessituraTier] = {
    ("Trumpet",     "lead"):   TessituraTier(safe=(67, 86), extended=(60, 89)),
    ("Trumpet",     "upper"):  TessituraTier(safe=(62, 82), extended=(58, 86)),
    ("Trumpet",     "middle"): TessituraTier(safe=(57, 77), extended=(55, 82)),
    ("Trumpet",     "lower"):  TessituraTier(safe=(54, 72), extended=(52, 77)),
    ("Trumpet",     "bass"):   TessituraTier(safe=(52, 67), extended=(50, 72)),
    ("Flugelhorn",  "lower"):  TessituraTier(safe=(55, 77), extended=(52, 82)),
    ("Flugelhorn",  "bass"):   TessituraTier(safe=(57, 74), extended=(52, 77)),
    ("French Horn", "middle"): TessituraTier(safe=(45, 65), extended=(40, 70)),
    ("French Horn", "lower"):  TessituraTier(safe=(38, 60), extended=(34, 65)),
    ("Trombone",    "lower"):  TessituraTier(safe=(40, 70), extended=(34, 74)),
    ("Trombone",    "bass"):   TessituraTier(safe=(36, 65), extended=(34, 70)),
    ("Tuba",        "bass"):   TessituraTier(safe=(26, 53), extended=(22, 58)),
    ("Euphonium",   "lower"):  TessituraTier(safe=(36, 62), extended=(29, 67)),
    ("Cornet",      "lead"):   TessituraTier(safe=(65, 84), extended=(58, 86)),
    ("Cornet",      "upper"):  TessituraTier(safe=(60, 79), extended=(55, 82)),
}

# Legacy single-range fallback (used when no role is known yet)
TESSITURA_DB: Dict[str, Tuple[int, int]] = {
    "Trumpet":      (60, 76),
    "Cornet":       (60, 76),
    "Flugelhorn":   (52, 74),
    "French Horn":  (40, 62),
    "Trombone":     (40, 60),
    "Euphonium":    (36, 58),
    "Tuba":         (28, 48),
}


# ═══════════════════════════════════════════════════════════════════════
#  ENSEMBLE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

class VoiceDef(NamedTuple):
    """Definition of a single voice slot in an ensemble."""
    role: str
    instrument: str
    variants: List[str]


class EnsembleDef(NamedTuple):
    """Full definition of a brass ensemble configuration."""
    voices: List[VoiceDef]
    voicing: str  # "open", "close", "mixed"
    crossing_tolerance: int  # semitones
    min_spacing: Dict[Tuple[str, str], int]  # (upper_role, lower_role) -> min semitones


ENSEMBLE_DB: Dict[str, EnsembleDef] = {
    "Brass Trio": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",     ["Trumpet", "Cornet"]),
            VoiceDef("middle", "French Horn", ["French Horn"]),
            VoiceDef("lower",  "Trombone",    ["Trombone", "Euphonium"]),
        ],
        voicing="open",
        crossing_tolerance=3,
        min_spacing={("middle", "lower"): 0},
    ),
    "Brass Quartet": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",     ["Trumpet", "Cornet"]),
            VoiceDef("middle", "French Horn", ["French Horn"]),
            VoiceDef("lower",  "Trombone",    ["Trombone"]),
            VoiceDef("bass",   "Tuba",        ["Tuba", "Euphonium"]),
        ],
        voicing="open",
        crossing_tolerance=2,
        min_spacing={
            ("lower", "bass"): 5,
            ("middle", "lower"): 0,
        },
    ),
    "Brass Quintet": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",     ["Trumpet", "Cornet"]),
            VoiceDef("upper",  "Trumpet",     ["Trumpet", "Cornet"]),
            VoiceDef("middle", "French Horn", ["French Horn"]),
            VoiceDef("lower",  "Trombone",    ["Trombone"]),
            VoiceDef("bass",   "Tuba",        ["Tuba", "Euphonium"]),
        ],
        voicing="mixed",
        crossing_tolerance=2,
        min_spacing={
            ("lower", "bass"): 5,
            ("middle", "lower"): 0,
            ("upper", "middle"): 0,
        },
    ),
    "Trumpet Quartet": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",    ["Trumpet"]),
            VoiceDef("upper",  "Trumpet",    ["Trumpet"]),
            VoiceDef("middle", "Trumpet",    ["Trumpet"]),
            VoiceDef("lower",  "Flugelhorn", ["Flugelhorn", "Trumpet"]),
        ],
        voicing="close",
        crossing_tolerance=2,
        min_spacing={},
    ),
    "Trumpet Quintet": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",    ["Trumpet"]),
            VoiceDef("upper",  "Trumpet",    ["Trumpet"]),
            VoiceDef("middle", "Trumpet",    ["Trumpet"]),
            VoiceDef("lower",  "Trumpet",    ["Trumpet"]),
            VoiceDef("bass",   "Flugelhorn", ["Flugelhorn", "Trumpet"]),
        ],
        voicing="close",
        crossing_tolerance=2,
        min_spacing={},
    ),
    "Trumpet Sextet": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",    ["Trumpet"]),
            VoiceDef("lead",   "Trumpet",    ["Trumpet"]),
            VoiceDef("upper",  "Trumpet",    ["Trumpet"]),
            VoiceDef("upper",  "Trumpet",    ["Trumpet"]),
            VoiceDef("middle", "Trumpet",    ["Trumpet"]),
            VoiceDef("lower",  "Flugelhorn", ["Flugelhorn", "Trumpet"]),
        ],
        voicing="mixed",
        crossing_tolerance=2,
        min_spacing={},
    ),
    "Trumpet Septet": EnsembleDef(
        voices=[
            VoiceDef("lead",   "Trumpet",    ["Trumpet"]),
            VoiceDef("lead",   "Trumpet",    ["Trumpet"]),
            VoiceDef("upper",  "Trumpet",    ["Trumpet"]),
            VoiceDef("upper",  "Trumpet",    ["Trumpet"]),
            VoiceDef("middle", "Trumpet",    ["Trumpet"]),
            VoiceDef("middle", "Trumpet",    ["Trumpet"]),
            VoiceDef("lower",  "Flugelhorn", ["Flugelhorn", "Trumpet"]),
        ],
        voicing="mixed",
        crossing_tolerance=2,
        min_spacing={},
    ),
}

# Common ensemble presets: name → list of target instrument names
ENSEMBLE_PRESETS: Dict[str, List[str]] = {
    "Brass Trio":      ["Trumpet", "French Horn", "Trombone"],
    "Brass Quartet":   ["Trumpet", "French Horn", "Trombone", "Tuba"],
    "Brass Quintet":   ["Trumpet", "Trumpet", "French Horn", "Trombone", "Tuba"],
    "Trumpet Quartet": ["Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
    "Trumpet Quintet": ["Trumpet", "Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
    "Trumpet Sextet":  ["Trumpet", "Trumpet", "Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
    "Trumpet Septet":  ["Trumpet", "Trumpet", "Trumpet", "Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
}


# ═══════════════════════════════════════════════════════════════════════
#  FREE-TEXT PARSING
# ═══════════════════════════════════════════════════════════════════════

_TEXT_ALIASES: Dict[str, List[str]] = {
    "trumpet": ["Trumpet"], "tpt": ["Trumpet"], "tromba": ["Trumpet"],
    "french horn": ["French Horn"], "horn": ["French Horn"], "hn": ["French Horn"],
    "trombone": ["Trombone"], "trb": ["Trombone"], "tbn": ["Trombone"],
    "tuba": ["Tuba"],
    "cornet": ["Cornet"],
    "euphonium": ["Euphonium"],
    "flugelhorn": ["Flugelhorn"], "flugel": ["Flugelhorn"], "flg": ["Flugelhorn"],
    "brass trio": ["Trumpet", "French Horn", "Trombone"],
    "brass quartet": ["Trumpet", "French Horn", "Trombone", "Tuba"],
    "brass quintet": ["Trumpet", "Trumpet", "French Horn", "Trombone", "Tuba"],
    "trumpet quartet": ["Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
    "trumpet quintet": ["Trumpet", "Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
    "trumpet sextet":  ["Trumpet", "Trumpet", "Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
    "trumpet septet":  ["Trumpet", "Trumpet", "Trumpet", "Trumpet", "Trumpet", "Trumpet", "Flugelhorn"],
}


def parse_free_text(text: str) -> Optional[List[str]]:
    """Parse free-text instrument specification into a list of instrument names.

    Accepts things like:
      "brass quintet"
      "trumpet quartet"
      "2 trumpets, trombone, tuba"
      "reduce to brass trio"

    Returns:
        List of instrument names, or None if unrecognized.
    """
    text = text.lower().strip()
    # Strip common filler
    text = re.sub(r"^(reduce|arrange|convert|rewrite)\s+(to|for|into)\s+", "", text)
    text = re.sub(r"\s+", " ", text)

    # Try full text as an ensemble name first
    if text in _TEXT_ALIASES:
        return _TEXT_ALIASES[text]

    # Split by comma, "and", "+"
    parts = re.split(r"[,\+]|\band\b", text)
    result: List[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Handle "2 trumpets", "3 violins" etc
        m = re.match(r"(\d+)\s+(.+)", part)
        if m:
            count = int(m.group(1))
            name = m.group(2).strip()
        else:
            count = 1
            name = part

        # Depluralize carefully
        if name.endswith("sses"):
            name = name[:-2]
        elif name.endswith("oes"):
            name = name[:-1]
        elif name.endswith("s") and not name.endswith("ss") and not name.endswith("us"):
            name = name[:-1]
        name = name.strip()

        # Look up
        if name in _TEXT_ALIASES:
            for _ in range(count):
                result.extend(_TEXT_ALIASES[name])
        else:
            # Try partial match
            matched = False
            for alias, instruments in sorted(_TEXT_ALIASES.items(), key=lambda x: -len(x[0])):
                if alias in name or name in alias:
                    for _ in range(count):
                        result.extend(instruments)
                    matched = True
                    break
            if not matched:
                return None

    return result if result else None


def depluralize(name: str) -> str:
    """Remove plural suffixes from an instrument name."""
    name = name.strip()
    if name.endswith("sses"):
        return name[:-2]
    elif name.endswith("oes"):
        return name[:-1]
    elif name.endswith("s") and not name.endswith("ss") and not name.endswith("us"):
        return name[:-1]
    return name
