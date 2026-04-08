"""
services/radio_markup.py
Parse lightweight radio-play directives from extracted chapter paragraphs.

Supported directives (phase 1):
  - SCENE: ...
  - AMBIENCE: ...
  - [FOLEY: ...]
  - [SFX: ...]    # alias of FOLEY
  - [MUSIC: ...]
"""
from __future__ import annotations

import re

INLINE_CUE_RE = re.compile(r"\[(FOLEY|SFX|MUSIC)\s*:\s*([^\]]+)\]", re.IGNORECASE)
PREFIX_DIRECTIVE_RE = re.compile(r"^\s*(SCENE|AMBIENCE)\s*:\s*(.*)$", re.IGNORECASE)
NEXT_PREFIX_RE = re.compile(r"\s+(SCENE|AMBIENCE)\s*:\s*", re.IGNORECASE)


def _tokenize_value(raw_value: str) -> tuple[str, dict[str, str]]:
    """
    Parse cue value payload.
    Example: "footsteps_fast, pan=left_to_center, dist=near"
      -> label: "footsteps_fast"
      -> params: {"pan": "left_to_center", "dist": "near"}
    """
    parts = [p.strip() for p in raw_value.split(",") if p.strip()]
    if not parts:
        return "", {}
    label = parts[0]
    params: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            params[key] = value
    return label, params


def _cue_item(
    cue_type: str,
    raw_value: str,
    chapter_index: int,
    paragraph_index: int,
) -> dict:
    label, params = _tokenize_value(raw_value)
    return {
        "type": cue_type,
        "value": raw_value.strip(),
        "label": label,
        "params": params,
        "chapter_index": chapter_index,
        "paragraph_index": paragraph_index,
    }


def _extract_from_paragraph(
    paragraph: str,
    chapter_index: int,
    paragraph_index: int,
) -> tuple[str, list[dict]]:
    text = paragraph.strip()
    cues: list[dict] = []

    # Parse leading SCENE/AMBIENCE directives, including chained lines collapsed
    # into one paragraph by extraction.
    while True:
        m = PREFIX_DIRECTIVE_RE.match(text)
        if not m:
            break
        cue_type = m.group(1).lower()
        remainder = m.group(2).strip()
        if not remainder:
            text = ""
            break

        next_directive = NEXT_PREFIX_RE.search(remainder)
        if next_directive:
            raw_value = remainder[:next_directive.start()].strip(" ,;-")
            text = remainder[next_directive.start():].lstrip()
        else:
            raw_value = remainder.strip(" ,;-")
            text = ""

        if raw_value:
            cues.append(_cue_item(cue_type, raw_value, chapter_index, paragraph_index))

    def _replace_inline(match: re.Match) -> str:
        cue_type = match.group(1).lower()
        if cue_type == "sfx":
            cue_type = "foley"
        raw_value = (match.group(2) or "").strip()
        if raw_value:
            cues.append(_cue_item(cue_type, raw_value, chapter_index, paragraph_index))
        return " "

    text = INLINE_CUE_RE.sub(_replace_inline, text)
    cleaned = " ".join(text.split()).strip()
    return cleaned, cues


def parse_radio_markup(chapters_data: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Return (cleaned_chapters, radio_cues).
    - cleaned_chapters have cue directives removed from paragraph text
    - radio_cues is a flat list suitable for UI preview
    """
    cleaned_chapters: list[dict] = []
    all_cues: list[dict] = []

    for ch_idx, chapter in enumerate(chapters_data):
        paragraphs = chapter.get("paragraphs", []) or []
        cleaned_paragraphs: list[str] = []
        for p_idx, paragraph in enumerate(paragraphs):
            if not isinstance(paragraph, str):
                continue
            cleaned, cues = _extract_from_paragraph(paragraph, ch_idx, p_idx)
            all_cues.extend(cues)
            if cleaned:
                cleaned_paragraphs.append(cleaned)
        cleaned_chapters.append({
            **chapter,
            "paragraphs": cleaned_paragraphs,
        })

    return cleaned_chapters, all_cues


def summarize_radio_cues(cues: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cue in cues:
        cue_type = str(cue.get("type", "")).lower()
        if not cue_type:
            continue
        counts[cue_type] = counts.get(cue_type, 0) + 1
    return counts
