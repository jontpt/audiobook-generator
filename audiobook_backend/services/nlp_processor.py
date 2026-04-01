"""
services/nlp_processor.py
NLP pipeline:
  1. Sentence segmentation
  2. Dialogue detection & speaker attribution
  3. Character name extraction (NER)
  4. Emotion / scene tagging (rule-based + optional transformer)
  5. Returns structured TextSegment data
"""
from __future__ import annotations
import re
import logging
from typing import Optional
from models.schemas import TextSegment, SegmentType, EmotionTag, Gender, Character

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Dialogue patterns
# ─────────────────────────────────────────────────────────────────────────────

# Match "quoted text" – handles "", '', «», and curly quotes
QUOTE_PATTERN = re.compile(
    r'[""«]([^""»]+)[""»]|'   # smart / guillemet quotes
    r'"([^"]+)"',              # straight double quotes
    re.DOTALL
)

# Speaker attribution: "he said", "Alice whispered", "said John" etc.
SPEAKER_AFTER  = re.compile(
    r'[""»,]\s*(?:said|asked|whispered|shouted|exclaimed|replied|cried|'
    r'muttered|answered|called|breathed|snapped|groaned|laughed|sighed|'
    r'stated|remarked|added|continued|interrupted|insisted)\s+([A-Z][a-z]+)',
    re.IGNORECASE
)
SPEAKER_BEFORE = re.compile(
    r'([A-Z][a-z]+)\s+(?:said|asked|whispered|shouted|exclaimed|replied|'
    r'cried|muttered|answered|called|snapped|groaned|laughed|sighed|stated|'
    r'remarked|added|continued|interrupted|insisted)\s*[,:]?',
    re.IGNORECASE
)
PRONOUN_MAP = {
    'he': Gender.MALE, 'him': Gender.MALE, 'his': Gender.MALE,
    'she': Gender.FEMALE, 'her': Gender.FEMALE, 'hers': Gender.FEMALE,
}

# ─────────────────────────────────────────────────────────────────────────────
# Emotion keywords (rule-based fallback)
# ─────────────────────────────────────────────────────────────────────────────

EMOTION_KEYWORDS: dict[EmotionTag, list[str]] = {
    EmotionTag.HAPPY:      ['laugh', 'joy', 'smile', 'happy', 'delight', 'cheer', 'celebrate', 'excited'],
    EmotionTag.SAD:        ['cry', 'tear', 'sob', 'mourn', 'grieve', 'despair', 'sorrow', 'weep', 'lost'],
    EmotionTag.SUSPENSE:   ['fear', 'shadow', 'dark', 'creep', 'silent', 'danger', 'threat', 'suddenly', 'lurk'],
    EmotionTag.DRAMATIC:   ['rage', 'fury', 'betray', 'crash', 'shout', 'scream', 'clash', 'confront'],
    EmotionTag.ROMANTIC:   ['love', 'kiss', 'embrace', 'heart', 'tender', 'gentle', 'longing', 'passion'],
    EmotionTag.ACTION:     ['run', 'fight', 'chase', 'attack', 'explosion', 'battle', 'race', 'leap', 'dodge'],
    EmotionTag.MYSTERIOUS: ['mystery', 'secret', 'strange', 'unknown', 'hidden', 'whisper', 'clue', 'puzzle'],
    EmotionTag.PEACEFUL:   ['calm', 'quiet', 'breeze', 'gentle', 'soft', 'still', 'peaceful', 'serene', 'rest'],
}


def _detect_emotion(text: str) -> EmotionTag:
    """Simple keyword-frequency emotion detection."""
    lower = text.lower()
    scores: dict[EmotionTag, int] = {}
    for emotion, keywords in EMOTION_KEYWORDS.items():
        scores[emotion] = sum(lower.count(kw) for kw in keywords)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else EmotionTag.NEUTRAL


# ─────────────────────────────────────────────────────────────────────────────
# Character registry builder
# ─────────────────────────────────────────────────────────────────────────────

