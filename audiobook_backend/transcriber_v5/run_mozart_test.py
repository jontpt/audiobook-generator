"""Quick test: run v4 engine on the Mozart Mass."""
import sys, traceback
from datetime import datetime
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
LOG = []
def log(msg):
    LOG.append(str(msg))
    print(f"[{len(LOG):03d}] {str(msg).encode('ascii','ignore').decode('ascii')}")

mxl_root = Path(__file__).parent.parent
mozart_path = mxl_root / "mozart-great-mass-grosse-messe-in-c-minor-k-427-i-kyrie.mxl"
log(f"Score: {mozart_path.name}")
try:
    from music21 import converter
    score = converter.parse(str(mozart_path))
    log(f"Parsed: {len(score.parts)} parts")
    from transcriber.engine import ArrangementEngine
    from transcriber.instruments import ENSEMBLE_DB, ENSEMBLE_PRESETS
    score = score.toSoundingPitch()
    targets = ENSEMBLE_PRESETS["Brass Quintet"]
    ensemble_def = ENSEMBLE_DB["Brass Quintet"]
    engine = ArrangementEngine(log_fn=log)
    result = engine.arrange(score, targets, ensemble_def)
    log(f"Done: {len(result.parts)} parts")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = mxl_root / f"mozart_v4_brass_quintet_{stamp}.musicxml"
    result.write("musicxml", fp=str(out_path))
    log(f"Saved: {out_path.name}")
    log("SUCCESS")
except Exception as e:
    log(f"EXCEPTION: {e}")
    log(traceback.format_exc())
with open(Path(__file__).parent / "mozart_v4_test_log.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
