"""
Source score classification helpers.

Classifies instrument parts into families (string, woodwind, brass,
keyboard, percussion, voice) and extracts pitch ranges.
"""

from typing import Dict, Set, Tuple, Type

from music21 import instrument, stream

from music21 import note, chord


# ──────────────────────────────────────────────────────────────────────
#  music21 class → family mapping
# ──────────────────────────────────────────────────────────────────────

_M21_CLASS_MAP: Dict[type, str] = {}


def _build_class_map() -> None:
    class_defs: Dict[str, str] = {
        "Violin": "string", "Viola": "string", "Violoncello": "string",
        "Contrabass": "string", "StringInstrument": "string", "Harp": "string",
        "Flute": "woodwind", "Piccolo": "woodwind", "Oboe": "woodwind",
        "EnglishHorn": "woodwind", "Clarinet": "woodwind",
        "BassClarinet": "woodwind", "Bassoon": "woodwind",
        "Contrabassoon": "woodwind", "Recorder": "woodwind",
        "Saxophone": "woodwind", "Woodwind": "woodwind",
        "Horn": "brass", "Trumpet": "brass", "Trombone": "brass",
        "BassTrombone": "brass", "Tuba": "brass", "BrassInstrument": "brass",
        "Piano": "keyboard", "Harpsichord": "keyboard", "Organ": "keyboard",
        "ElectricOrgan": "keyboard", "KeyboardInstrument": "keyboard",
        "Percussion": "percussion", "UnpitchedPercussion": "percussion",
        "Timpani": "percussion",
    }
    for name, family in class_defs.items():
        cls = getattr(instrument, name, None)
        if cls is not None:
            _M21_CLASS_MAP[cls] = family


_build_class_map()

# Compound instrument names that contain "bass" but are NOT string instruments
_BASS_COMPOUND_NON_STRING = {
    "bass trombone", "bass clarinet", "bass drum", "bass flute",
    "bass oboe", "bass trumpet", "bass saxophone", "bass recorder",
    "bass voice", "basso", "bassposaune", "bassklarinette",
}

_SOURCE_KEYWORD_MAP: Dict[str, str] = {
    "violin": "string", "violine": "string", "violino": "string", "vln": "string",
    "viola": "string", "vla": "string", "bratsche": "string",
    "cello": "string", "violoncello": "string", "vlc": "string",
    "contrabass": "string", "double bass": "string", "string bass": "string",
    "kontrabass": "string", "string": "string", "strings": "string",
    "harp": "string", "harfe": "string", "arpa": "string",
    "flute": "woodwind", "flauto": "woodwind", "flt": "woodwind",
    "piccolo": "woodwind", "picc": "woodwind",
    "oboe": "woodwind", "hautbois": "woodwind",
    "english horn": "woodwind", "cor anglais": "woodwind",
    "clarinet": "woodwind", "clarinetto": "woodwind", "klarinette": "woodwind",
    "clar": "woodwind", "bass clarinet": "woodwind",
    "bassoon": "woodwind", "fagotto": "woodwind", "fagott": "woodwind",
    "bsn": "woodwind", "fag": "woodwind",
    "contrabassoon": "woodwind", "saxophone": "woodwind", "sax": "woodwind",
    "recorder": "woodwind", "woodwind": "woodwind",
    "trumpet": "brass", "tromba": "brass", "trompete": "brass", "tpt": "brass",
    "trombone": "brass", "posaune": "brass", "tbn": "brass", "trb": "brass",
    "bass trombone": "brass", "bassposaune": "brass",
    "horn": "brass", "french horn": "brass", "waldhorn": "brass",
    "tuba": "brass", "cornet": "brass", "euphonium": "brass",
    "flugelhorn": "brass", "brass": "brass",
    "piano": "keyboard", "pianoforte": "keyboard", "klavier": "keyboard",
    "pno": "keyboard", "keyboard": "keyboard", "organ": "keyboard",
    "orgel": "keyboard", "harpsichord": "keyboard", "cembalo": "keyboard",
    "celesta": "keyboard",
    "percussion": "percussion", "perc": "percussion",
    "drum": "percussion", "drums": "percussion", "bass drum": "percussion",
    "timpani": "percussion", "timp": "percussion", "pauken": "percussion",
    "cymbal": "percussion", "snare": "percussion", "glockenspiel": "percussion",
    "xylophone": "percussion", "vibraphone": "percussion", "marimba": "percussion",
    "soprano": "voice", "alto": "voice", "tenor": "voice", "baritone": "voice",
    "voice": "voice", "vocal": "voice", "choir": "voice", "chorus": "voice",
}


def classify_source_part(part: stream.Part) -> Set[str]:
    """Classify a source part into one or more instrument families.

    Uses both the music21 instrument class and keyword matching on part names.
    """
    families: Set[str] = set()

    # Class-based detection
    try:
        inst = part.getInstrument()
        if inst:
            for cls, fam in _M21_CLASS_MAP.items():
                if isinstance(inst, cls):
                    families.add(fam)
            # MIDI channel 9 = percussion (0-indexed)
            if hasattr(inst, "midiChannel") and inst.midiChannel == 9:
                families.add("percussion")
    except Exception:
        pass

    # Keyword-based detection
    names = []
    try:
        inst = part.getInstrument()
        if inst and inst.instrumentName:
            names.append(inst.instrumentName.lower())
    except Exception:
        pass
    if part.partName:
        names.append(part.partName.lower())
    if hasattr(part, "partAbbreviation") and part.partAbbreviation:
        names.append(part.partAbbreviation.lower())

    combined = " ".join(names)
    for kw in sorted(_SOURCE_KEYWORD_MAP, key=len, reverse=True):
        if kw in combined:
            families.add(_SOURCE_KEYWORD_MAP[kw])

    # "bass" alone usually means string bass (unless it's a compound name)
    if "bass" in combined:
        if not any(c in combined for c in _BASS_COMPOUND_NON_STRING):
            families.add("string")

    if not families:
        families.add("unknown")
    return families


def get_source_range(part: stream.Part) -> Tuple[int, int]:
    """Get the actual MIDI pitch range of notes in a part.

    Returns:
        (lowest_midi, highest_midi) tuple. Defaults to (60, 72) if no notes found.
    """
    lo, hi = 127, 0
    for n in part.recurse().notes:
        if isinstance(n, note.Note):
            lo = min(lo, n.pitch.midi)
            hi = max(hi, n.pitch.midi)
        elif isinstance(n, chord.Chord):
            for p in n.pitches:
                lo = min(lo, p.midi)
                hi = max(hi, p.midi)
    return (lo, hi) if lo <= hi else (60, 72)
