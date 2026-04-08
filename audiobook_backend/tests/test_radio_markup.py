import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.radio_markup import parse_radio_markup, summarize_radio_cues


def test_parse_radio_markup_extracts_and_cleans():
    chapters = [{
        "title": "Chapter 1",
        "paragraphs": [
            "SCENE: Train station AMBIENCE: rain_city_night",
            "NARRATOR: The platform shook. [FOLEY: footsteps_fast, pan=left_to_center, dist=near]",
            'MARA: "Did you bring it?" [MUSIC: tension_low, fade_in=1.2]',
        ],
    }]
    cleaned, cues = parse_radio_markup(chapters)
    counts = summarize_radio_cues(cues)

    assert len(cleaned) == 1
    assert len(cleaned[0]["paragraphs"]) == 2
    assert "SCENE:" not in " ".join(cleaned[0]["paragraphs"])
    assert counts["scene"] == 1
    assert counts["ambience"] == 1
    assert counts["foley"] == 1
    assert counts["music"] == 1

    foley = next(c for c in cues if c["type"] == "foley")
    assert foley["label"] == "footsteps_fast"
    assert foley["params"]["pan"] == "left_to_center"
    assert foley["params"]["dist"] == "near"
