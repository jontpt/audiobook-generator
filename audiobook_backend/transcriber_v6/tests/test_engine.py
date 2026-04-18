import sys
sys.path.insert(0, '.')

from pathlib import Path
from music21 import converter

LOG = []
def log(msg):
    LOG.append(msg)
    print(f'[{len(LOG):03d}] {msg}', flush=True)

mxl_dir = Path(__file__).parent.parent.parent
mxl_files = sorted(mxl_dir.glob('*.mxl'))
print(f'Found {len(mxl_files)} .mxl files', flush=True)
mxl_path = str(mxl_files[0])
log(f'Using: {Path(mxl_path).name}')

log('1/7 Parsing score...')
score = converter.parse(mxl_path)
log(f'   OK - {len(score.parts)} parts')

log('2/7 Importing engine...')
from transcriber.engine import ArrangementEngine
from transcriber.instruments import ENSEMBLE_DB, ENSEMBLE_PRESETS
log('   OK')

log('3/7 Creating engine...')
engine = ArrangementEngine(log_fn=log)
log('   OK')

log('4/7 Converting to concert pitch...')
try:
    score_concert = score.toSoundingPitch()
    log('   OK')
except Exception as e:
    log(f'   Error: {e}')
    score_concert = score

log('5/7 Analyzing sources (first 2 parts)...')
for i, part in enumerate(score_concert.parts[:2]):
    name = part.partName or f'Part {i+1}'
    log(f'   Part {i}: {name}...')
    count = sum(1 for _ in part.recurse().notes)
    log(f'   -> {count} notes')

log('6/7 Full arrange()...')
targets = ENSEMBLE_PRESETS['Brass Quintet']
ensemble_def = ENSEMBLE_DB['Brass Quintet']
result = engine.arrange(score_concert, targets, ensemble_def)
log(f'   OK - {len(result.parts)} parts')

log('7/7 Saving...')
out_path = str(mxl_dir / 'test_output.musicxml')
result.write('musicxml', fp=out_path)
log(f'   Saved')

log('DONE!')

with open(Path(__file__).parent.parent / 'engine_test_log.txt', 'w') as f:
    f.write('\n'.join(LOG))
