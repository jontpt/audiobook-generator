import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.audio_mixer import _scene_profile, _find_asset_candidates  # noqa: E402


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
