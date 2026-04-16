"""
Melodic thread extractor: pre-processing step that identifies which source voice
carries the melodic line at each moment, then synthesizes a continuous melody part
that follows that thread across voice handoffs.

The problem this solves: in dense choral/orchestral scores (e.g. Mozart's Mass in
C minor), the melodic line is not confined to a single source part. A phrase may
begin in Soprano, be answered by Tenor, completed by Alto, and doubled throughout
by the violins. A purely register-based assignment (Soprano → Trumpet 1) misses
these cross-voice melodic arcs.

The extractor scores each source voice at every note-onset against four signals:
  1. Thread momentum   — prefer the voice already holding the melody
  2. Pitch proximity   — prefer voices that continue close to the last melody note
  3. Family preference — vocal/string parts carry the tune in vocal music
  4. Register          — melody tends to sit at the top of the texture

The result is a synthetic stream.Part that a human arranger would recognize as
"the tune" — suitable for injection as the primary source for the top target
instrument before register-based assignment runs.
"""

import copy
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Tuple

from music21 import chord, clef, common, note, stream

LogFn = Callable[[str], None]
SourceInfo = Dict[str, Any]

# ── Scoring weights ──────────────────────────────────────────────────────────

_W_MOMENTUM        = 5.0   # currently holding the thread
_W_VOCAL           = 4.0   # vocal family
_W_MELODY_FAMILY   = 2.0   # string/woodwind (melody-capable but secondary to voice)
_W_PROXIMITY_2     = 3.0   # stepwise continuation (≤ 2 semitones from last note)
_W_PROXIMITY_5     = 2.0   # small leap (≤ 5 semitones)
_W_PROXIMITY_7     = 1.0   # medium leap (≤ 7 semitones)
_W_PROXIMITY_FAR   = -3.0  # very large leap (> 12 semitones) — likely a different voice
_W_REGISTER        = 1/48  # per MIDI unit above C3 (48) — very gentle top-voice bias
_W_DURATION        = 0.4   # per quarter length remaining (capped at 4 beats)
_W_NON_VOCAL_WHEN_VOCALS_ACTIVE = -6.0  # penalty when vocals are singing

# Families where the melody most commonly lives
_MELODY_FAMILIES = {"voice", "string", "woodwind"}

# Minimum number of active sources before extraction is worthwhile
_MIN_SOURCES = 3


def _safe(text: str) -> str:
    return str(text).encode("ascii", "ignore").decode("ascii")


