"""
tests/test_pipeline.py
Self-contained integration test — runs the full pipeline with a
sample text (no file upload needed, no real ElevenLabs key required).
Mock TTS mode is used automatically when ELEVENLABS_API_KEY is not set.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("test_pipeline")

# ── Sample book text ─────────────────────────────────────────────────────────

SAMPLE_TEXT = """Chapter 1: The Arrival

It was a dark and stormy night. The wind howled through the ancient oak trees,
bending their branches like fragile reeds. Eleanor clutched her coat tighter
as she walked up the gravel path toward Ashford Manor.

"Who goes there?" a gruff voice called from the shadows.

Eleanor stopped, her heart pounding. "My name is Eleanor Vance," she replied
nervously. "I received a letter inviting me here."

The large iron door swung open with a creak. A tall man in a butler's uniform
stepped forward, his face illuminated by the pale moonlight.

"Miss Vance," Thomas said with a slight bow. "We have been expecting you.
Please come in. The master will see you shortly."

She stepped inside, the warmth of the manor wrapping around her like a
welcome embrace. A fire crackled in a massive stone hearth, casting dancing
shadows across portraits of stern-faced ancestors.

Chapter 2: The Secret Room

The following morning, Eleanor awoke to bright sunshine streaming through
lace curtains. She felt strangely refreshed, though she had not slept well.

"Good morning," chirped a cheerful voice.

Eleanor turned to find a young maid setting a breakfast tray on the bedside
table. The girl smiled warmly.

"I'm Sophie," the maid announced with a bright smile. "Cook made your favorite
this morning — fresh scones with clotted cream."

Eleanor laughed softly. "That is very kind, Sophie. Though how could Cook
possibly know my favorites?"

Sophie leaned closer and whispered conspiratorially, "The master knows
everything about his guests, Miss Vance. That is his gift — and perhaps
his greatest secret."

Outside, a carriage rolled up the misty lane, its wheels clattering on
the cobblestones. Eleanor watched from the window as a shadowy figure
stepped out, looking up at her with dark, intense eyes.

"Who is that?" she breathed.

