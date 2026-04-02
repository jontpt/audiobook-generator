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
    r"remarked|added|continued|interrupted|insisted|began|demanded|"
    r"told|warned|murmured|growled|pleaded|urged|noted|declared|"
    r"responded|announced|questioned|admitted|confessed|suggested)"
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

# ── Known-name gender lookup (checked before pronoun counting) ───────────
_KNOWN_FEMALE_NAMES: frozenset[str] = frozenset({
    "sarah", "emma", "alice", "anna", "mary", "jane", "emily",
    "elizabeth", "rachel", "jessica", "lisa", "jennifer", "sophia",
    "olivia", "ava", "isabella", "mia", "charlotte", "amelia",
    "lily", "grace", "chloe", "victoria", "diana", "claire",
    "helen", "kate", "amy", "julia", "laura", "amanda", "rebecca",
    "natalie", "michelle", "katherine", "caroline", "eleanor",
    "abigail", "madison", "hannah", "samantha", "stephanie",
    "patricia", "sandra", "melissa", "donna", "carol", "ruth",
    "sharon", "deborah", "virginia", "maria", "margaret", "dorothy",
    "effie", "corinne", "bridget", "rosa", "nora", "iris", "vera", "pearl",
    "ruth", "agnes", "maud", "edith", "hazel", "ada", "flora", "ida",
})
_KNOWN_MALE_NAMES: frozenset[str] = frozenset({
    "marcus", "james", "john", "david", "michael", "robert",
    "thomas", "william", "richard", "charles", "george", "henry",
    "daniel", "matthew", "joseph", "peter", "andrew", "paul",
    "mark", "christopher", "alex", "alexander", "sam", "samuel",
    "jack", "jake", "ryan", "luke", "adam", "ben", "benjamin",
    "ethan", "noah", "liam", "mason", "logan", "lucas", "oliver",
    "aiden", "elijah", "harry", "edward", "arthur", "alfred",
    "frank", "fred", "eric", "kevin", "brian", "justin", "sean",
    "patrick", "ian", "alan", "scott", "keith", "carl", "roger",
    "miles", "floyd", "sam", "hamish", "clint", "wade", "vince", "gil",
    "dirk", "bart", "clem", "bud", "hank", "gus", "lenny", "mort",
})

def _name_gender(name: str) -> str | None:
    """Return 'male', 'female', or None based on known-name lookup."""
    if not name:
        return None
    first = name.strip().split()[0].lower()
    if first in _KNOWN_FEMALE_NAMES:
        return "female"
    if first in _KNOWN_MALE_NAMES:
        return "male"
    return None

