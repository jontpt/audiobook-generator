import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.routes.books import _compute_revision_diff  # noqa: E402


def test_compute_revision_diff_detects_metrics_settings_voices_and_cues():
    base = {
        "id": "rev1",
        "revision_number": 1,
        "chapter_count": 3,
        "character_count": 4,
        "segment_count": 120,
        "total_words": 21000,
        "music_provider_preference": "auto",
        "music_style_preset": "ambient",
        "character_voice_plan": {
            "Archer": "voice_a",
            "Mara": "voice_m1",
        },
        "radio_cue_counts": {"scene": 3, "foley": 5},
    }
    compare = {
        "id": "rev2",
        "revision_number": 2,
        "chapter_count": 4,
        "character_count": 5,
        "segment_count": 130,
        "total_words": 23500,
        "music_provider_preference": "jamendo",
        "music_style_preset": "cinematic",
        "character_voice_plan": {
            "Archer": "voice_a2",   # changed
            "Mara": "voice_m1",
            "Wren": "voice_w",      # added
        },
        "radio_cue_counts": {"scene": 4, "foley": 2, "music": 3},
    }

    diff = _compute_revision_diff(base, compare)

    assert diff["metrics"]["chapter_count"]["delta"] == 1
    assert diff["metrics"]["total_words"]["delta"] == 2500
    assert len(diff["settings_changes"]) == 2
    assert diff["voice_plan"]["added_characters"] == ["Wren"]
    assert diff["voice_plan"]["removed_characters"] == []
    assert diff["voice_plan"]["changed_voices"][0]["character"] == "Archer"
    assert diff["cue_counts"]["delta"]["scene"] == 1
    assert diff["cue_counts"]["delta"]["foley"] == -3
    assert diff["cue_counts"]["delta"]["music"] == 3
    assert diff["has_changes"] is True


def test_compute_revision_diff_no_changes_reports_false():
    payload = {
        "chapter_count": 2,
        "character_count": 3,
        "segment_count": 50,
        "total_words": 8000,
        "music_provider_preference": "auto",
        "music_style_preset": "auto",
        "character_voice_plan": {"Narrator": "voice_n"},
        "radio_cue_counts": {"scene": 1},
    }

    diff = _compute_revision_diff(payload, payload)
    assert diff["has_changes"] is False
    assert diff["settings_changes"] == []
    assert diff["voice_plan"]["changed_voices"] == []
    assert diff["cue_counts"]["delta"] == {}
