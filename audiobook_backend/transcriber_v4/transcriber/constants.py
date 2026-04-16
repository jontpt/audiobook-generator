"""
Constants and configuration for the Brass Ensemble Transcriber.

All magic numbers, thresholds, and default values live here.
"""

from fractions import Fraction
from typing import NamedTuple


# ──────────────────────────────────────────────────────────────────────
#  Minimum durations and timing thresholds
# ──────────────────────────────────────────────────────────────────────

#: Minimum note duration in quarter lengths (64th note triplet)
MIN_NOTE_DURATION = Fraction(1, 1920)

#: Tolerance for float comparison in bar-length checks
BAR_EPSILON = 1e-6

#: Sparse measure threshold — if fewer than this fraction of source parts
#: have notes in a measure, treat it as a solo/unison passage.
SPARSE_MEASURE_THRESHOLD = 0.30

#: Pickup detection: minimum difference from full bar to flag as pickup
PICKUP_MIN_DIFF = Fraction(1, 8)


# ──────────────────────────────────────────────────────────────────────
#  Keyboard reduction constants
# ──────────────────────────────────────────────────────────────────────

#: MIDI pitch of middle C — split point for RH/LH keyboard hands
MIDDLE_C = 60

#: Maximum notes per hand in keyboard reduction
MAX_NOTES_PER_HAND = 5


# ──────────────────────────────────────────────────────────────────────
#  Voicing rule defaults
# ──────────────────────────────────────────────────────────────────────

#: Default voice crossing tolerance in semitones
DEFAULT_CROSSING_TOLERANCE = 2

#: Default minimum spacing between trombone and tuba (perfect 4th)
DEFAULT_TBN_TUBA_SPACING = 5


# ──────────────────────────────────────────────────────────────────────
#  PDF export constants
# ──────────────────────────────────────────────────────────────────────

#: MuseScore CLI timeout in seconds
MUSESCORE_TIMEOUT = 120

#: Audiveris CLI timeout in seconds (5 minutes)
AUDIVERIS_TIMEOUT = 300

#: Java version check timeout in seconds
JAVA_TIMEOUT = 8

#: Default title font size for PDF score credits
DEFAULT_TITLE_FONT_SIZE = 16

#: MIDI program numbers for vocal instruments (to be replaced)
VOCAL_MIDI_PROGRAMS = range(53, 56)  # 53-55: Voice Oohs, Aahs, Synth Voice

#: Default replacement MIDI program (Trumpet)
DEFAULT_INSTRUMENTAL_MIDI = 57


# ──────────────────────────────────────────────────────────────────────
#  File paths and settings
# ──────────────────────────────────────────────────────────────────────

#: User settings file location
SETTINGS_PATH_NAME = ".universal_transcriber_settings.json"


# ──────────────────────────────────────────────────────────────────────
#  Common Java installation search roots (Windows)
# ──────────────────────────────────────────────────────────────────────

JAVA_SEARCH_ROOTS = [
    "C:/Program Files/Java",
    "C:/Program Files/Eclipse Adoptium",
    "C:/Program Files/Eclipse Foundation",
    "C:/Program Files/Microsoft",
    "C:/Program Files/OpenJDK",
    "C:/Program Files/BellSoft",
    "C:/Program Files (x86)/Java",
]

#: MuseScore executable names to search for on PATH
MUSESCORE_SEARCH_NAMES = [
    "musescore4", "musescore3", "musescore",
    "mscore4", "mscore3", "mscore",
]

#: MuseScore executable paths to search for (Windows)
MUSESCORE_SEARCH_PATHS = [
    "C:/Program Files/MuseScore 4/bin/MuseScore4.exe",
    "C:/Program Files/MuseScore 3/bin/MuseScore3.exe",
    "C:/Program Files/MuseScore 3/bin/mscore3.exe",
    "C:/Program Files (x86)/MuseScore 3/bin/MuseScore3.exe",
    "C:/Program Files (x86)/MuseScore 3/bin/mscore3.exe",
    "C:/Program Files/MuseScore 4/bin/mscore4.exe",
]
