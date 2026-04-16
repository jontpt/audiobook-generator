"""Print the melodic thread voice-selection measure by measure to see where it hops."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

mxl_root = Path(__file__).parent.parent
mozart_path = mxl_root / "mozart-great-mass-grosse-messe-in-c-minor-k-427-i-kyrie.mxl"

from music21 import converter, note as m21note, chord as m21chord, stream, common
from fractions import Fraction

score = converter.parse(str(mozart_path))
score = score.toSoundingPitch()

parts = [p for p in score.parts if any(True for _ in p.recurse().notes)]
print(f"\n{len(parts)} pitched parts\n")

# Show measures 1-35: at each beat, which voice is loudest/highest?
for m_num in range(1, 36):
    entries = []
    for p in parts:
        for m in p.getElementsByClass(stream.Measure):
            if m.number != m_num:
                continue
            for el in m.notesAndRests:
                if isinstance(el, m21note.Note):
                    entries.append((float(el.offset), el.pitch.midi, p.partName or "?",
                                    float(el.duration.quarterLength)))
                elif isinstance(el, m21chord.Chord) and el.pitches:
                    top = max(el.pitches, key=lambda p: p.midi)
                    entries.append((float(el.offset), top.midi, p.partName or "?",
                                    float(el.duration.quarterLength)))
    if not entries:
        continue
    entries.sort(key=lambda x: (x[0], -x[1]))
    # Show top note at beats 0,1,2,3
    beats = {}
    for off, midi, name, dur in entries:
        beat = round(off * 2) / 2  # half-beat resolution
        if beat not in beats:
            beats[beat] = (midi, name, dur)
    beat_str = "  ".join(
        f"b{b:.1f}:{name[:8]}({midi},{dur:.1f}ql)"
        for b, (midi, name, dur) in sorted(beats.items())[:6]
    )
    print(f"m{m_num:3d}: {beat_str}")
