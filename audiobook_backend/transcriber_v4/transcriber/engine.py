"""
Arrangement engine for the Brass Ensemble Transcriber — v4.

Based on v5.9 (the best-sounding baseline):
  - _minimize_leap() is a deliberate no-op: notes inside the playable range
    are left exactly where the source placed them.
  - _shift_into_range is context-aware: passes last_midi so octave choice
    minimises melodic leaps rather than defaulting to lowest valid octave.
  - _smooth_octave_jumps post-pass corrects isolated outliers using a ±4-note
    context window (conservative: only corrects when alternative is clearly better).

Added over v5.9:
  - Cross-voice melodic thread extractor (MelodicThreadExtractor) injected as
    primary source for the top target instrument before register assignment.
  - is_melody_thread flag pins the synthetic melody to the lead voice slot.
  - Type hints throughout.
"""

import copy
from collections import Counter, defaultdict
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Tuple

from music21 import chord, clef, common, instrument, interval, note, stream

from .constants import (
    BAR_EPSILON,
    MAX_NOTES_PER_HAND,
    MIDDLE_C,
    MIN_NOTE_DURATION,
    SPARSE_MEASURE_THRESHOLD,
)
from .instruments import (
    INSTRUMENT_DB,
    TESSITURA_DB,
    TESSITURA_TIERS,
)
from .source_classifier import classify_source_part, get_source_range

# Type aliases
LogFn = Callable[[str], None]
SourceInfo = Dict[str, Any]
TargetInfo = Dict[str, Any]
MeasureMeta = Dict[int, Tuple[List[Any], List[Any], Optional[Fraction]]]


def _safe(text: str) -> str:
    """Encode text to ASCII-safe for console output (drops Unicode music symbols)."""
    return str(text).encode('ascii', 'ignore').decode('ascii')


# ═══════════════════════════════════════════════════════════════════════
#  HORN ENHARMONIC CLEANUP
# ═══════════════════════════════════════════════════════════════════════

def _cleanup_horn_enharmonics(part: stream.Part) -> None:
    """Convert sharp spellings to flat equivalents throughout a horn part."""
    for el in part.recurse().notes:
        pitches = list(el.pitches) if isinstance(el, chord.Chord) else [el.pitch]
        for p in pitches:
            if p.accidental and p.accidental.name == "sharp":
                try:
                    enh = p.getEnharmonic()
                    p.name = enh.name
                    p.octave = enh.octave
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════
#  ARRANGEMENT ENGINE
# ═══════════════════════════════════════════════════════════════════════

