import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.nlp_processor import _extract_acting_directive  # noqa: E402
from services.tts_service import _apply_acting_directive  # noqa: E402


def test_extract_acting_directive_from_parenthetical_prefix():
    directive, cleaned = _extract_acting_directive("(whisper, tense) Keep your voice down.")
    assert directive == "whisper, tense"
    assert cleaned == "Keep your voice down."


def test_extract_acting_directive_from_bracket_prefix():
    directive, cleaned = _extract_acting_directive("[shout] Run!")
    assert directive == "shout"
    assert cleaned == "Run!"


def test_merge_acting_directive_into_voice_settings():
    base = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.2}
    updated = _apply_acting_directive(base, "whisper, tense")
    # whisper increases stability and lowers style first.
    assert updated["stability"] >= 0.5
    assert updated["style"] <= 0.2
    # tense then raises style a bit (still bounded).
    assert 0.0 <= updated["style"] <= 1.0
