# Brass Ensemble Transcriber v6.0

A refactored, modular version of the Universal Transcriber that arranges any musical score for brass ensembles (trio, quartet, quintet, or trumpet quartet through septet).

## Key Improvements Over v5.9

| Area | v5.9 | v6.0 |
|------|------|------|
| **Structure** | Single 4,024-line file | Package with 6 focused modules |
| **Type Hints** | None | Throughout all modules |
| **Dead Code** | `_minimize_leap()` no-op, vertical reduction (always disabled) | Removed |
| **Constants** | Magic numbers scattered | Centralized in `constants.py` |
| **Tests** | None | 30+ unit tests for core logic |
| **Documentation** | Mixed quality | Consistent docstrings, architecture docs |
| **Maintainability** | Hard to isolate components | Clean separation of concerns |

## Architecture

```
transcriber_v2/
├── main.py                  # Entry point (GUI launch)
├── requirements.txt         # Dependencies
├── README.md               # This file
├── transcriber/            # Main package
│   ├── __init__.py         # Version info
│   ├── constants.py        # All magic numbers & config
│   ├── instruments.py      # Instrument DB, tessitura, ensembles, free-text parsing
│   ├── source_classifier.py # Part family classification & pitch range extraction
│   ├── engine.py           # Core arrangement logic (assignment, rendering, voicing)
│   ├── pdf_export.py       # Audiveris/MuseScore integration
│   ├── gui.py              # PyQt5 interface
│   └── utils.py            # Shared helpers (settings load/save)
└── tests/                  # Unit tests
    └── test_core.py        # Tests for constants, instruments, ensembles, parsing
```

### Module Responsibilities

#### `constants.py`
All configuration values, thresholds, and defaults:
- `MIN_NOTE_DURATION` (1/1920 QL)
- `MIDDLE_C` (60)
- `SPARSE_MEASURE_THRESHOLD` (0.30)
- `MUSESCORE_TIMEOUT` (120s)
- Java/MuseScore search paths

#### `instruments.py`
Complete instrument database and ensemble definitions:
- `INSTRUMENT_DB`: 7 brass instruments with MIDI ranges and transposition
- `TESSITURA_TIERS`: Role-aware safe/extended ranges
- `ENSEMBLE_DB`: 7 ensemble configurations with voicing rules
- `parse_free_text()`: Natural language instrument specification parser

#### `source_classifier.py`
Classifies source score parts into families:
- Class-based detection via music21 instrument hierarchy
- Keyword-based detection from part names
- Handles compound names (e.g., "bass clarinet" ≠ string bass)

#### `engine.py`
Core arrangement logic (~800 lines, down from ~2000):
- `ArrangementEngine.arrange()`: Main orchestration
- Register-aware source-to-target assignment
- Single-part rendering with primary + secondary fill-in
- Keyboard two-hand reduction
- Voicing rules (spacing, crossing prevention)
- Gap rest filling
- Transposition for written pitch

#### `pdf_export.py`
External tool integration:
- Java auto-detection (PATH, JAVA_HOME, common paths)
- MuseScore auto-detection
- `convert_to_pdf()`: MusicXML → PDF via MuseScore CLI
- `run_audiveris()`: PDF → MusicXML via Audiveris OMR

#### `gui.py`
PyQt5 interface:
- File selection with PDF setup hints
- Three target specification modes (Presets, Pick, Type It)
- Background conversion thread
- Export options (MusicXML, MIDI, PDF score, PDF parts)
- Audiveris/MuseScore setup dialog

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Launch the GUI

```bash
python main.py
```

### 3. Run Tests

```bash
cd transcriber_v2
python -m pytest tests/ -v
```

## Usage

### Input Formats
- **MusicXML**: `.xml`, `.musicxml`, `.mxl`
- **MIDI**: `.mid`, `.midi`
- **MuseScore**: `.mscz`, `.mscx`
- **PDF**: `.pdf` (requires Audiveris + Java)

### Target Specification

Three ways to specify your target ensemble:

1. **Presets**: Choose from 7 predefined ensembles
2. **Pick Instruments**: Manually select from available brass instruments
3. **Type It**: Free-text like "brass quintet" or "2 trumpets, trombone, tuba"

### Export Options
- **MusicXML**: Primary format, preserves notation
- **MIDI**: Sounding pitch (auto-converted for playback)
- **PDF Score**: Full arranged score via MuseScore
- **PDF Parts**: Individual part PDFs with proper credits

## What Changed from v5.9

### Removed
- `_minimize_leap()` — no-op stub that did nothing
- Vertical reduction path — `_should_use_vertical_reduction()` always returned `False` but ~300 lines of dead code remained
- Duplicate XML post-processing code

### Refactored
- Extracted `INSTRUMENT_DB`, `TESSITURA_TIERS`, `ENSEMBLE_DB` to `instruments.py`
- Extracted all magic numbers to `constants.py`
- Extracted Audiveris/MuseScore logic to `pdf_export.py`
- Split GUI from engine logic (`gui.py` vs `engine.py`)
- Added `NamedTuple` types for `InstrumentInfo`, `TessituraTier`, `VoiceDef`, `EnsembleDef`

### Added
- Type hints on all public functions and methods
- 30+ unit tests covering constants, instruments, ensembles, and free-text parsing
- Consistent docstrings
- Architecture documentation (this README)

## Known Limitations

1. **PyQt5**: Uses PyQt5 (LGPL license). Consider PyQt6 or PySide6 for modern deployments.
2. **No CI/CD**: Tests must be run manually. Add to CI pipeline for safety.
3. **Single-file engine**: The `engine.py` module is ~800 lines. For further scaling, consider splitting into `assignment.py`, `render.py`, `voicing.py` sub-modules.
4. **No logging framework**: Uses simple callback-based logging. Consider `logging` module for production.

## Development

### Running Tests

```bash
cd transcriber_v2
python -m pytest tests/ -v --tb=short
```

### Code Style

No linter is configured yet. Recommended:
```bash
pip install ruff
ruff check transcriber/
```

### Future Work

- [ ] Split `engine.py` into focused sub-modules
- [ ] Add integration tests with real scores
- [ ] Add type checking with `mypy`
- [ ] Add linting with `ruff`
- [ ] Add CI/CD pipeline (GitHub Actions)
- [ ] Consider PySide6 migration
- [ ] Add user documentation / tutorial

## License

Same as the original Universal Transcriber. Check with the original author for licensing terms.

## Credits

Original code: Universal Transcriber v5.9
Refactored by: Qwen Code (v6.0)

The refactoring preserves all functional behavior from v5.9 while improving code organization, maintainability, and testability.