class CharacterRegistry:
    def __init__(self, book_id: str):
        self.book_id = book_id
        self._chars: dict[str, Character] = {}
        self._explicit: set[str] = set()  # names locked by CHARACTERS: block

    def _infer_gender(self, name: str, surrounding_text: str) -> Gender:
        """Infer gender: check known-name dict first, then pronoun window."""
        # 1. Fast lookup by first name
        first = name.split()[0].lower()
        if first in _KNOWN_FEMALE_NAMES:
            return Gender.FEMALE
        if first in _KNOWN_MALE_NAMES:
            return Gender.MALE
        # 2. Pronoun-count fallback
        idx = surrounding_text.lower().find(name.lower())
        if idx == -1:
            return Gender.NEUTRAL
        window = surrounding_text[max(0, idx-100): idx+100].lower()
        male_score   = sum(window.count(p) for p in ['he ', 'him ', 'his '])
        female_score = sum(window.count(p) for p in ['she ', 'her ', 'hers'])
        if male_score > female_score:   return Gender.MALE
        if female_score > male_score:   return Gender.FEMALE
        return Gender.NEUTRAL

    def register_explicit(self, name: str, gender_str: str) -> "Character":
        """
        Register a character with an explicitly declared gender (from CHARACTERS: block).
        Marks the entry so it is never overwritten by pronoun-inference later.
        """
        gender_str = gender_str.lower()
        gender_map = {
            "male":    Gender.MALE,
            "female":  Gender.FEMALE,
            "neutral": Gender.NEUTRAL,
            "m":       Gender.MALE,
            "f":       Gender.FEMALE,
            "n":       Gender.NEUTRAL,
        }
        gender = gender_map.get(gender_str, Gender.NEUTRAL)
        if name not in self._chars:
            self._chars[name] = Character(
                book_id=self.book_id,
                name=name,
                gender=gender,
                appearance_count=0,
            )
        else:
            # Override any previously inferred gender with the explicit declaration
            self._chars[name].gender = gender
        self._explicit.add(name)
        logger.debug(f"CHARACTERS block: '{name}' locked as {gender.value}")
        return self._chars[name]

    def register(self, name: str, surrounding_text: str = "") -> Character:
        if name not in self._chars:
            gender = self._infer_gender(name, surrounding_text)
            self._chars[name] = Character(
                book_id=self.book_id,
                name=name,
                gender=gender,
                appearance_count=0,
            )
        elif name not in self._explicit:
            # Re-infer only if not explicitly declared — updates gender from new context
            pass  # keep existing inference; avoid flipping on short windows
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
    cross_para_state: "dict[str, str] | None" = None,
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
    parts = _split_dialogue_narration(paragraph, char_registry=_char_genders, cross_para_state=cross_para_state)

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
    cross_para_state: "dict[str, str] | None" = None,
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
    _last_speaker_by_gender: dict[str, str] = dict(cross_para_state or {})
    _pending_continuation: "str | None" = None

    # Pre-seed gender tracker from char_registry (handles paragraphs that open with quotes)
    if char_registry:
        for _n, _dg in char_registry.items():
            _fn = _n.split()[0].lower()
            if _fn in _KNOWN_FEMALE_NAMES or _dg == "female":
                _last_speaker_by_gender.setdefault("female", _n)
            elif _fn in _KNOWN_MALE_NAMES or _dg == "male":
                _last_speaker_by_gender.setdefault("male", _n)

    def _advance_tag(m_obj: re.Match, after_raw: str, after_start: int) -> "tuple[int, bool]":
        tail = after_raw[m_obj.end():]
        cm = re.search(r"([,])|([.!?])|(?=[\"\u201c])", tail)
        if cm:
            tag_end = after_start + m_obj.end() + cm.end()
            is_comma = bool(cm.group(1))
            # Treat "verb. <quote>" as continuation (same speaker continues)
            if not is_comma and cm.group(2):
                rest = tail[cm.end():].lstrip()
                is_comma = bool(rest and rest[0] in '\"\"\u201c')
            return tag_end, is_comma
        return after_start + len(after_raw), after_raw.rstrip().endswith(",")

    def _update_gender(name: str) -> None:
        # Name-dict takes priority over DB gender (fixes mis-labeled characters)
        _first = name.split()[0].lower()
        if _first in _KNOWN_FEMALE_NAMES:
            _last_speaker_by_gender["female"] = name
        elif _first in _KNOWN_MALE_NAMES:
            _last_speaker_by_gender["male"] = name
        else:
            # Fall back to DB gender if name not in known sets
            g = char_registry.get(name) if char_registry else None
            if g and g not in ("neutral", "unknown"):
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
                _candidate = sp_b.group(1)
                # Ignore bare pronouns — resolve them via gender tracker
                if _candidate.lower() in ("he", "she", "they", "it", "we", "i"):
                    _pg = _PRONOUN_GENDER.get(_candidate.lower())
                    if _pg and _pg in _last_speaker_by_gender:
                        speaker = _last_speaker_by_gender[_pg]
                else:
                    speaker = _candidate

        if speaker:
            _update_gender(speaker)

        if tag_end > after_start:
            # Also treat "verb. <quote>" as continuation:
            # if tag ends with period and next non-space is a quote, same speaker continues
            effective_comma = tag_comma
            if not tag_comma and speaker:
                _rest = text[tag_end:].lstrip()
                if _rest and _rest[0] in '\"\"\u201c':
                    effective_comma = True
            _pending_continuation = speaker if effective_comma else None

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
    char_declarations: "dict[str, str] | None" = None,
) -> tuple[list[list[TextSegment]], CharacterRegistry]:
    """
    Analyze all chapters and return:
      - all_segments: list of chapter-segments (list[list[TextSegment]])
      - registry: CharacterRegistry with all discovered characters

    char_declarations: optional {name: gender_str} from the CHARACTERS: block.
    These are locked in with priority over any pronoun-based inference.
    """
    registry = CharacterRegistry(book_id)
    all_chapter_segments: list[list[TextSegment]] = []

    # ── Pre-seed registry from CHARACTERS: block (highest priority) ──────────
    if char_declarations:
        for decl_name, decl_gender in char_declarations.items():
            registry.register_explicit(decl_name, decl_gender)
        logger.info(
            f"Pre-seeded registry with {len(char_declarations)} declared characters: "
            f"{list(char_declarations.keys())}"
        )

    # First pass: NER over full text for better character discovery
    full_text = '\n'.join(
        '\n'.join(ch['paragraphs']) for ch in chapters_data
    )
    spacy_names = _extract_person_names_spacy(full_text)
    for name in spacy_names:
        if name not in registry._explicit:   # don't overwrite declared characters
            registry.register(name, full_text)

    # Second pass: per-paragraph segment extraction
    _cross_para_state: dict[str, str] = {}  # carries gender context across paragraphs
    # Build book-level char→gender for cross-para lookups
    _char_genders_book: dict[str, str] = {c.name: c.gender.value for c in registry.all_characters() if c.gender}
    for ch_idx, chapter in enumerate(chapters_data):
        chapter_segments: list[TextSegment] = []
        for para_idx, paragraph in enumerate(chapter['paragraphs']):
            segs = analyze_paragraph(
                paragraph, book_id, ch_idx, para_idx, registry,
                cross_para_state=_cross_para_state,
            )
            # Update cross-paragraph gender state from this paragraph's speakers
            for _seg in segs:
                if _seg.speaker and _seg.speaker not in ("NARRATOR",):
                    _sg = _name_gender(_seg.speaker)
                    if not _sg and _char_genders_book.get(_seg.speaker):
                        _sg = _char_genders_book[_seg.speaker]
                    if _sg in ("male", "female"):
                        _cross_para_state[_sg] = _seg.speaker
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
    char_declarations: "dict[str, str] | None" = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Adapter called by pipeline.py.

    Accepts the raw chapter list from text_extraction:
        [{"title": str, "paragraphs": [str]}, ...]
    and an optional char_declarations dict from the CHARACTERS: block:
        {"CharName": "male"|"female"|"neutral", ...}

    Returns three flat lists of dicts ready for db.insert():
        chapters:   [Chapter.model_dump(), ...]
        characters: [Character.model_dump(), ...]
        segments:   [TextSegment.model_dump(), ...]
    """
    from models.schemas import Chapter, EmotionTag
    from collections import Counter

    # Run NLP (pass character declarations for explicit gender locking)
    all_chapter_segs, registry = analyze_book(chapters_raw, book_id, char_declarations=char_declarations)

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
feat: CharacterRegistry.register_explicit - lock gender from CHARACTERS block
