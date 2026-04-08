import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.audio_mixer import _scene_profile, _find_asset_candidates, _master_radio_mix  # noqa: E402


def test_scene_profile_detects_hallway():
    profile = _scene_profile("Old stone hallway with echoes")
    # Hall/cavern style spaces should have stronger wet layer.
    assert profile["wet_db"] > -16.0
    assert profile["echo_delay_ms"] >= 110


def test_scene_profile_detects_outdoor():
    profile = _scene_profile("Windy forest night outside")
    # Outdoor scenes should be drier than hall.
    assert profile["wet_db"] <= -20.0
    assert profile["echo_delay_ms"] <= 80


def test_find_asset_candidates_handles_missing_library():
    # Should gracefully return no candidates when assets are not present.
    candidates = _find_asset_candidates("foley", "footsteps_fast")
    assert isinstance(candidates, list)


def test_master_radio_mix_applies_headroom_limit():
    try:
        from pydub.generators import Sine
    except Exception:
        # If pydub isn't available in a constrained environment, skip this assertion.
        return

    hot_tone = (Sine(440).to_audio_segment(duration=1400) + 4).fade_in(10).fade_out(30)
    mastered = _master_radio_mix(hot_tone)

    assert len(mastered) == len(hot_tone)
    assert mastered.max_dBFS <= -0.7
