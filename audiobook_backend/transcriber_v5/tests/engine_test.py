"""Test engine directly on the Mozart MXL file to find the hang."""
import sys
import traceback
from pathlib import Path
from fractions import Fraction

LOG = []
def log(msg):
    LOG.append(msg)
    print(f"[{len(LOG):03d}] {msg}")

def write_log():
    with open(Path(__file__).parent.parent / "engine_test_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))

# Find the MXL file (in parent directory)
mxl_dir = Path(__file__).parent.parent.parent
mxl_files = list(mxl_dir.glob("*.mxl"))
if not mxl_files:
    print(f"No .mxl files found in {mxl_dir}")
    sys.exit(1)

mxl_path = str(mxl_files[0])
log(f"Using: {mxl_path}")

try:
    log("1/8 Importing music21...")
    from music21 import converter, stream
    log("   OK")

    log("2/8 Parsing score...")
    score = converter.parse(mxl_path)
    log(f"   OK - {len(score.parts)} parts")

    log("3/8 Importing engine...")
    from transcriber.engine import ArrangementEngine
    from transcriber.instruments import ENSEMBLE_DB, ENSEMBLE_PRESETS
    log("   OK")

    log("4/8 Creating engine...")
    engine = ArrangementEngine(log_fn=log)
    log("   OK")

    log("5/8 Starting arrange()...")
    targets = ENSEMBLE_PRESETS["Brass Quintet"]
    ensemble_def = ENSEMBLE_DB["Brass Quintet"]

    log("   Converting to concert pitch...")
    try:
        score_concert = score.toSoundingPitch()
        log("   Concert pitch OK")
    except Exception as e:
        log(f"   Concert pitch error (continuing): {e}")
        score_concert = score

    log("   Analyzing sources...")
    source_parts = list(score_concert.parts)
    log(f"   {len(source_parts)} source parts")

    # Analyze each part manually to find bottleneck
    for i, part in enumerate(source_parts[:5]):  # First 5 only
        name = part.partName or f"Part {i+1}"
        log(f"   Part {i}: '{name}'...")
        
        log(f"     getInstrument...")
        try:
            inst = part.getInstrument()
            log(f"     -> {inst}")
        except Exception as e:
            log(f"     -> Error: {e}")

        log(f"     recurse().notes count...")
        try:
            count = sum(1 for _ in part.recurse().notes)
            log(f"     -> {count} notes")
        except Exception as e:
            log(f"     -> Error: {e}")
            break

        if i >= 2:
            log(f"   (skipping remaining parts for speed)")
            break

    log("6/8 Full arrange() call (this may take a while)...")
    result = engine.arrange(score_concert, targets, ensemble_def)
    log(f"   OK - {len(result.parts)} result parts")

    log("7/8 Saving...")
    out_path = str(mxl_dir / "test_output.musicxml")
    result.write("musicxml", fp=out_path)
    log(f"   Saved to {out_path}")

    log("8/8 DONE - All steps completed successfully!")

except Exception as e:
    log(f"EXCEPTION: {e}")
    log(traceback.format_exc())

write_log()
print(f"\nLog written to engine_test_log.txt ({len(LOG)} entries)")
print("Press Enter to exit...")
