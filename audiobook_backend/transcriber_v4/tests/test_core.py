"""
Tests for the Brass Ensemble Transcriber.

Run with: python -m pytest tests/ -v
"""

import pytest
from fractions import Fraction

# Test imports - these should work if the package is structured correctly
from transcriber.instruments import (
    INSTRUMENT_DB,
    ENSEMBLE_PRESETS,
    ENSEMBLE_DB,
    TESSITURA_TIERS,
    TESSITURA_DB,
    parse_free_text,
    depluralize,
    InstrumentInfo,
)
from transcriber.constants import (
    MIN_NOTE_DURATION,
    MIDDLE_C,
    MAX_NOTES_PER_HAND,
    SPARSE_MEASURE_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════════════
#  Constants Tests
# ═══════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_min_note_duration_is_fraction(self):
        assert isinstance(MIN_NOTE_DURATION, Fraction)
        assert MIN_NOTE_DURATION > 0

    def test_middle_c_is_60(self):
        assert MIDDLE_C == 60

    def test_max_notes_per_hand_positive(self):
        assert MAX_NOTES_PER_HAND > 0

    def test_sparse_threshold_between_0_and_1(self):
        assert 0 < SPARSE_MEASURE_THRESHOLD < 1


# ═══════════════════════════════════════════════════════════════════════
#  Instrument Database Tests
# ═══════════════════════════════════════════════════════════════════════

class TestInstrumentDB:
    def test_all_instruments_have_info(self):
        for name, info in INSTRUMENT_DB.items():
            assert isinstance(info, InstrumentInfo)
            assert info.display_name
            assert info.m21_class
            assert info.family == "brass"
            assert info.low_midi < info.high_midi
            assert info.transposition_semitones >= 0

    def test_trumpet_is_bb(self):
        tpt = INSTRUMENT_DB["Trumpet"]
        assert tpt.transposition_semitones == 2
        assert tpt.m21_class == "Trumpet"

    def test_french_horn_is_f(self):
        horn = INSTRUMENT_DB["French Horn"]
        assert horn.transposition_semitones == 7
        assert horn.m21_class == "Horn"

    def test_trombone_is_concert_pitch(self):
        tbn = INSTRUMENT_DB["Trombone"]
        assert tbn.transposition_semitones == 0

    def test_tuba_is_lowest(self):
        tuba = INSTRUMENT_DB["Tuba"]
        assert tuba.low_midi == 22
        assert all(tuba.low_midi <= other.low_midi for other in INSTRUMENT_DB.values())


# ═══════════════════════════════════════════════════════════════════════
#  Tessitura Tests
# ═══════════════════════════════════════════════════════════════════════

class TestTessitura:
    def test_tiers_have_safe_and_extended(self):
        for (inst, role), tier in TESSITURA_TIERS.items():
            assert tier.safe[0] < tier.safe[1]
            assert tier.extended[0] < tier.extended[1]
            # Extended should be wider than safe
            assert tier.extended[0] <= tier.safe[0]
            assert tier.extended[1] >= tier.safe[1]

    def test_trumpet_lead_tessitura(self):
        tier = TESSITURA_TIERS[("Trumpet", "lead")]
        assert tier.safe == (67, 86)
        assert tier.extended == (60, 89)

    def test_legacy_tessitura_db(self):
        for name, (lo, hi) in TESSITURA_DB.items():
            assert lo < hi
            assert 0 <= lo < hi <= 127


# ═══════════════════════════════════════════════════════════════════════
#  Ensemble Tests
# ═══════════════════════════════════════════════════════════════════════

class TestEnsembles:
    def test_presets_match_db_keys(self):
        for name, instruments in ENSEMBLE_PRESETS.items():
            assert name in ENSEMBLE_DB
            ensemble_def = ENSEMBLE_DB[name]
            assert len(ensemble_def.voices) == len(instruments)

    def test_brass_quintet_structure(self):
        quintet = ENSEMBLE_DB["Brass Quintet"]
        assert len(quintet.voices) == 5
        roles = [v.role for v in quintet.voices]
        assert roles == ["lead", "upper", "middle", "lower", "bass"]

    def test_trumpet_quartet_has_flugelhorn(self):
        quartet = ENSEMBLE_PRESETS["Trumpet Quartet"]
        assert quartet == ["Trumpet", "Trumpet", "Trumpet", "Flugelhorn"]

    def test_all_ensembles_have_voicing(self):
        for name, defn in ENSEMBLE_DB.items():
            assert defn.voicing in ("open", "close", "mixed")
            assert defn.crossing_tolerance >= 0


# ═══════════════════════════════════════════════════════════════════════
#  Free-Text Parsing Tests
# ═══════════════════════════════════════════════════════════════════════

class TestFreeTextParsing:
    def test_brass_quintet(self):
        result = parse_free_text("brass quintet")
        assert result == ["Trumpet", "Trumpet", "French Horn", "Trombone", "Tuba"]

    def test_trumpet_quartet(self):
        result = parse_free_text("trumpet quartet")
        assert result == ["Trumpet", "Trumpet", "Trumpet", "Flugelhorn"]

    def test_individual_instruments(self):
        result = parse_free_text("2 trumpets, trombone, tuba")
        assert result == ["Trumpet", "Trumpet", "Trombone", "Tuba"]

    def test_with_filler_words(self):
        result = parse_free_text("reduce to brass trio")
        assert result == ["Trumpet", "French Horn", "Trombone"]

    def test_aliases(self):
        assert parse_free_text("tpt") == ["Trumpet"]
        assert parse_free_text("horn") == ["French Horn"]
        assert parse_free_text("flugel") == ["Flugelhorn"]

    def test_plural_handling(self):
        result = parse_free_text("3 trumpets")
        assert len(result) == 3
        assert all(r == "Trumpet" for r in result)

    def test_unrecognized_returns_none(self):
        assert parse_free_text("xyzzy") is None
        assert parse_free_text("banjo") is None

    def test_empty_string(self):
        assert parse_free_text("") is None
        assert parse_free_text("   ") is None


# ═══════════════════════════════════════════════════════════════════════
#  Depluralize Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDepluralize:
    def test_regular_plural(self):
        assert depluralize("trumpets") == "trumpet"

    def test_ss_ending(self):
        assert depluralize("bass") == "bass"

    def test_sses_ending(self):
        assert depluralize("basses") == "bass"

    def test_oes_ending(self):
        assert depluralize("oboes") == "oboe"

    def test_us_ending(self):
        assert depluralize("chorus") == "chorus"


# ═══════════════════════════════════════════════════════════════════════
#  Integration / Smoke Tests
# ═══════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_all_instruments_in_tessitura_db(self):
        """Every instrument in DB should have a tessitura fallback."""
        for name in INSTRUMENT_DB:
            assert name in TESSITURA_DB, f"{name} missing from TESSITURA_DB"

    def test_all_preset_instruments_valid(self):
        """All instruments in presets should exist in INSTRUMENT_DB."""
        for preset_name, instruments in ENSEMBLE_PRESETS.items():
            for inst in instruments:
                assert inst in INSTRUMENT_DB, f"{inst} in preset '{preset_name}' not in INSTRUMENT_DB"

    def test_ensemble_voice_instruments_valid(self):
        """All instruments in ensemble voices should exist in INSTRUMENT_DB."""
        for ensemble_name, defn in ENSEMBLE_DB.items():
            for voice in defn.voices:
                assert voice.instrument in INSTRUMENT_DB, \
                    f"{voice.instrument} in ensemble '{ensemble_name}' not in INSTRUMENT_DB"