class CharacterRegistry:
    def __init__(self, book_id: str):
        self.book_id = book_id
        self._chars: dict[str, Character] = {}

    def _infer_gender(self, name: str, surrounding_text: str) -> Gender:
        """Infer gender from surrounding pronouns."""
        # Look 100 chars around the name
        idx = surrounding_text.lower().find(name.lower())
        if idx == -1:
            return Gender.NEUTRAL
        window = surrounding_text[max(0, idx-100): idx+100].lower()
        male_score   = sum(window.count(p) for p in ['he ', 'him ', 'his '])
        female_score = sum(window.count(p) for p in ['she ', 'her ', 'hers'])
        if male_score > female_score:   return Gender.MALE
        if female_score > male_score:   return Gender.FEMALE
        return Gender.NEUTRAL

    def register(self, name: str, surrounding_text: str = "") -> Character:
        if name not in self._chars:
            gender = self._infer_gender(name, surrounding_text)
            self._chars[name] = Character(
                book_id=self.book_id,
                name=name,
                gender=gender,
                appearance_count=0,
            )
        char = self._chars[name]
        char.appearance_count += 1
        return char

    def all_characters(self) -> list[Character]:
        return list(self._chars.values())


# ─────────────────────────────────────────────────────────────────────────────
# Spacy NER (lazy-loaded)
# ─────────────────────────────────────────────────────────────────────────────

_nlp = None
_nlp_tried = False


def _get_nlp():
    global _nlp, _nlp_tried
    if _nlp_tried:
        return _nlp
    _nlp_tried = True
    try:
        import spacy
        try:
            _nlp = spacy.load("en_core_web_sm")
            logger.info("Loaded spaCy model en_core_web_sm")
        except OSError:
            logger.warning("spaCy model not found — running NER-lite mode (regex only)")
    except ImportError:
        logger.warning("spaCy not installed — running NER-lite mode")
    return _nlp


def _extract_person_names_spacy(text: str) -> list[str]:
    nlp = _get_nlp()
    if not nlp:
        return []
    doc = nlp(text[:10_000])  # Limit to first 10k chars for speed
    return list({ent.text for ent in doc.ents if ent.label_ == "PERSON"
                 and len(ent.text) > 2 and ent.text.replace(" ", "").isalpha()})


# ─────────────────────────────────────────────────────────────────────────────
# Core analysis function
# ─────────────────────────────────────────────────────────────────────────────

def analyze_paragraph(
    paragraph: str,
    book_id: str,
    chapter_idx: int,
    para_idx: int,
    registry: CharacterRegistry,
) -> list[TextSegment]:
    """
    Decompose a paragraph into TextSegments (narration + dialogue pieces).
    Returns list of segments in order.
    """
    segments: list[TextSegment] = []
    emotion = _detect_emotion(paragraph)

    # Split paragraph into dialogue / narration pieces
    parts = _split_dialogue_narration(paragraph)

    for part_type, content, speaker in parts:
        if not content.strip():
            continue
        seg = TextSegment(
            book_id=book_id,
            chapter_index=chapter_idx,
            paragraph_index=para_idx,
            segment_type=part_type,
            speaker=speaker,
            text=content.strip(),
            emotion=emotion,
        )
        if speaker:
            registry.register(speaker, paragraph)
        segments.append(seg)

    return segments