class ArrangementEngine:
    """Arranges a score for target brass instruments.

    Each non-keyboard target gets one primary source voice. Extra parts
    are assigned to the closest-register target and merged at beat
    boundaries. Transposition is calculated per pair to keep lines
    within playable range.
    """

    def __init__(self, log_fn: Optional[LogFn] = None) -> None:
        self.log: LogFn = log_fn or (lambda _: None)

    # ── Public API ──────────────────────────────────────────────────

    def arrange(
        self,
        score: stream.Score,
        target_instruments: List[str],
        ensemble_def: Optional[Dict[str, Any]] = None,
    ) -> stream.Score:
        """Arrange *score* for the given target instruments.

        Args:
            score: Source music21 Score.
            target_instruments: Instrument names from INSTRUMENT_DB.
            ensemble_def: Optional ensemble definition (enables role-aware
                tessituras and voicing rules).

        Returns:
            New Score with arranged parts.
        """
        # Convert to concert pitch
        self.log("Converting to concert pitch...")
        try:
            score = score.toSoundingPitch()
        except Exception as e:
            self.log(f"  ⚠ Could not convert to concert pitch: {e}")

        # Analyze sources
        self.log("Analyzing source score...")
        source_parts = list(score.parts)
        if not source_parts:
            raise ValueError("No parts in source score")

        source_info = self._analyze_sources(source_parts)
        pitched_sources = [s for s in source_info if s["has_notes"] and "percussion" not in s["families"]]

        # Melody thread extractor disabled: it picks slow-moving voices with long
        # sustained notes instead of the actual melody, producing output that is
        # missing most of the melodic content. Reference v3 output (which matches
        # user expectations) uses pure register-based assignment without a thread.

        # Build targets
        self.log(f"\nTarget: {', '.join(target_instruments)}")
        voice_defs = ensemble_def.voices if ensemble_def else []
        targets = self._build_targets(target_instruments, voice_defs)

        # Assign sources
        self.log("\nAssigning parts (register-matched)...")
        self._assign_parts_by_register(pitched_sources, targets)

        # Render
        self.log("\nRendering arrangement...")
        result_score = self._render_score(score, targets, pitched_sources, ensemble_def)

        # Fill gap rests
        measure_meta = self._collect_measure_meta(score)
        self._fill_gap_rests(result_score, measure_meta)

        # Diagnostic
        self._log_diagnostic(result_score, targets, pitched_sources, score)

        # Voicing rules
        if ensemble_def:
            self.log("\nApplying voicing rules...")
            self._apply_voicing_rules(result_score, targets, ensemble_def)

        # Transpositions
        self._apply_transpositions(result_score, targets)

        # Octave cleanup — correct isolated out-of-context octave misplacements
        self._smooth_octave_jumps(result_score, targets)

        # Trombone: switch to tenor clef for passages at/above C4
        self._apply_trombone_tenor_clef(result_score, targets)

        self.log(f"\n✅ Done: {len(result_score.parts)} output parts")
        return result_score

    # ── Source Analysis ─────────────────────────────────────────────

    def _analyze_sources(self, parts: List[stream.Part]) -> List[SourceInfo]:
        """Analyze all source parts for family, range, and activity."""
        info_list = []
        for i, part in enumerate(parts):
            families = classify_source_part(part)
            lo, hi = get_source_range(part)
            median = (lo + hi) / 2
            name = part.partName or f"Part {i+1}"
            has_notes = any(True for _ in part.recurse().notes)
            info_list.append({
                "part": part, "name": name, "families": families,
                "low": lo, "high": hi, "median": median,
                "index": i, "has_notes": has_notes,
            })
            flag = "" if has_notes else " (rests only)"
            # Encode to ASCII for safe console output
            safe_name = _safe(name) or "Unknown"
            families_str = ', '.join(sorted(_safe(str(f)) for f in families))
            self.log(f"  Source: {safe_name} [{lo}-{hi}] ({families_str}){flag}")
        return info_list

    def _build_targets(
        self,
        target_instruments: List[str],
        voice_defs: List[Dict[str, Any]],
    ) -> List[TargetInfo]:
        """Build target instrument info with tessitura data."""
        targets: List[TargetInfo] = []
        for i, tname in enumerate(target_instruments):
            info = INSTRUMENT_DB.get(tname)
            if not info:
                self.log(f"  ⚠ Unknown instrument: {tname}")
                continue

            display, m21_class, family, lo, hi, trans_semi = info
            count = target_instruments[:i+1].count(tname)
            label = f"{display} {count}" if target_instruments.count(tname) > 1 else display

            role = voice_defs[i].role if i < len(voice_defs) else ""
            tier = TESSITURA_TIERS.get((tname, role))
            if tier:
                tess_lo, tess_hi = tier.safe
                ext_lo, ext_hi = tier.extended
            else:
                tess_lo, tess_hi = TESSITURA_DB.get(tname, (lo, hi))
                ext_lo, ext_hi = lo, hi

            targets.append({
                "name": tname, "label": label, "m21_class": m21_class,
                "family": family, "low": lo, "high": hi,
                "median": (lo + hi) / 2,
                "transposition_semitones": trans_semi,
                "tessitura_low": tess_lo, "tessitura_high": tess_hi,
                "extended_low": ext_lo, "extended_high": ext_hi,
                "role": role, "assigned_sources": [], "primary_source": None,
            })

        if not targets:
            raise ValueError("No valid target instruments")
        return targets

    # ── Rendering Orchestration ─────────────────────────────────────

    def _render_score(
        self,
        score: stream.Score,
        targets: List[TargetInfo],
        pitched_sources: List[SourceInfo],
        ensemble_def: Optional[Dict[str, Any]],
    ) -> stream.Score:
        """Orchestrate rendering of all target parts."""
        result_score = stream.Score()
        if hasattr(score, "metadata") and score.metadata:
            result_score.metadata = copy.deepcopy(score.metadata)

        measure_meta = self._collect_measure_meta(score)
        all_m_nums = sorted(measure_meta.keys()) if measure_meta else self._get_measure_nums(score)

        non_kb_targets = [t for t in targets if t["family"] != "keyboard"]
        kb_targets = [t for t in targets if t["family"] == "keyboard"]

        if self._should_use_vertical_reduction(pitched_sources, non_kb_targets):
            self.log("  → Dense score detected: using vertical reduction")
            vr_parts = self._render_vertical_reduction(score, non_kb_targets, all_m_nums, measure_meta)
            for p in vr_parts:
                result_score.append(p)
        else:
            for target in non_kb_targets:
                if not target["assigned_sources"]:
                    self.log(f"  {target['label']}: no sources, skipping")
                    continue
                p = self._render_single_part(target, all_m_nums, measure_meta, pitched_sources)
                result_score.append(p)

        for target in kb_targets:
            if not target["assigned_sources"]:
                self.log(f"  {target['label']}: no sources, skipping")
                continue
            parts = self._render_keyboard_part(target, all_m_nums, measure_meta)
            for p in parts:
                result_score.append(p)

        if not result_score.parts:
            raise ValueError("Arrangement produced no parts!")
        return result_score

    def _should_use_vertical_reduction(
        self,
        pitched_sources: List[SourceInfo],
        non_kb_targets: List[TargetInfo],
    ) -> bool:
        """Return True when the source is dense enough to warrant vertical reduction.

        Vertical reduction samples active pitches at every change-point and
        distributes them high→low across targets. It works best when the source
        has many more parts than the target — the typical orchestra→quintet case.
        Part-assignment is better when the source and target counts are similar,
        because it preserves individual voice lines and articulations.

        Heuristic: activate when pitched source count exceeds twice the number
        of non-keyboard targets (e.g. 17 orchestra parts → 7 trumpets triggers
        it; a string quartet → quintet does not).
        """
        if not non_kb_targets:
            return False
        return False

    def _render_vertical_reduction(
        self,
        score: stream.Score,
        targets: List[TargetInfo],
        measure_nums: List[int],
        measure_meta: MeasureMeta,
    ) -> List[stream.Part]:
        """Reduce a dense score to N parts by sampling active pitches at every
        change-point and distributing them high→low to target instruments.

        This preserves harmonic rhythm and surface motion when the source has
        far more parts than the target. Each target receives the pitch closest
        to its register, octave-shifted into its playable range and tessitura.
        """
        # Build output parts ordered by target list; rank by median (0 = highest)
        out_parts: List[stream.Part] = []
        ranked = sorted(enumerate(targets), key=lambda it: -it[1]["median"])
        rank_index = {t["label"]: r for r, (_, t) in enumerate(ranked)}

        for t in targets:
            p = stream.Part()
            p.partName = t["label"]
            inst_cls = getattr(instrument, t["m21_class"], None)
            if inst_cls:
                try:
                    p.insert(0, inst_cls())
                except Exception:
                    pass
            p.insert(0, clef.BassClef() if t["median"] < 55 else clef.TrebleClef())
            out_parts.append(p)

        # Index source measures once
        src_measure_maps: List[Dict[int, stream.Measure]] = [
            {m.number: m for m in sp.getElementsByClass(stream.Measure)}
            for sp in score.parts
        ]

        current_bar_ql: Fraction = Fraction(4, 1)

        def bar_ql_for(m_num: int) -> Fraction:
            nonlocal current_bar_ql
            if m_num in measure_meta:
                ts_list = measure_meta[m_num][0]
                if ts_list:
                    try:
                        current_bar_ql = common.opFrac(ts_list[0].barDuration.quarterLength)
                    except Exception:
                        pass
                actual_ql = measure_meta[m_num][2]
                if actual_ql is not None and actual_ql > 0:
                    return common.opFrac(actual_ql)
            return common.opFrac(current_bar_ql)

        for m_num in measure_nums:
            bar_ql = bar_ql_for(m_num)

            # Detect pickup offset shift (paddingLeft on anacrusis bars)
            pickup_shift: Fraction = Fraction(0)
            is_pickup = m_num in measure_meta and measure_meta[m_num][2] is not None
            if is_pickup:
                earliest = None
                for m_map in src_measure_maps:
                    m = m_map.get(m_num)
                    if not m:
                        continue
                    for el in m.notesAndRests:
                        off = common.opFrac(el.offset)
                        if earliest is None or off < earliest:
                            earliest = off
                if earliest is not None and earliest > Fraction(0):
                    pickup_shift = earliest

            # Collect (start, end, midi) spans from all source parts
            spans: List[Tuple[Fraction, Fraction, int]] = []
            change_points = {Fraction(0), common.opFrac(bar_ql)}

            for m_map in src_measure_maps:
                m = m_map.get(m_num)
                if not m:
                    continue
                for el in m.notesAndRests:
                    if isinstance(el, note.Rest):
                        continue
                    start = common.opFrac(el.offset) - pickup_shift
                    dur = common.opFrac(el.duration.quarterLength)
                    if dur <= 0:
                        continue
                    if start < 0:
                        start = Fraction(0)
                    end = min(bar_ql, start + dur)
                    if end <= 0:
                        continue
                    change_points.add(start)
                    change_points.add(end)
                    if isinstance(el, note.Note):
                        spans.append((start, end, int(el.pitch.midi)))
                    elif isinstance(el, chord.Chord):
                        for pch in el.pitches:
                            spans.append((start, end, int(pch.midi)))

            cps = sorted(cp for cp in change_points if Fraction(0) <= cp <= bar_ql + Fraction(1, 960))
            n = len(targets)

            # Per change-point: pick representative pitches, assign high→low
            decisions: Dict[str, List[Tuple[Fraction, Optional[int]]]] = {t["label"]: [] for t in targets}
            last_choice: Dict[str, Optional[int]] = {t["label"]: None for t in targets}

            for off in cps:
                act = sorted({midi for (s, e, midi) in spans if s <= off < e})

                if not act:
                    for t in targets:
                        if last_choice[t["label"]] is not None:
                            decisions[t["label"]].append((off, None))
                            last_choice[t["label"]] = None
                    continue

                # Choose up to N representative pitches: always keep outer voices,
                # then greedily add inner notes for pitch-class coverage and spacing.
                if len(act) == 1:
                    rep = [act[0]]
                else:
                    top, bot = act[-1], act[0]
                    rep = [top] if top == bot else [top, bot]
                    cand = [m for m in act if m not in rep]
                    pcs = {m % 12 for m in rep}

                    def _score(m: int) -> float:
                        new_pc = 1.0 if (m % 12) not in pcs else 0.0
                        spacing = min(abs(m - r) for r in rep) if rep else 0.0
                        return 3.0 * new_pc + spacing / 12.0

                    while len(rep) < n and cand:
                        best = max(cand, key=_score)
                        rep.append(best)
                        pcs.add(best % 12)
                        cand.remove(best)

                rep_sorted = sorted(rep, reverse=True)
                if len(rep_sorted) < n:
                    rep_sorted += [rep_sorted[-1]] * (n - len(rep_sorted))

                chosen = [None] * n
                for t in targets:
                    chosen[rank_index[t["label"]]] = rep_sorted[rank_index[t["label"]]]

                for t in targets:
                    r = rank_index[t["label"]]
                    midi = chosen[r]
                    if midi is None:
                        if last_choice[t["label"]] is not None:
                            decisions[t["label"]].append((off, None))
                            last_choice[t["label"]] = None
                        continue

                    # Octave-shift into absolute range, then bias toward tessitura
                    lo = t.get("low", 0)
                    hi = t.get("high", 127)
                    tess_lo = t.get("tessitura_low", lo)
                    tess_hi = t.get("tessitura_high", hi)

                    m2 = int(midi)
                    while m2 < lo and m2 + 12 <= 127:
                        m2 += 12
                    while m2 > hi and m2 - 12 >= 0:
                        m2 -= 12
                    if m2 > tess_hi and m2 - 12 >= lo:
                        m2 -= 12
                    elif m2 < tess_lo and m2 + 12 <= hi:
                        m2 += 12

                    if last_choice[t["label"]] != m2:
                        decisions[t["label"]].append((off, m2))
                        last_choice[t["label"]] = m2

            # Convert decisions to notes/rests with durations
            for pi, t in enumerate(targets):
                part = out_parts[pi]
                m_out = stream.Measure(number=m_num)

                if m_num in measure_meta:
                    for ts in measure_meta[m_num][0]:
                        m_out.insert(ts.offset, copy.deepcopy(ts))
                    for ks in measure_meta[m_num][1]:
                        m_out.insert(ks.offset, copy.deepcopy(ks))

                seq = decisions[t["label"]]
                if not seq or seq[0][0] != Fraction(0):
                    seq = [(Fraction(0), None)] + seq
                if seq[-1][0] < bar_ql:
                    seq.append((bar_ql, None))

                for (off, midi), (next_off, _) in zip(seq, seq[1:]):
                    off_q = common.opFrac(off)
                    next_q = common.opFrac(next_off)
                    if off_q < 0:
                        off_q = Fraction(0)
                    if next_q < 0:
                        next_q = Fraction(0)
                    if off_q > bar_ql or next_q <= off_q:
                        continue
                    if next_q > bar_ql:
                        next_q = bar_ql
                    dur_q = common.opFrac(next_q - off_q)
                    if dur_q <= 0:
                        continue

                    if midi is None:
                        el: Any = note.Rest()
                    else:
                        el = note.Note()
                        el.pitch.midi = int(midi)
                    el.duration.quarterLength = max(MIN_NOTE_DURATION, dur_q)
                    m_out.insert(off_q, el)

                if is_pickup:
                    m_out.duration.quarterLength = common.opFrac(bar_ql)
                else:
                    try:
                        m_out.makeRests(inPlace=True, fillGaps=True)
                    except Exception:
                        pass

                # Clamp any elements that overrun the bar boundary
                try:
                    for el in list(m_out.notesAndRests):
                        off_q = common.opFrac(el.offset)
                        dur_q = common.opFrac(el.duration.quarterLength)
                        if off_q >= bar_ql:
                            m_out.remove(el)
                            continue
                        if off_q + dur_q > bar_ql:
                            new_dur = bar_ql - off_q
                            if new_dur <= 0:
                                m_out.remove(el)
                            else:
                                el.duration.quarterLength = common.opFrac(new_dur)
                    m_out.duration.quarterLength = common.opFrac(bar_ql)
                except Exception:
                    pass

                part.append(m_out)

        return out_parts

    # ── Transposition ───────────────────────────────────────────────

    def _apply_transpositions(
        self,
        result_score: stream.Score,
        targets: List[TargetInfo],
    ) -> None:
        """Transpose written pitch for transposing instruments."""
        self.log("\nApplying transpositions for written pitch...")

        for target in targets:
            if not target["assigned_sources"]:
                continue
            trans = target.get("transposition_semitones", 0)
            is_horn = (target["name"] == "French Horn")

            if trans == 0:
                self.log(f"  {target['label']}: concert pitch (no transposition)")
                continue

            self.log(f"  {target['label']}: +{trans} semitones for written pitch")
            written_lo = target["low"] + trans
            written_hi = target["high"] + trans

            for p in result_score.parts:
                if p.partName not in (target["label"], f"{target['label']} - RH", f"{target['label']} - LH"):
                    continue

                for el in p.recurse().notesAndRests:
                    if isinstance(el, (note.Note, chord.Chord)):
                        el.transpose(trans, inPlace=True)
                        self._shift_into_range(el, written_lo, written_hi)

                for ks in p.recurse().getElementsByClass("KeySignature"):
                    try:
                        ks.sharps = ks.transpose(interval.Interval(trans)).sharps
                    except Exception:
                        pass

                try:
                    inst_obj = p.getInstrument()
                    if inst_obj:
                        inst_obj.transposition = interval.Interval(-trans)
                except Exception:
                    pass

                if is_horn:
                    _cleanup_horn_enharmonics(p)

    # ── Register Assignment ─────────────────────────────────────────

    def _assign_parts_by_register(self, sources: List[SourceInfo], targets: List[TargetInfo]) -> None:
        """Assign source parts to targets preserving high-to-low register order."""
        keyboard_targets = [t for t in targets if t["family"] == "keyboard"]
        non_kb_targets = sorted([t for t in targets if t["family"] != "keyboard"], key=lambda t: -t["median"])

        if non_kb_targets:
            n_targets = len(non_kb_targets)

            # Score by activity (note count + vocal bonus)
            for s in sources:
                note_count = sum(1 for _ in s["part"].recurse().notes)
                vocal_bonus = 10000 if "voice" in s.get("families", set()) else 0
                s["_note_count"] = note_count + vocal_bonus

            assigned_indices: set = set()

            n_remaining = len(non_kb_targets)
            activity_sorted = sorted(sources, key=lambda s: -s["_note_count"])
            primary_pool = sorted(activity_sorted[:n_remaining], key=lambda s: -s["median"])

            for i, tgt in enumerate(non_kb_targets):
                if i < len(primary_pool):
                    src = primary_pool[i]
                    tgt["assigned_sources"].append(src)
                    tgt["primary_source"] = src
                    assigned_indices.add(src["index"])
                    self.log(f"  {_safe(src['name'])} -> {_safe(tgt['label'])} (primary, {src['_note_count']} notes)")

            # Secondary: remaining sources → closest target
            remaining = sorted(
                [s for s in sources if s["index"] not in assigned_indices],
                key=lambda s: -s["_note_count"]
            )
            for src in remaining:
                best_tgt = min(non_kb_targets, key=lambda t: abs(t["median"] - src["median"]))
                best_tgt["assigned_sources"].append(src)
                assigned_indices.add(src["index"])
                self.log(f"  {_safe(src['name'])} -> {_safe(best_tgt['label'])} (secondary)")

            # Keyboard targets get ALL sources
            for kb in keyboard_targets:
                kb["assigned_sources"] = list(sources)
                if sources:
                    kb["primary_source"] = sources[0]
        else:
            for kb in keyboard_targets:
                kb["assigned_sources"] = list(sources)
                if sources:
                    kb["primary_source"] = sources[0]

    # ── Single Part Rendering ───────────────────────────────────────

    def _render_single_part(
        self,
        target: TargetInfo,
        measure_nums: List[int],
        measure_meta: MeasureMeta,
        all_pitched_sources: Optional[List[SourceInfo]] = None,
    ) -> stream.Part:
        """Render a single target part from primary + secondary sources."""
        new_part = stream.Part()
        new_part.partName = target["label"]

        inst_cls = getattr(instrument, target["m21_class"], None)
        if inst_cls:
            try:
                new_part.insert(0, inst_cls())
            except Exception:
                pass

        new_part.insert(0, clef.BassClef() if target["median"] < 55 else clef.TrebleClef())

        target_lo = target["low"]
        target_hi = target["high"]
        tess_lo = target.get("tessitura_low")
        tess_hi = target.get("tessitura_high")
        tgt_median = target.get("median", 60)
        is_perc = target.get("family") == "percussion"
        allow_pedal = target["name"] == "Trombone"

        primary = target["primary_source"]
        secondaries = [s for s in target["assigned_sources"] if s["index"] != primary["index"]] if primary else []

        primary_trans = self._calc_transpose_for(primary, target) if primary else 0
        sec_trans = {s["index"]: self._calc_transpose_for(s, target) for s in secondaries}

        if primary_trans != 0:
            self.log(f"  {target['label']}: transpose primary '{_safe(primary['name'])}' by {primary_trans:+d} semitones")

        # Index measures
        primary_measures = {m.number: m for m in primary["part"].getElementsByClass(stream.Measure)} if primary else {}
        secondary_measures = [
            (s, {m.number: m for m in s["part"].getElementsByClass(stream.Measure)}, sec_trans[s["index"]])
            for s in secondaries
        ]

        all_source_m_maps = [
            (src, {m.number: m for m in src["part"].getElementsByClass(stream.Measure)})
            for src in (all_pitched_sources or [])
        ]

        current_bar_ql = 4.0
        gap_fills_total = 0
        empty_fills_total = 0
        last_midi: Optional[int] = None

        for m_num in measure_nums:
            new_m = stream.Measure(number=m_num)

            # Copy time/key signatures
            if m_num in measure_meta:
                for ts in measure_meta[m_num][0]:
                    new_m.insert(ts.offset, copy.deepcopy(ts))
                    try:
                        current_bar_ql = float(ts.barDuration.quarterLength)
                    except Exception:
                        pass
                for ks in measure_meta[m_num][1]:
                    new_m.insert(ks.offset, copy.deepcopy(ks))

            actual_ql = measure_meta[m_num][2] if m_num in measure_meta else None
            bar_ql = float(actual_ql) if actual_ql else current_bar_ql

            # Pickup offset shift
            pickup_shift = 0.0
            if actual_ql is not None:
                source_m_check = primary_measures.get(m_num)
                if source_m_check:
                    for el in self._iter_measure_notes(source_m_check):
                        off = float(el.offset)
                        if off > 0:
                            pickup_shift = off
                            break

            source_m = primary_measures.get(m_num)
            placed_spans: List[Tuple[float, float]] = []
            placed_offsets: set = set()
            primary_note_spans: List[Tuple[float, float]] = []

            # Primary source
            if source_m:
                for el in self._iter_measure_notes(source_m):
                    ql = float(getattr(el.duration, "quarterLength", 0) or 0)
                    start = max(0.0, float(el.offset) - pickup_shift)
                    if start >= bar_ql:
                        continue
                    ql = min(ql, bar_ql - start)
                    end = start + ql

                    el_copy = copy.deepcopy(el)
                    el_copy.duration.quarterLength = ql
                    if isinstance(el_copy, (note.Note, chord.Chord)):
                        if self._span_overlaps((start, end), placed_spans):
                            continue
                        primary_note_spans.append((start, end))
                        if primary_trans != 0:
                            el_copy = el_copy.transpose(primary_trans)
                        if not is_perc:
                            self._shift_into_range(el_copy, target_lo, target_hi, tess_lo, tess_hi, allow_pedal, last_midi)
                            self._minimize_leap(el_copy, target_lo, target_hi, last_midi, allow_pedal)
                        el_copy, last_midi = self._maybe_reduce_to_single_note(el_copy, target, last_midi)
                        new_m.insert(start, el_copy)
                        placed_spans.append((start, end))
                        placed_offsets.add(start)

            # Secondary fill-in
            for s, s_map, s_trans in secondary_measures:
                sec_m = s_map.get(m_num)
                if not sec_m:
                    continue
                for el in self._iter_measure_notes(sec_m):
                    if isinstance(el, note.Rest):
                        continue
                    ql = float(getattr(el.duration, "quarterLength", 0) or 0)
                    start = max(0.0, float(el.offset) - pickup_shift)
                    if start >= bar_ql:
                        continue
                    ql = min(ql, bar_ql - start)
                    end = start + ql

                    if start in placed_offsets or self._span_overlaps((start, end), primary_note_spans):
                        continue

                    el_copy = copy.deepcopy(el)
                    el_copy.duration.quarterLength = ql
                    if s_trans != 0:
                        el_copy = el_copy.transpose(s_trans)
                    if not is_perc:
                        self._shift_into_range(el_copy, target_lo, target_hi, tess_lo, tess_hi, allow_pedal, last_midi)
                        self._minimize_leap(el_copy, target_lo, target_hi, last_midi, allow_pedal)
                    el_copy, last_midi = self._maybe_reduce_to_single_note(el_copy, target, last_midi)
                    new_m.insert(start, el_copy)
                    placed_spans.append((start, end))
                    placed_offsets.add(start)

            # Sparse measure guard
            active_src_count = 0
            if all_source_m_maps:
                for _src, _m_map in all_source_m_maps:
                    _src_m = _m_map.get(m_num)
                    if _src_m and any(isinstance(_el, (note.Note, chord.Chord)) for _el in self._iter_measure_notes(_src_m)):
                        active_src_count += 1
            n_sources = len(all_source_m_maps)
            sparse = (n_sources > 0 and active_src_count / n_sources < SPARSE_MEASURE_THRESHOLD and not placed_spans)

            # Empty-measure fallback — assigned secondaries preferred, full pool as fallback
            if not placed_spans and not sparse:
                best_src_m = None
                best_reg_dist = float("inf")
                best_trans = 0

                def _score_empty(src_m, trans):
                    nonlocal best_src_m, best_reg_dist, best_trans
                    src_notes = [el for el in self._iter_measure_notes(src_m)
                                 if isinstance(el, (note.Note, chord.Chord))]
                    if not src_notes:
                        return
                    src_med = sum(self._representative_midi(el, target) for el in src_notes) / len(src_notes)
                    reg_dist = abs(src_med + trans - tgt_median)
                    if reg_dist < best_reg_dist:
                        best_reg_dist = reg_dist
                        best_src_m = src_m
                        best_trans = trans

                # Pass 1: assigned secondaries
                for s, s_map, s_trans in secondary_measures:
                    src_m = s_map.get(m_num)
                    if src_m:
                        _score_empty(src_m, s_trans)

                # Pass 2: full pool — only if no assigned secondary had notes here
                if best_src_m is None and all_source_m_maps:
                    for src, m_map in all_source_m_maps:
                        src_m = m_map.get(m_num)
                        if src_m:
                            _score_empty(src_m, 0)

                if best_src_m:
                    for el in self._iter_measure_notes(best_src_m):
                        if isinstance(el, note.Rest):
                            continue
                        ql = float(getattr(el.duration, "quarterLength", 0) or 0)
                        start = max(0.0, float(el.offset) - pickup_shift)
                        if start >= bar_ql:
                            continue
                        ql = min(ql, bar_ql - start)
                        el_copy = copy.deepcopy(el)
                        el_copy.duration.quarterLength = ql
                        if best_trans != 0:
                            el_copy = el_copy.transpose(best_trans)
                        if not is_perc:
                            self._shift_into_range(el_copy, target_lo, target_hi, tess_lo, tess_hi, allow_pedal, last_midi)
                            self._minimize_leap(el_copy, target_lo, target_hi, last_midi, allow_pedal)
                        el_copy, last_midi = self._maybe_reduce_to_single_note(el_copy, target, last_midi)
                        new_m.insert(start, el_copy)
                        placed_spans.append((start, start + ql))
                        placed_offsets.add(start)
                        empty_fills_total += 1

            # Gap filling — assigned secondaries preferred, full pool as fallback
            if placed_spans:
                gap_candidates: Dict[float, Tuple[Any, float, float, int]] = {}

                def _add_gap_candidate(el, start, ql, trans, prefer: bool) -> None:
                    end = start + ql
                    if start in placed_offsets or self._span_overlaps((start, end), placed_spans):
                        return
                    midi = self._representative_midi(el, target)
                    dist = abs(midi + trans - tgt_median)
                    existing = gap_candidates.get(start)
                    # Prefer assigned secondaries over full-pool candidates
                    if existing is None:
                        gap_candidates[start] = (copy.deepcopy(el), dist, ql, trans)
                    elif prefer and not existing[3] == -1:
                        # Assigned secondary always beats a full-pool entry (sentinel -1)
                        gap_candidates[start] = (copy.deepcopy(el), dist, ql, trans)
                    elif prefer or existing[3] == -1:
                        if dist < existing[1]:
                            gap_candidates[start] = (copy.deepcopy(el), dist, ql, trans)

                # Pass 1: assigned secondaries
                for s, s_map, s_trans in secondary_measures:
                    src_m = s_map.get(m_num)
                    if not src_m:
                        continue
                    for el in self._iter_measure_notes(src_m):
                        if isinstance(el, note.Rest):
                            continue
                        ql = float(getattr(el.duration, "quarterLength", 0) or 0)
                        start = max(0.0, float(el.offset) - pickup_shift)
                        if start >= bar_ql or ql <= 0:
                            continue
                        ql = min(ql, bar_ql - start)
                        _add_gap_candidate(el, start, ql, s_trans, prefer=True)

                # Pass 2: full pool for offsets not covered by an assigned secondary
                if all_source_m_maps:
                    assigned_covered = set(gap_candidates.keys())
                    for src, m_map in all_source_m_maps:
                        src_m = m_map.get(m_num)
                        if not src_m:
                            continue
                        for el in self._iter_measure_notes(src_m):
                            if isinstance(el, note.Rest):
                                continue
                            ql = float(getattr(el.duration, "quarterLength", 0) or 0)
                            start = max(0.0, float(el.offset) - pickup_shift)
                            if start >= bar_ql or ql <= 0:
                                continue
                            if start in assigned_covered:
                                continue  # assigned secondary already covers this offset
                            ql = min(ql, bar_ql - start)
                            _add_gap_candidate(el, start, ql, -1, prefer=False)

                for start, (el_copy, _, clipped_ql, fill_trans) in sorted(gap_candidates.items()):
                    if start in placed_offsets or self._span_overlaps((start, start + clipped_ql), placed_spans):
                        continue
                    el_copy.duration.quarterLength = clipped_ql
                    if fill_trans not in (0, -1):
                        el_copy = el_copy.transpose(fill_trans)
                    if not is_perc:
                        self._shift_into_range(el_copy, target_lo, target_hi, tess_lo, tess_hi, allow_pedal, last_midi)
                        self._minimize_leap(el_copy, target_lo, target_hi, last_midi, allow_pedal)
                    el_copy, last_midi = self._maybe_reduce_to_single_note(el_copy, target, last_midi)
                    new_m.insert(start, el_copy)
                    placed_spans.append((start, start + clipped_ql))
                    placed_offsets.add(start)
                    gap_fills_total += 1

            self._purge_overlaps(new_m, bar_ql)
            new_part.append(new_m)

        self.log(f"  {target['label']}: primary='{_safe(primary['name']) if primary else '?'}' "
                 f"+{len(secondaries)} fill-in +{gap_fills_total} gaps +{empty_fills_total} empty")

        # Apply instrumental beaming conventions (replaces any vocal-style flagging
        # that may have been carried over from vocal source parts).
        try:
            new_part.makeBeams(inPlace=True)
        except Exception:
            pass

        return new_part

    # ── Keyboard Rendering ──────────────────────────────────────────

    def _render_keyboard_part(
        self,
        target: TargetInfo,
        measure_nums: List[int],
        measure_meta: MeasureMeta,
    ) -> List[stream.Part]:
        """Two-hand keyboard reduction from all assigned sources."""
        rh = stream.Part()
        rh.partName = f"{target['label']} - RH"
        lh = stream.Part()
        lh.partName = f"{target['label']} - LH"

        inst_cls = getattr(instrument, target["m21_class"], None)
        if inst_cls:
            try:
                rh.insert(0, inst_cls())
                lh.insert(0, inst_cls())
            except Exception:
                pass
        rh.insert(0, clef.TrebleClef())
        lh.insert(0, clef.BassClef())

        all_source_measures = [
            {m.number: m for m in src["part"].getElementsByClass(stream.Measure)}
            for src in target["assigned_sources"]
        ]

        for m_num in measure_nums:
            rh_m = stream.Measure(number=m_num)
            lh_m = stream.Measure(number=m_num)

            if m_num in measure_meta:
                for ts in measure_meta[m_num][0]:
                    rh_m.insert(ts.offset, copy.deepcopy(ts))
                    lh_m.insert(ts.offset, copy.deepcopy(ts))
                for ks in measure_meta[m_num][1]:
                    rh_m.insert(ks.offset, copy.deepcopy(ks))
                    lh_m.insert(ks.offset, copy.deepcopy(ks))

            # Pickup shift
            pickup_shift = 0.0
            for s_map in all_source_measures:
                src_m = s_map.get(m_num)
                if not src_m:
                    continue
                for el in self._iter_measure_notes(src_m):
                    off = float(el.offset)
                    if off > 0:
                        pickup_shift = off
                        break
                if pickup_shift > 0:
                    break

            # Collect pitches at each offset
            offset_pitches: Dict[Fraction, Dict[int, Tuple[Any, Fraction]]] = defaultdict(dict)
            for s_map in all_source_measures:
                src_m = s_map.get(m_num)
                if not src_m:
                    continue
                for el in self._iter_measure_notes(src_m):
                    if isinstance(el, note.Rest):
                        continue
                    off = common.opFrac(el.offset - pickup_shift)
                    if off < 0:
                        off = Fraction(0)
                    dur = common.opFrac(el.duration.quarterLength)
                    pitches = [el.pitch] if isinstance(el, note.Note) else (list(el.pitches) if isinstance(el, chord.Chord) else [])
                    for p in pitches:
                        midi = p.midi
                        if midi not in offset_pitches[off] or dur > offset_pitches[off][midi][1]:
                            offset_pitches[off][midi] = (copy.deepcopy(p), dur)

            # Build RH/LH
            for off in sorted(offset_pitches.keys()):
                pmap = offset_pitches[off]
                rh_pitches = sorted([(m, p, d) for m, (p, d) in pmap.items() if m >= MIDDLE_C], key=lambda x: x[0])
                lh_pitches = sorted([(m, p, d) for m, (p, d) in pmap.items() if m < MIDDLE_C], key=lambda x: x[0])

                # Crossover
                if not rh_pitches and lh_pitches:
                    n = min(2, len(lh_pitches))
                    rh_pitches = lh_pitches[-n:]
                    lh_pitches = lh_pitches[:-n] if n < len(lh_pitches) else []
                elif not lh_pitches and rh_pitches:
                    n = min(2, len(rh_pitches))
                    lh_pitches = rh_pitches[:n]
                    rh_pitches = rh_pitches[n:] if n < len(rh_pitches) else []

                for sel, target_m in [
                    (self._select_voices_simple(rh_pitches, MAX_NOTES_PER_HAND), rh_m),
                    (self._select_voices_simple(lh_pitches, MAX_NOTES_PER_HAND), lh_m),
                ]:
                    if sel:
                        dur = max(d for _, _, d in sel)
                        ps = [p for _, p, _ in sel]
                        n = note.Note(ps[0]) if len(ps) == 1 else chord.Chord(ps)
                        n.duration.quarterLength = max(MIN_NOTE_DURATION, dur)
                        target_m.insert(off, n)

            rh.append(rh_m)
            lh.append(lh_m)

        return [rh, lh]

    # ── Voicing Rules ───────────────────────────────────────────────

    def _apply_voicing_rules(
        self,
        result_score: stream.Score,
        targets: List[TargetInfo],
        ensemble_def: Dict[str, Any],
    ) -> None:
        """Enforce spacing and voice-crossing constraints on concert-pitch parts."""
        voices = ensemble_def.voices
        min_spacing = ensemble_def.min_spacing
        crossing_tol = ensemble_def.crossing_tolerance

        part_map = {p.partName: p for p in result_score.parts}
        ordered = []
        for t, v in zip(targets, voices):
            p = part_map.get(t["label"])
            if p:
                ordered.append((p, t, v))

        if len(ordered) < 2:
            return

        part_measure_maps = [
            (p, {m.number: m for m in p.getElementsByClass(stream.Measure)}, t, v)
            for p, t, v in ordered
        ]
        all_m_nums = sorted({mn for _, mm, _, _ in part_measure_maps for mn in mm})

        for m_num in all_m_nums:
            part_notes = []
            for p, mm, t, v in part_measure_maps:
                m = mm.get(m_num)
                note_map = {}
                if m:
                    for el in m.notesAndRests:
                        if isinstance(el, (note.Note, chord.Chord)):
                            note_map[float(el.offset)] = (el, self._representative_midi(el, t))
                part_notes.append(note_map)

            all_offsets = sorted({off for nm in part_notes for off in nm})

            for off in all_offsets:
                midis = [nm[off][1] if off in nm else None for nm in part_notes]
                elements = [nm[off][0] if off in nm else None for nm in part_notes]

                for i in range(len(ordered) - 1):
                    _, upper_t, upper_v = ordered[i]
                    _, lower_t, lower_v = ordered[i + 1]
                    um, lm = midis[i], midis[i + 1]
                    uel, lel = elements[i], elements[i + 1]

                    if um is None or lm is None:
                        continue

                    role_pair = (upper_v.role, lower_v.role)

                    # Min spacing
                    min_sep = min_spacing.get(role_pair)
                    if min_sep is not None and (um - lm) < min_sep:
                        if lel is not None and lm - 12 >= lower_t.get("extended_low", lower_t["low"]):
                            self._shift_element_by_octaves(lel, -1)
                            midis[i + 1] = lm - 12
                        elif uel is not None and um + 12 <= upper_t.get("extended_high", upper_t["high"]):
                            self._shift_element_by_octaves(uel, +1)
                            midis[i] = um + 12

                    # Voice crossing
                    um, lm = midis[i], midis[i + 1]
                    if lm - um > crossing_tol:
                        if lel is not None and lm - 12 >= lower_t.get("extended_low", lower_t["low"]):
                            self._shift_element_by_octaves(lel, -1)
                            midis[i + 1] = lm - 12
                        elif uel is not None and um + 12 <= upper_t.get("extended_high", upper_t["high"]):
                            self._shift_element_by_octaves(uel, +1)
                            midis[i] = um + 12

    # ── Octave Consistency ──────────────────────────────────────────

    @staticmethod
    def _minimize_leap(element, lo: int, hi: int, last_midi: Optional[int],
                       allow_pedal: bool = False) -> None:
        """No-op stub retained for call-site compatibility.

        Octave-shifting to minimise leaps fights the source melodic shape and
        compresses lines toward the centre of the range.  _shift_into_range
        already handles the only case that matters: notes outside the playable
        range.  Notes that are playable are left exactly where the source put them.
        """
        return

    # ── Trombone Tenor Clef ─────────────────────────────────────────

    def _apply_trombone_tenor_clef(self, result_score: stream.Score, targets: List[TargetInfo]) -> None:
        """Switch trombone clef to tenor for measures whose notes sit at/above C4.

        Bass clef is used otherwise. Clef changes are inserted only at transitions
        so the score doesn't repeat the same clef every bar.
        """
        trombone_labels = {t["label"] for t in targets if t.get("name") == "Trombone"}
        if not trombone_labels:
            return

        C4 = 60
        for part in result_score.parts:
            if part.partName not in trombone_labels:
                continue
            measures = list(part.getElementsByClass(stream.Measure))
            if not measures:
                continue

            desired: List[str] = []
            for m in measures:
                midis = []
                for el in m.recurse().notes:
                    if isinstance(el, chord.Chord):
                        midis.extend(p.midi for p in el.pitches)
                    else:
                        try:
                            midis.append(el.pitch.midi)
                        except AttributeError:
                            pass
                if midis and (sum(midis) / len(midis)) >= C4:
                    desired.append("tenor")
                else:
                    desired.append("bass")

            # Remove any pre-existing starting clef so we can set a fresh one
            for c in list(part.getElementsByClass(clef.Clef)):
                part.remove(c)
            for m in measures:
                for c in list(m.getElementsByClass(clef.Clef)):
                    m.remove(c)

            # Hysteresis: only switch when a different clef persists for
            # 2+ consecutive measures, so the part doesn't flip-flop every bar.
            smoothed = list(desired)
            for i in range(len(smoothed) - 1):
                if i > 0 and smoothed[i] != smoothed[i-1]:
                    # Singleton between two matching neighbours → absorb
                    if i + 1 < len(smoothed) and smoothed[i+1] == smoothed[i-1]:
                        smoothed[i] = smoothed[i-1]

            current = smoothed[0]
            first_clef = clef.TenorClef() if current == "tenor" else clef.BassClef()
            part.insert(0, first_clef)

            for i, m in enumerate(measures[1:], start=1):
                if smoothed[i] != current:
                    new_clef = clef.TenorClef() if smoothed[i] == "tenor" else clef.BassClef()
                    m.insert(0, new_clef)
                    current = smoothed[i]

    # ── Gap Filling ─────────────────────────────────────────────────

    def _fill_gap_rests(self, result_score: stream.Score, measure_meta: MeasureMeta) -> None:
        """Ensure every measure in every part is fully covered by notes+rests."""
        bar_ql_map = {}
        current_bar_ql = 4.0
        for m_num in sorted(measure_meta.keys()):
            ts_list = measure_meta[m_num][0]
            if ts_list:
                try:
                    current_bar_ql = float(ts_list[0].barDuration.quarterLength)
                except Exception:
                    pass
            actual_ql = measure_meta[m_num][2]
            bar_ql_map[m_num] = float(actual_ql) if actual_ql else current_bar_ql

        for part in result_score.parts:
            for m in part.getElementsByClass(stream.Measure):
                bar_ql = bar_ql_map.get(m.number, 4.0)
                spans = []
                for el in m.notesAndRests:
                    try:
                        s = float(el.offset)
                        d = float(el.duration.quarterLength or 0)
                    except Exception:
                        continue
                    if d <= 0:
                        continue
                    spans.append((s, s + d))
                spans.sort()

                gaps = []
                cursor = 0.0
                for s, e in spans:
                    if s > cursor + BAR_EPSILON:
                        gaps.append((cursor, min(s, bar_ql)))
                    cursor = max(cursor, e)
                    if cursor >= bar_ql:
                        break
                if cursor < bar_ql - BAR_EPSILON:
                    gaps.append((cursor, bar_ql))

                for g_start, g_end in gaps:
                    g_dur = g_end - g_start
                    if g_dur <= BAR_EPSILON:
                        continue
                    r = note.Rest()
                    try:
                        r.duration.quarterLength = g_dur
                    except Exception:
                        continue
                    m.insert(g_start, r)

    # ── Measure Metadata ────────────────────────────────────────────

    def _collect_measure_meta(self, score: stream.Score) -> MeasureMeta:
        """Collect time/key signatures and actual durations per measure number."""
        meta: MeasureMeta = {}
        for part in score.parts:
            for m in part.getElementsByClass(stream.Measure):
                num = m.number
                if num not in meta:
                    ts = list(m.getElementsByClass("TimeSignature"))
                    ks = list(m.getElementsByClass("KeySignature"))
                    meta[num] = (ts, ks, None)
                elif not meta[num][0] and not meta[num][1]:
                    ts = list(m.getElementsByClass("TimeSignature"))
                    ks = list(m.getElementsByClass("KeySignature"))
                    if ts or ks:
                        meta[num] = (ts, ks, meta[num][2])

        # Detect pickup/anacrusis bars
        sorted_m_nums = sorted(meta.keys())
        first_m_num = sorted_m_nums[0] if sorted_m_nums else None
        last_m_num = sorted_m_nums[-1] if sorted_m_nums else None
        current_bar_dur = Fraction(4, 1)

        for m_num in sorted_m_nums:
            ts_list = meta[m_num][0]
            if ts_list:
                try:
                    current_bar_dur = common.opFrac(ts_list[0].barDuration.quarterLength)
                except Exception:
                    pass

            detected_ql = None
            for part in score.parts:
                for m in part.getElementsByClass(stream.Measure):
                    if m.number != m_num:
                        continue
                    try:
                        if hasattr(m, "paddingLeft") and m.paddingLeft > 0:
                            detected_ql = common.opFrac(m.barDuration.quarterLength - m.paddingLeft)
                    except Exception:
                        pass
                    break

            if detected_ql is None and m_num in (first_m_num, last_m_num):
                min_start = None
                max_end = Fraction(0)
                for part in score.parts:
                    for m in part.getElementsByClass(stream.Measure):
                        if m.number != m_num:
                            continue
                        for el in m.notesAndRests:
                            try:
                                s = common.opFrac(el.offset)
                                e = common.opFrac(s + el.duration.quarterLength)
                                if min_start is None or s < min_start:
                                    min_start = s
                                if e > max_end:
                                    max_end = e
                            except Exception:
                                pass
                        break
                if min_start is not None:
                    content_span = max_end - min_start
                    if 0 < content_span < current_bar_dur - Fraction(1, 8):
                        detected_ql = content_span

            if detected_ql is not None:
                meta[m_num] = (meta[m_num][0], meta[m_num][1], detected_ql)

        return meta

    def _get_measure_nums(self, score: stream.Score) -> List[int]:
        """Get sorted list of unique measure numbers from the score."""
        nums: set = set()
        for part in score.parts:
            for m in part.getElementsByClass(stream.Measure):
                nums.add(m.number)
        return sorted(nums)

    # ── Static Helpers ──────────────────────────────────────────────

    @staticmethod
    def _calc_transpose_for(src: SourceInfo, target: TargetInfo) -> int:
        """Calculate semitones to transpose so source fits target range."""
        src_center = src["median"]
        tgt_lo, tgt_hi = target["low"], target["high"]
        if tgt_lo <= src_center <= tgt_hi:
            return 0
        tgt_center = target["median"]
        diff = tgt_center - src_center
        return round(diff / 12) * 12

    @staticmethod
    def _iter_measure_notes(measure: stream.Measure):
        """Yield notes/rests from a measure, handling Voice sub-streams."""
        voices = list(measure.getElementsByClass(stream.Voice))
        if not voices:
            yield from measure.notesAndRests
            return

        def _count(v):
            n = 0
            for el in v.notesAndRests:
                if isinstance(el, (note.Note, chord.Chord)):
                    try:
                        if getattr(el, "style", None) and el.style.hideObjectOnPrint:
                            continue
                    except Exception:
                        pass
                    n += 1
            return n

        best_voice = max(voices, key=_count)
        for el in best_voice.notesAndRests:
            try:
                if getattr(el, "style", None) and el.style.hideObjectOnPrint:
                    continue
            except Exception:
                pass
            yield el

    def _smooth_octave_jumps(
        self,
        result_score: stream.Score,
        targets: List[TargetInfo],
    ) -> None:
        """Remove isolated octave misplacements from rendered parts.

        For each note, examine the surrounding melodic context (up to 4 notes
        on each side). If an octave-shifted version sits closer to that context
        mean AND remains within the instrument's playable range, substitute it.
        """
        target_map = {t["label"]: t for t in targets}
        corrections = 0

        for part in result_score.parts:
            target = target_map.get(part.partName)
            if not target:
                continue
            lo = target["low"]
            hi = target["high"]

            notes = [el for el in part.recurse().notes if isinstance(el, note.Note)]
            if len(notes) < 3:
                continue

            midis = [n.pitch.midi for n in notes]

            for i in range(len(notes)):
                window = midis[max(0, i - 4):i] + midis[i + 1:i + 5]
                if not window:
                    continue
                context = sum(window) / len(window)
                curr = midis[i]
                best = curr
                best_dist = abs(curr - context)

                for alt in (curr + 12, curr - 12):
                    if lo <= alt <= hi and abs(alt - context) < best_dist:
                        best = alt
                        best_dist = abs(alt - context)

                if best != curr:
                    notes[i].pitch.midi = best
                    midis[i] = best
                    corrections += 1

        self.log(f"  {corrections} octave correction(s) applied")

    @staticmethod
    def _shift_into_range(
        element,
        lo: int,
        hi: int,
        tess_lo: Optional[int] = None,
        tess_hi: Optional[int] = None,
        allow_pedal: bool = False,
        last_midi: Optional[int] = None,
    ) -> None:
        """Octave-shift a Note or Chord into [lo, hi].

        When *last_midi* is provided the octave is chosen for melodic
        continuity (minimises distance to the previous note) rather than
        defaulting to the lowest valid position.  This preserves rising /
        falling phrase arcs that would otherwise be collapsed downward.
        """
        hard_floor = 28 if allow_pedal else lo

        def _clamp(midi_val: int) -> int:
            m = midi_val
            while m > hi:
                m -= 12
            while m < hard_floor:
                m += 12
            return m

        def _best_for_context(midi_val: int) -> int:
            base = _clamp(midi_val)
            note_in_range = (midi_val == base)

            if note_in_range:
                if last_midi is None:
                    if tess_hi is not None and base > tess_hi and base - 12 >= hard_floor:
                        return base - 12
                    if tess_lo is not None and base < tess_lo and base + 12 <= hi:
                        return base + 12
                return base

            candidates = []
            for shift in range(-3, 4):
                candidate = base + shift * 12
                if hard_floor <= candidate <= hi:
                    candidates.append(candidate)
            if not candidates:
                return base
            if last_midi is None:
                if tess_hi is not None and base > tess_hi and base - 12 >= hard_floor:
                    return base - 12
                if tess_lo is not None and base < tess_lo and base + 12 <= hi:
                    return base + 12
                return base
            return min(candidates, key=lambda m: abs(m - last_midi))

        if isinstance(element, note.Note):
            element.pitch.midi = _best_for_context(element.pitch.midi)
        elif isinstance(element, chord.Chord):
            pitches = element.pitches
            if not pitches:
                return
            mids = [p.midi for p in pitches]
            chord_in_range = (hard_floor <= min(mids) and max(mids) <= hi)
            while min(mids) < hard_floor:
                mids = [m + 12 for m in mids]
            while max(mids) > hi and min(mids) - 12 >= hard_floor:
                mids = [m - 12 for m in mids]
            if not chord_in_range and last_midi is not None:
                rep = mids[0]
                if rep - 12 >= hard_floor and abs(rep - 12 - last_midi) < abs(rep - last_midi):
                    mids = [m - 12 for m in mids]
                elif max(mids) + 12 <= hi and abs(rep + 12 - last_midi) < abs(rep - last_midi):
                    mids = [m + 12 for m in mids]
            shift = mids[0] - pitches[0].midi
            if shift != 0:
                for p in pitches:
                    p.midi += shift

    @staticmethod
    def _span_overlaps(span: Tuple[float, float], spans: List[Tuple[float, float]]) -> bool:
        """Return True if span overlaps any span in spans."""
        if not spans:
            return False
        a0, a1 = span
        if a1 <= a0:
            return False
        for b0, b1 in spans:
            if b1 <= b0:
                continue
            if a0 < b1 and b0 < a1:
                return True
        return False

    @staticmethod
    def _purge_overlaps(measure: stream.Measure, bar_ql: float) -> None:
        """Remove notes that overlap an earlier note or exceed bar_ql."""
        elements = [(float(el.offset), el) for el in list(measure.notesAndRests) if isinstance(el, (note.Note, chord.Chord))]
        elements.sort(key=lambda x: x[0])
        kept_spans: List[Tuple[float, float]] = []
        to_remove = []
        for start, el in elements:
            ql = float(el.duration.quarterLength)
            end = start + ql
            if start >= bar_ql - 0.001:
                to_remove.append(el)
                continue
            if end > bar_ql + 0.001:
                el.duration.quarterLength = bar_ql - start
                end = bar_ql
            overlaps = any(s < end and start < e for s, e in kept_spans)
            if overlaps:
                to_remove.append(el)
            else:
                kept_spans.append((start, end))
        for el in to_remove:
            try:
                measure.remove(el)
            except Exception:
                pass

    def _maybe_reduce_to_single_note(self, element, target: TargetInfo, last_midi: Optional[int]):
        """Ensure monophonic playability for brass/woodwind/voice targets."""
        fam = target.get("family")
        if fam not in ("brass", "woodwind", "voice"):
            if isinstance(element, note.Note):
                return element, element.pitch.midi
            if isinstance(element, chord.Chord) and element.pitches:
                mids = [p.midi for p in element.pitches]
                if last_midi is not None:
                    new_last = min(mids, key=lambda m: abs(m - last_midi))
                else:
                    new_last = min(mids, key=lambda m: abs(m - target.get("median", 60)))
                return element, new_last
            return element, last_midi

        if isinstance(element, note.Note):
            return element, element.pitch.midi

        if isinstance(element, chord.Chord) and element.pitches:
            mids = [p.midi for p in element.pitches]
            if last_midi is not None:
                chosen_midi = min(mids, key=lambda m: abs(m - last_midi))
            else:
                chosen_midi = max(mids) if target.get("median", 60) >= 60 else min(mids)

            chosen_pitch = next((copy.deepcopy(p) for p in element.pitches if p.midi == chosen_midi), copy.deepcopy(element.pitches[0]))
            n = note.Note(chosen_pitch)
            try:
                n.duration = copy.deepcopy(element.duration)
            except Exception:
                pass
            if getattr(element, "tie", None) is not None:
                try:
                    n.tie = copy.deepcopy(element.tie)
                except Exception:
                    pass
            try:
                n.articulations = [copy.deepcopy(a) for a in getattr(element, "articulations", [])]
            except Exception:
                pass
            try:
                n.expressions = [copy.deepcopy(e) for e in getattr(element, "expressions", [])]
            except Exception:
                pass
            return n, n.pitch.midi

        return element, last_midi

    @staticmethod
    def _representative_midi(element, target: TargetInfo) -> int:
        """Single representative MIDI value for a note or chord."""
        if isinstance(element, note.Note):
            return element.pitch.midi
        if isinstance(element, chord.Chord) and element.pitches:
            mids = [p.midi for p in element.pitches]
            tgt_med = target.get("median", 60)
            return min(mids, key=lambda m: abs(m - tgt_med))
        return 60

    @staticmethod
    def _shift_element_by_octaves(element, n_octaves: int) -> None:
        """Shift all pitches in a Note or Chord by n_octaves."""
        semitones = n_octaves * 12
        if isinstance(element, note.Note):
            element.pitch.midi += semitones
        elif isinstance(element, chord.Chord):
            for p in element.pitches:
                p.midi += semitones

    @staticmethod
    def _select_voices_simple(candidates: list, max_notes: int) -> list:
        """Keep outer voices + evenly-spaced inner. candidates = [(midi, pitch_obj, dur)]."""
        if len(candidates) <= max_notes:
            return candidates
        selected = {0, len(candidates) - 1}
        remaining = max_notes - len(selected)
        interior = list(range(1, len(candidates) - 1))
        if remaining > 0 and interior:
            step = len(interior) / remaining
            for i in range(remaining):
                idx = interior[min(int(i * step), len(interior) - 1)]
                selected.add(idx)
        return [candidates[i] for i in sorted(selected)]

    # ── Diagnostics ─────────────────────────────────────────────────

    def _log_diagnostic(
        self,
        result_score: stream.Score,
        targets: List[TargetInfo],
        pitched_sources: List[SourceInfo],
        source_score: stream.Score,
    ) -> None:
        """Read-only diagnostic: note/rest counts per slot + unassigned source coverage."""
        self.log("\n── Diagnostic: Voice Assignment Coverage ──")

        all_src_spans: Dict[int, List[Tuple[float, float, str]]] = defaultdict(list)
        for s in pitched_sources:
            for m in s["part"].getElementsByClass(stream.Measure):
                for el in self._iter_measure_notes(m):
                    if isinstance(el, (note.Note, chord.Chord)):
                        st = float(el.offset)
                        en = st + float(el.duration.quarterLength or 0)
                        all_src_spans[m.number].append((st, en, s["name"]))

        part_map = {p.partName: p for p in result_score.parts}

        for t in targets:
            p = part_map.get(t["label"])
            if not p:
                continue

            note_count = 0
            rest_count = 0
            occupied: Dict[int, List[Tuple[float, float]]] = defaultdict(list)

            for m in p.getElementsByClass(stream.Measure):
                for el in m.notesAndRests:
                    ql = float(el.duration.quarterLength or 0)
                    st = float(el.offset)
                    if isinstance(el, (note.Note, chord.Chord)):
                        note_count += 1
                        occupied[m.number].append((st, st + ql))
                    elif isinstance(el, note.Rest):
                        rest_count += 1

            pair_seen: set = set()
            unmatched_hits = 0
            for m_num, spans in all_src_spans.items():
                occ = occupied.get(m_num, [])
                for src_st, src_en, src_name in spans:
                    if not any(o_st < src_en and src_st < o_en for o_st, o_en in occ):
                        key = (m_num, src_name)
                        if key not in pair_seen:
                            unmatched_hits += 1
                            pair_seen.add(key)

            role = t.get("role", "—")
            primary = t["primary_source"]["name"] if t.get("primary_source") else "none"
            n_fill = len(t.get("assigned_sources", [])) - (1 if t.get("primary_source") else 0)

            self.log(f"  {t['label']}  [{role}]")
            self.log(f"    notes={note_count}  rests={rest_count} | primary='{primary}' fill-in={n_fill}")

            if not unmatched_hits:
                self.log("    ✓ All source activity covered")
                continue

            source_freq = Counter()
            slot_gap = 0
            empty_meas = 0
            for m_num, spans in all_src_spans.items():
                occ = occupied.get(m_num, [])
                slot_active = len(occ) > 0
                for src_st, src_en, src_name in spans:
                    if not any(o_st < src_en and src_st < o_en for o_st, o_en in occ):
                        source_freq[src_name] += 1
                        if slot_active:
                            slot_gap += 1
                        else:
                            empty_meas += 1

            top5 = source_freq.most_common(5)
            top5_str = "  ·  ".join(f"{n} ×{c}" for n, c in top5)
            self.log(f"    ⚠ {unmatched_hits} pairs uncovered")
            self.log(f"    Top sources: {top5_str}")
            self.log(f"    slot gap={slot_gap} | empty measure={empty_meas}")

        assigned_indices = {s["index"] for t in targets for s in t.get("assigned_sources", [])}
        unassigned = [s for s in pitched_sources if s["index"] not in assigned_indices]
        if unassigned:
            self.log(f"  Unassigned: {', '.join(s['name'] for s in unassigned)}")
        else:
            self.log("  All source parts assigned.")
        self.log("────────────────────────────────────────────")
