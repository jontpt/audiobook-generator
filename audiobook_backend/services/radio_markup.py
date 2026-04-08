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
INLINE_ANY_TAG_RE = re.compile(r"\[([A-Z_]+)\s*:", re.IGNORECASE)
INLINE_UNCLOSED_RE = re.compile(r"\[(FOLEY|SFX|MUSIC)\s*:[^\]]*$", re.IGNORECASE)

VALID_PAN_VALUES = {"left", "right", "center", "left_to_center", "right_to_center"}
VALID_DIST_VALUES = {"near", "mid", "far"}
ALLOWED_PARAMS_BY_TYPE: dict[str, set[str]] = {
    "scene": {"level"},
    "ambience": {"level"},
    "foley": {"duration", "level", "pan", "dist", "distance"},
    "music": {"duration", "level", "pan", "dist", "distance", "fade_in", "fade_out"},
}


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


def _is_number_like(raw: str) -> bool:
    text = (raw or "").strip().lower()
    if not text:
        return False
    suffixes = ("db", "ms", "s")
    for suffix in suffixes:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    try:
        float(text)
        return True
    except Exception:
        return False


def lint_radio_markup(chapters_data: list[dict], cues: list[dict]) -> list[dict]:
    """
    Return lint issues for authoring-time cue validation.
    Does not block processing; provides ergonomic feedback in UI.
    """
    issues: list[dict] = []

    # Paragraph-level structural checks
    for ch_idx, chapter in enumerate(chapters_data):
        paragraphs = chapter.get("paragraphs", []) or []
        for p_idx, paragraph in enumerate(paragraphs):
            if not isinstance(paragraph, str):
                continue
            text = paragraph.strip()
            if not text:
                continue

            for match in INLINE_ANY_TAG_RE.finditer(text):
                tag = (match.group(1) or "").strip().lower()
                if tag not in {"foley", "sfx", "music"}:
                    issues.append({
                        "severity": "error",
                        "code": "unknown_inline_cue_tag",
                        "message": f"Unknown inline cue tag [{tag.upper()}: ...]",
                        "hint": "Use [FOLEY:], [SFX:], or [MUSIC:].",
                        "chapter_index": ch_idx,
                        "paragraph_index": p_idx,
                    })

            if INLINE_UNCLOSED_RE.search(text):
                issues.append({
                    "severity": "error",
                    "code": "unclosed_inline_cue",
                    "message": "Inline cue appears to be missing a closing ']'.",
                    "hint": "Close cue tags like [FOLEY: footsteps_fast].",
                    "chapter_index": ch_idx,
                    "paragraph_index": p_idx,
                })

    # Parsed-cue semantic checks
    for cue in cues:
        cue_type = str(cue.get("type", "")).lower()
        params = cue.get("params") or {}
        label = str(cue.get("label", "")).strip()
        ch_idx = int(cue.get("chapter_index", 0) or 0)
        p_idx = int(cue.get("paragraph_index", 0) or 0)

        if not label:
            issues.append({
                "severity": "error",
                "code": "empty_cue_label",
                "message": f"{cue_type.upper()} cue is missing a label.",
                "hint": "Provide a cue label before optional params.",
                "chapter_index": ch_idx,
                "paragraph_index": p_idx,
            })

        allowed = ALLOWED_PARAMS_BY_TYPE.get(cue_type, set())
        for key, value in params.items():
            norm_key = str(key).lower().strip()
            raw_value = str(value).strip()
            if allowed and norm_key not in allowed:
                issues.append({
                    "severity": "warning",
                    "code": "unknown_param",
                    "message": f"Unexpected parameter '{norm_key}' on {cue_type.upper()} cue.",
                    "hint": f"Supported params: {', '.join(sorted(allowed))}.",
                    "chapter_index": ch_idx,
                    "paragraph_index": p_idx,
                })
                continue

            if norm_key == "pan" and raw_value.lower() not in VALID_PAN_VALUES:
                issues.append({
                    "severity": "warning",
                    "code": "invalid_pan_value",
                    "message": f"Unrecognized pan value '{raw_value}'.",
                    "hint": "Use left, right, center, left_to_center, or right_to_center.",
                    "chapter_index": ch_idx,
                    "paragraph_index": p_idx,
                })
            elif norm_key in {"dist", "distance"} and raw_value.lower() not in VALID_DIST_VALUES:
                issues.append({
                    "severity": "warning",
                    "code": "invalid_distance_value",
                    "message": f"Unrecognized distance value '{raw_value}'.",
                    "hint": "Use near, mid, or far.",
                    "chapter_index": ch_idx,
                    "paragraph_index": p_idx,
                })
            elif norm_key in {"duration", "level", "fade_in", "fade_out"} and not _is_number_like(raw_value):
                issues.append({
                    "severity": "warning",
                    "code": "invalid_numeric_param",
                    "message": f"Parameter '{norm_key}' should be numeric (got '{raw_value}').",
                    "hint": "Examples: level=-20, duration=900ms, fade_in=1.2s.",
                    "chapter_index": ch_idx,
                    "paragraph_index": p_idx,
                })

    # Stable sorting keeps issue rendering deterministic.
    return sorted(
        issues,
        key=lambda i: (
            int(i.get("chapter_index", 0) or 0),
            int(i.get("paragraph_index", 0) or 0),
            str(i.get("severity", "")),
            str(i.get("code", "")),
        ),
    )


def summarize_lint_issues(issues: list[dict]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0}
    for issue in issues:
        severity = str(issue.get("severity", "")).lower()
        if severity in counts:
            counts[severity] += 1
    return counts
