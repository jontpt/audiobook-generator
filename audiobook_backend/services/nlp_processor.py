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

_SPEECH_VERBS = (
    r"(?:said|asked|whispered|shouted|exclaimed|replied|cried|muttered|"
    r"answered|called|breathed|snapped|groaned|laughed|sighed|stated|"
    r"remarked|added|continued|interrupted|insisted)"
)

# ── speaker attribution patterns (anchored to start of after-text) ────────
# A: "Name verb"  e.g.  Sarah replied  /  Marcus said
SPEECH_TAG_NAME_VERB = re.compile(
    r"^\s*[,.]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+" + _SPEECH_VERBS,
)
# B: "verb Name"  e.g.  said Marcus
SPEECH_TAG_VERB_NAME = re.compile(
    r"^\s*[,.]?\s*" + _SPEECH_VERBS + r"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)
# C: pronoun + verb  e.g.  he said  /  she whispered
SPEECH_TAG_PRONOUN = re.compile(
    r"^\s*[,.]?\s*(he|she|they)\s+" + _SPEECH_VERBS,
    re.IGNORECASE,
)
# Fallback: "Name verb" anywhere in unprocessed before-text
SPEAKER_BEFORE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+" + _SPEECH_VERBS + r"\s*[,:]?",
)
SPEAKER_AFTER = SPEAKER_BEFORE  # alias for backward compatibility

_PRONOUN_GENDER: dict[str, str] = {
    "he": "male", "him": "male",
    "she": "female", "her": "female",
    "they": "neutral",
}
_SPEECH_TAG_WINDOW = 90
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
    # Build {name: gender} for pronoun resolution inside the parser
    _char_genders = {n: r.gender.value for n, r in registry._chars.items()}
    parts = _split_dialogue_narration(paragraph, char_registry=_char_genders)

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
    char_registry: "dict[str, str] | None" = None,
) -> list[tuple[SegmentType, str, Optional[str]]]:
    """
    Split paragraph into ordered list of (SegmentType, text, speaker_or_None).

    Priority order for speaker detection on each closing quote:
      1. "Name verb"  immediately after closing quote  (e.g. Sarah replied)
      2. "verb Name"  immediately after closing quote  (e.g. said Marcus)
      3. pronoun + verb after quote  → resolved via per-gender tracker
      4. Continuation: previous speech tag ended with comma → same speaker
      5. "Name verb" in unprocessed narration between last pos and this quote

    Speech tags are consumed (pos advanced) so they do NOT re-appear as
    orphaned NARRATION segments that would be read in the narrator voice.

    char_registry: optional {name: gender_str} for pronoun resolution.
    """
    results: list[tuple[SegmentType, str, Optional[str]]] = []
    pos = 0
    text = paragraph
    _last_speaker_by_gender: dict[str, str] = {}
    _pending_continuation: "str | None" = None

    def _advance_tag(m_obj: re.Match, after_raw: str, after_start: int) -> "tuple[int, bool]":
        tail = after_raw[m_obj.end():]
        cm = re.search(r"([,])|([.!?])|(?=[\"\u201c])", tail)
        if cm:
            return after_start + m_obj.end() + cm.end(), bool(cm.group(1))
        return after_start + len(after_raw), after_raw.rstrip().endswith(",")

    def _update_gender(name: str) -> None:
        if char_registry:
            g = char_registry.get(name)
            if g:
                _last_speaker_by_gender[g] = name

    for match in QUOTE_PATTERN.finditer(text):
        before = text[pos:match.start()].strip()
        if before:
            results.append((SegmentType.NARRATION, before, None))
            if char_registry:
                for cname in char_registry:
                    if cname in before:
                        _update_gender(cname)

        dialogue = match.group(1) or match.group(2) or ""
        after_start = match.end()
        next_q = QUOTE_PATTERN.search(text, after_start)
        win_end = next_q.start() if next_q else after_start + _SPEECH_TAG_WINDOW
        after_raw = text[after_start:min(win_end, after_start + _SPEECH_TAG_WINDOW)]

        speaker: "str | None" = None
        tag_end = after_start
        tag_comma = False

        m = SPEECH_TAG_NAME_VERB.match(after_raw)
        if m:
            speaker = m.group(1)
            tag_end, tag_comma = _advance_tag(m, after_raw, after_start)

        if not speaker:
            m = SPEECH_TAG_VERB_NAME.match(after_raw)
            if m:
                speaker = m.group(1)
                tag_end, tag_comma = _advance_tag(m, after_raw, after_start)

        if not speaker:
            m = SPEECH_TAG_PRONOUN.match(after_raw)
            if m:
                pronoun = m.group(1).lower()
                gender = _PRONOUN_GENDER.get(pronoun)
                if gender and gender in _last_speaker_by_gender:
                    speaker = _last_speaker_by_gender[gender]
                    tag_end, tag_comma = _advance_tag(m, after_raw, after_start)

        if not speaker and _pending_continuation:
            speaker = _pending_continuation

        if not speaker:
            before_text = text[pos:match.start()]
            sp_b = SPEAKER_BEFORE.search(before_text)
            if sp_b:
                speaker = sp_b.group(1)

        if speaker:
            _update_gender(speaker)

        if tag_end > after_start:
            _pending_continuation = speaker if tag_comma else None

        results.append((SegmentType.DIALOGUE, dialogue, speaker))
        pos = tag_end if tag_end > after_start else match.end()

    tail = text[pos:].strip()
    if tail:
        results.append((SegmentType.NARRATION, tail, None))

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