class MelodicThreadExtractor:
    """Identifies and synthesizes the melodic thread across all source voices."""

    def __init__(self, log_fn: Optional[LogFn] = None) -> None:
        self.log: LogFn = log_fn or (lambda _: None)

    # ── Public API ───────────────────────────────────────────────────────────

    def extract(
        self,
        score: stream.Score,
        sources: List[SourceInfo],
    ) -> Optional[SourceInfo]:
        """Build a synthetic melody SourceInfo from the cross-voice melodic thread.

        Returns None if the score is simple enough that the default register-based
        assignment will already pick the right primary voice (e.g. a string quartet
        arranging to a quintet).
        """
        active = [s for s in sources if s["has_notes"] and "percussion" not in s["families"]]
        if len(active) < _MIN_SOURCES:
            self.log("  Melodic thread: skipped (fewer than 3 active sources)")
            return None

        self.log(f"  Melodic thread: analyzing {len(active)} source parts...")

        # Index each source part's measures once
        src_m_maps: List[Tuple[SourceInfo, Dict[int, stream.Measure]]] = [
            (s, {m.number: m for m in s["part"].getElementsByClass(stream.Measure)})
            for s in active
        ]

        all_m_nums = sorted({mn for _, mm in src_m_maps for mn in mm})

        melody_part = stream.Part()
        melody_part.partName = "Melodic Thread"
        melody_part.insert(0, clef.TrebleClef())

        thread_idx: Optional[int] = None   # index into `active`
        last_midi: Optional[int] = None

        for m_num in all_m_nums:
            m_out, thread_idx, last_midi = self._process_measure(
                m_num, src_m_maps, active, thread_idx, last_midi
            )
            melody_part.append(m_out)

        # Build SourceInfo
        all_midis = [n.pitch.midi for n in melody_part.recurse().notes
                     if isinstance(n, note.Note)]
        if not all_midis:
            self.log("  Melodic thread: no pitched content extracted")
            return None

        lo = min(all_midis)
        hi = max(all_midis)
        median = sum(all_midis) / len(all_midis)

        self.log(f"  Melodic thread: {len(all_midis)} notes, range [{lo}–{hi}], "
                 f"median={median:.0f}")

        return {
            "part":             melody_part,
            "name":             "Melodic Thread",
            "families":         {"voice"},
            "low":              lo,
            "high":             hi,
            "median":           median,
            "index":            -1,       # synthetic — won't clash with real part indices
            "has_notes":        True,
            "is_melody_thread": True,     # signals assignment engine to pin to top target
        }

    # ── Per-measure processing ───────────────────────────────────────────────

    def _process_measure(
        self,
        m_num: int,
        src_m_maps: List[Tuple[SourceInfo, Dict[int, stream.Measure]]],
        active: List[SourceInfo],
        thread_idx: Optional[int],
        last_midi: Optional[int],
    ) -> Tuple[stream.Measure, Optional[int], Optional[int]]:
        """Return (output Measure, updated thread_idx, updated last_midi)."""
        m_out = stream.Measure(number=m_num)

        # Detect bar length and copy time/key signatures
        bar_ql = Fraction(4, 1)
        sigs_copied = False
        for s, mm in src_m_maps:
            src_m = mm.get(m_num)
            if not src_m:
                continue
            for ts in src_m.getElementsByClass("TimeSignature"):
                try:
                    bar_ql = common.opFrac(ts.barDuration.quarterLength)
                except Exception:
                    pass
                if not sigs_copied:
                    m_out.insert(ts.offset, copy.deepcopy(ts))
            for ks in src_m.getElementsByClass("KeySignature"):
                if not sigs_copied:
                    m_out.insert(ks.offset, copy.deepcopy(ks))
            if not sigs_copied:
                sigs_copied = True

        # Collect note spans and change-points across all sources
        # spans_by_src[i] = list of (start, end, midi) for source i
        spans_by_src: List[List[Tuple[Fraction, Fraction, int]]] = []
        change_points = {Fraction(0), bar_ql}

        for s, mm in src_m_maps:
            src_m = mm.get(m_num)
            spans: List[Tuple[Fraction, Fraction, int]] = []
            if src_m:
                for el in _iter_notes(src_m):
                    if isinstance(el, note.Rest):
                        continue
                    start = common.opFrac(el.offset)
                    dur = common.opFrac(el.duration.quarterLength)
                    if dur <= 0:
                        continue
                    end = common.opFrac(start + dur)
                    if end > bar_ql:
                        end = bar_ql
                    if start >= bar_ql:
                        continue
                    change_points.add(start)
                    change_points.add(end)
                    midi = _top_midi(el)
                    if midi is not None:
                        spans.append((start, end, midi))
            spans_by_src.append(spans)

        cps = sorted(change_points)

        # Decide which source holds the melody at each onset
        # decisions = list of (offset, midi_or_None, source_idx, note_start)
        # note_start is the ORIGINAL onset of the winning note in its source — this
        # lets us distinguish a continuous held note (same source, same note_start
        # across multiple change-points) from separate articulations of the same
        # pitch (different note_starts).
        decisions: List[Tuple[Fraction, Optional[int], Optional[int], Optional[Fraction]]] = []

        for cp in cps:
            if cp >= bar_ql:
                break

            # Active note for each source at this change-point:
            # (midi, remaining_ql, note_start)
            actives: List[Optional[Tuple[int, float, Fraction]]] = []
            for spans in spans_by_src:
                best_entry: Optional[Tuple[int, float, Fraction]] = None
                for start, end, m in spans:
                    if start <= cp < end:
                        remaining = float(end - cp)
                        if best_entry is None or m > best_entry[0]:
                            best_entry = (m, remaining, start)
                actives.append(best_entry)

            if all(a is None for a in actives):
                decisions.append((cp, None, None, None))
                continue

            winner_idx, winner_midi = self._score_sources(
                actives, active, thread_idx, last_midi
            )

            winner_start: Optional[Fraction] = None
            if winner_idx is not None and actives[winner_idx] is not None:
                winner_start = actives[winner_idx][2]
                thread_idx = winner_idx
                last_midi = winner_midi

            decisions.append((cp, winner_midi, winner_idx, winner_start))

        # Merge only when consecutive decisions represent the SAME continuous note:
        # same source_idx AND same note_start (or both rests). Separate articulations
        # of the same pitch (e.g. staccato repetitions) are preserved as distinct notes.
        merged: List[Tuple[Fraction, Fraction, Optional[int]]] = []
        prev_key: Optional[Tuple[Optional[int], Optional[Fraction]]] = None
        for i, (off, midi, src_idx, note_start) in enumerate(decisions):
            next_off = decisions[i + 1][0] if i + 1 < len(decisions) else bar_ql
            end = common.opFrac(next_off)
            key = (src_idx, note_start)
            if merged and prev_key == key and midi == merged[-1][2]:
                merged[-1] = (merged[-1][0], end, midi)
            else:
                merged.append((common.opFrac(off), end, midi))
                prev_key = key

        # Convert merged spans to notes/rests
        for off, end, midi in merged:
            dur = common.opFrac(end - off)
            if dur <= 0:
                continue
            if midi is not None:
                el: Any = note.Note()
                el.pitch.midi = int(midi)
            else:
                el = note.Rest()
            el.duration.quarterLength = float(dur)
            m_out.insert(float(off), el)

        return m_out, thread_idx, last_midi

    # ── Scoring ──────────────────────────────────────────────────────────────

    @staticmethod
    def _score_sources(
        actives: List[Optional[Tuple[int, float, Fraction]]],
        sources: List[SourceInfo],
        thread_idx: Optional[int],
        last_midi: Optional[int],
    ) -> Tuple[Optional[int], Optional[int]]:
        """Score each active source and return (winner_index, winner_midi).

        Key principles:
        - When vocal parts are singing, non-vocal sources are penalised heavily
          (violin 8th-note figures should not steal the melody from the chorus)
        - Longer-duration notes are preferred over short passing tones
        - The current thread holder has momentum so the thread doesn't flip on
          every 8th note
        """
        # Determine whether any vocal source is active at this moment
        vocal_active = any(
            a is not None and "voice" in sources[i]["families"]
            for i, a in enumerate(actives)
        )

        # In orchestral passages (no vocals), fast melodic figures at the top ARE
        # the melody — reduce duration and momentum bias so 16th-note runs aren't
        # blocked by longer-note instruments holding the thread.
        w_duration = _W_DURATION if vocal_active else _W_DURATION * 0.25
        w_momentum = _W_MOMENTUM if vocal_active else _W_MOMENTUM * 0.5

        best_score = float("-inf")
        best_idx: Optional[int] = None
        best_midi: Optional[int] = None

        for i, entry in enumerate(actives):
            if entry is None:
                continue
            midi, remaining_ql, _note_start = entry
            s = sources[i]
            is_vocal = "voice" in s["families"]

            sc = 0.0

            # 1. Thread momentum — strong inertia to avoid micro-switching
            if i == thread_idx:
                sc += w_momentum

            # 2. Family preference
            if is_vocal:
                sc += _W_VOCAL
            elif s["families"] & _MELODY_FAMILIES:
                sc += _W_MELODY_FAMILY

            # 3. Heavy penalty for non-vocal source when vocals are active
            if vocal_active and not is_vocal:
                sc += _W_NON_VOCAL_WHEN_VOCALS_ACTIVE

            # 4. Pitch proximity to last melody note
            if last_midi is not None:
                dist = abs(midi - last_midi)
                if dist <= 2:
                    sc += _W_PROXIMITY_2
                elif dist <= 5:
                    sc += _W_PROXIMITY_5
                elif dist <= 7:
                    sc += _W_PROXIMITY_7
                elif dist > 12:
                    sc += _W_PROXIMITY_FAR

            # 5. Prefer longer note durations (lyrical notes beat passing tones)
            sc += min(remaining_ql, 4.0) * w_duration

            # 6. Very gentle register bias
            sc += (midi - 48) * _W_REGISTER

            if sc > best_score:
                best_score = sc
                best_idx = i
                best_midi = midi

        return best_idx, best_midi


# ── Module-level helpers ─────────────────────────────────────────────────────

def _iter_notes(measure: stream.Measure):
    """Yield notes/rests from a measure, preferring the most active Voice."""
    voices = list(measure.getElementsByClass(stream.Voice))
    if not voices:
        yield from measure.notesAndRests
        return
    best = max(
        voices,
        key=lambda v: sum(
            1 for el in v.notesAndRests if isinstance(el, (note.Note, chord.Chord))
        ),
    )
    yield from best.notesAndRests


def _top_midi(el) -> Optional[int]:
    """Return the highest MIDI pitch of a Note or Chord, or None."""
    if isinstance(el, note.Note):
        return el.pitch.midi
    if isinstance(el, chord.Chord) and el.pitches:
        return max(p.midi for p in el.pitches)
    return None