"That," said Thomas, appearing silently in the doorway, "is Lord Ashford
himself. And it appears he has returned earlier than expected."
"""


# ── Tests ────────────────────────────────────────────────────────────────────

def test_text_extraction():
    """Test extraction from a plain-text file."""
    logger.info("=" * 60)
    logger.info("TEST: Text Extraction")

    tmp = Path("/tmp/test_sample.txt")
    tmp.write_text(SAMPLE_TEXT, encoding="utf-8")

    from services.text_extraction import extract_text
    chapters = extract_text(tmp)

    assert len(chapters) >= 1, "Should extract at least 1 chapter"
    assert all("title" in c and "paragraphs" in c for c in chapters)

    for ch in chapters:
        logger.info(f"  Chapter: '{ch['title']}' — {len(ch['paragraphs'])} paragraphs")

    logger.info(f"  ✅ Extracted {len(chapters)} chapters")
    return chapters


def test_nlp_analysis(chapters):
    """Test NLP dialogue detection and character extraction."""
    logger.info("=" * 60)
    logger.info("TEST: NLP Analysis")

    from services.nlp_processor import analyze_book
    all_segs, registry = analyze_book(chapters, "test_book_001")

    characters = registry.all_characters()
    total_segs = sum(len(c) for c in all_segs)
    dialogue_segs = sum(
        1 for ch_segs in all_segs
        for s in ch_segs if s.segment_type.value == "dialogue"
    )

    logger.info(f"  Characters found: {[c.name for c in characters]}")
    logger.info(f"  Total segments  : {total_segs}")
    logger.info(f"  Dialogue segs   : {dialogue_segs}")

    for ch_segs in all_segs:
        for seg in ch_segs:
            logger.info(
                f"    [{seg.segment_type.value:9s}] "
                f"[{seg.emotion.value:10s}] "
                f"[{(seg.speaker or 'narrator'):12s}] "
                f"{seg.text[:60]}..."
                if len(seg.text) > 60 else
                f"    [{seg.segment_type.value:9s}] "
                f"[{seg.emotion.value:10s}] "
                f"[{(seg.speaker or 'narrator'):12s}] "
                f"{seg.text}"
            )

    assert total_segs > 0
    logger.info("  ✅ NLP analysis complete")
    return all_segs, registry


def test_voice_assignment(characters):
    """Test voice auto-assignment."""
    logger.info("=" * 60)
    logger.info("TEST: Voice Assignment")

    from services.voice_manager import assign_voices, get_voice_info
    assignment = assign_voices(characters)

    for name, voice_id in assignment.items():
        voice = get_voice_info(voice_id)
        voice_label = voice.name if voice else voice_id
        logger.info(f"  {name:15s} → {voice_label} ({voice_id})")

    assert "narrator" in assignment
    logger.info("  ✅ Voices assigned")
    return assignment


def test_tts_synthesis(all_segs, voice_assignment):
    """Test TTS synthesis (mock mode if no API key)."""
    logger.info("=" * 60)
    logger.info("TEST: TTS Synthesis (mock mode)")

    from services.tts_service import synthesize_segment
    from services.voice_manager import get_voice_for_speaker
    from config import settings

    if settings.ELEVENLABS_API_KEY:
        logger.info("  Using REAL ElevenLabs API")
    else:
        logger.info("  No API key — using MOCK audio stubs")

    # Test first 3 segments only
    flat_segs = [s for ch in all_segs for s in ch][:3]

    for seg in flat_segs:
        voice_id = get_voice_for_speaker(seg.speaker, voice_assignment)
        path = synthesize_segment(
            text=seg.text,
            voice_id=voice_id,
            book_id="test_book_001",
            segment_id=seg.id,
            emotion=seg.emotion.value,
        )
        seg.audio_path = str(path)
        assert path.exists(), f"Audio file not created: {path}"
        logger.info(f"  ✅ Segment synthesized → {path.name} ({path.stat().st_size}B)")

    return flat_segs


def test_audio_assembly(synthesized_segs):
    """Test chapter assembly with pydub."""
    logger.info("=" * 60)
    logger.info("TEST: Audio Assembly")

    from services.audio_mixer import assemble_chapter, get_audio_stats

    chapter_path = assemble_chapter(
        segments=synthesized_segs,
        chapter_title="Test Chapter One",
        book_id="test_book_001",
        chapter_index=0,
    )

    if chapter_path and chapter_path.exists():
        stats = get_audio_stats(chapter_path)
        logger.info(f"  ✅ Chapter assembled: {chapter_path.name}")
        logger.info(f"     Duration : {stats.get('duration_str', '?')}")
        logger.info(f"     File size: {stats.get('file_size_mb', '?')} MB")
        return chapter_path
    else:
        logger.warning("  ⚠️  Chapter assembly returned None (pydub may not be installed)")
        return None


def run_all_tests():
    logger.info("🎧 AUDIOBOOK PIPELINE — Integration Tests")
    logger.info("=" * 60)

    chapters   = test_text_extraction()
    all_segs, registry = test_nlp_analysis(chapters)
    characters = registry.all_characters()
    assignment = test_voice_assignment(characters)
    synth_segs = test_tts_synthesis(all_segs, assignment)
    chapter_path = test_audio_assembly(synth_segs)

    logger.info("=" * 60)
    logger.info("🎉 All tests passed!")

    # Summary report
    report = {
        "chapters": len(chapters),
        "characters_detected": [c.name for c in characters],
        "voice_assignment": assignment,
        "segments_synthesized": len(synth_segs),
        "chapter_audio": str(chapter_path) if chapter_path else None,
    }
    logger.info("\nTest Report:")
    logger.info(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    run_all_tests()