def _split_dialogue_narration(
    paragraph: str,
) -> list[tuple[SegmentType, str, Optional[str]]]:
    """
    Split paragraph into ordered list of (type, text, speaker).
    """
    results: list[tuple[SegmentType, str, Optional[str]]] = []
    pos = 0
    text = paragraph

    for match in QUOTE_PATTERN.finditer(text):
        # Narration before this quote
        before = text[pos:match.start()].strip()
        if before:
            speaker_m = SPEAKER_BEFORE.search(before)
            results.append((SegmentType.NARRATION, before, None))

        # The quoted dialogue
        dialogue = match.group(1) or match.group(2) or ""
        # Try to find speaker after this dialogue
        after_start = match.end()
        after_text = text[after_start:after_start + 80]
        speaker_m = SPEAKER_AFTER.search(text[max(0, match.start()-5):after_start+80])
        speaker = speaker_m.group(1) if speaker_m else None

        # Fallback: look for "Name said/asked" before the quote
        if not speaker:
            before_text = text[max(0, match.start()-60):match.start()]
            sp_before = SPEAKER_BEFORE.search(before_text)
            speaker = sp_before.group(1) if sp_before else None

        results.append((SegmentType.DIALOGUE, dialogue, speaker))
        pos = match.end()

    # Remaining narration after last quote
    tail = text[pos:].strip()
    if tail:
        results.append((SegmentType.NARRATION, tail, None))

    # If no dialogue found, entire paragraph is narration
    if not results:
        results.append((SegmentType.NARRATION, paragraph.strip(), None))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Full book analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_book(
    chapters_data: list[dict],
    book_id: str,
) -> tuple[list[list[TextSegment]], CharacterRegistry]:
    """
    Analyze all chapters and return:
      - all_segments: list of chapter-segments (list[list[TextSegment]])
      - registry: CharacterRegistry with all discovered characters
    """
    registry = CharacterRegistry(book_id)
    all_chapter_segments: list[list[TextSegment]] = []

    # First pass: NER over full text for better character discovery
    full_text = '\n'.join(
        '\n'.join(ch['paragraphs']) for ch in chapters_data
    )
    spacy_names = _extract_person_names_spacy(full_text)
    for name in spacy_names:
        registry.register(name, full_text)

    # Second pass: per-paragraph segment extraction
    for ch_idx, chapter in enumerate(chapters_data):
        chapter_segments: list[TextSegment] = []
        for para_idx, paragraph in enumerate(chapter['paragraphs']):
            segs = analyze_paragraph(
                paragraph, book_id, ch_idx, para_idx, registry
            )
            chapter_segments.extend(segs)
        all_chapter_segments.append(chapter_segments)
        logger.debug(f"Chapter {ch_idx+1}: {len(chapter_segments)} segments")

    total_segs = sum(len(c) for c in all_chapter_segments)
    chars = registry.all_characters()
    logger.info(
        f"Analysis complete: {total_segs} segments, "
        f"{len(chars)} characters discovered"
    )
    return all_chapter_segments, registry


# ─────────────────────────────────────────────────────────────────────────────
# process_chapters — pipeline adapter
# ─────────────────────────────────────────────────────────────────────────────

def process_chapters(
    chapters_raw: list[dict],
    book_id: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Adapter called by pipeline.py.

    Accepts the raw chapter list from text_extraction:
        [{"title": str, "paragraphs": [str]}, ...]

    Returns three flat lists of dicts ready for db.insert():
        chapters:   [Chapter.model_dump(), ...]
        characters: [Character.model_dump(), ...]
        segments:   [TextSegment.model_dump(), ...]
    """
    from models.schemas import Chapter, EmotionTag
    from collections import Counter

    # Run NLP
    all_chapter_segs, registry = analyze_book(chapters_raw, book_id)

    # ── Build chapter dicts ─────────────────────────────────────────────────
    chapter_dicts: list[dict] = []
    for idx, (raw_ch, ch_segs) in enumerate(zip(chapters_raw, all_chapter_segs)):
        # Determine dominant emotion by frequency
        emotion_counts: Counter[str] = Counter(
            s.emotion.value for s in ch_segs if s.emotion
        )
        dominant = (
            EmotionTag(emotion_counts.most_common(1)[0][0])
            if emotion_counts
            else EmotionTag.NEUTRAL
        )
        chapter = Chapter(
            book_id=book_id,
            index=idx,
            title=raw_ch.get("title", f"Chapter {idx + 1}"),
            dominant_emotion=dominant,
            segment_count=len(ch_segs),
        )
        chapter_dicts.append(chapter.model_dump())

    # ── Build character dicts ───────────────────────────────────────────────
    character_dicts: list[dict] = [
        c.model_dump() for c in registry.all_characters()
    ]

    # ── Build segment dicts (flatten chapter lists) ─────────────────────────
    segment_dicts: list[dict] = [
        seg.model_dump()
        for ch_segs in all_chapter_segs
        for seg in ch_segs
    ]

    return chapter_dicts, character_dicts, segment_dicts
