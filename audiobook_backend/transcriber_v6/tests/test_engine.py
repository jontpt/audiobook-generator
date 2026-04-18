from music21 import meter, note, stream

from transcriber.engine import ArrangementEngine


def _make_measure(number: int, events, time_signature: str = "4/4") -> stream.Measure:
    measure = stream.Measure(number=number)
    if time_signature:
        measure.insert(0, meter.TimeSignature(time_signature))
    for offset, element in events:
        measure.insert(offset, element)
    return measure


def _make_part(name: str, measures) -> stream.Part:
    part = stream.Part()
    part.partName = name
    for measure in measures:
        part.append(measure)
    return part


def _get_measure_notes(result: stream.Score, part_name: str, measure_number: int):
    part = next(part for part in result.parts if part.partName == part_name)
    measure = next(m for m in part.getElementsByClass(stream.Measure) if m.number == measure_number)
    return list(measure.recurse().notes)


def test_iter_measure_notes_merges_all_voices_in_offset_order():
    measure = stream.Measure(number=1)
    voice_a = stream.Voice()
    voice_a.insert(0, note.Note("C4"))

    voice_b = stream.Voice()
    hidden = note.Note("F4")
    hidden.style.hideObjectOnPrint = True
    voice_b.insert(1, hidden)
    voice_b.insert(2, note.Note("E4"))

    measure.insert(0, voice_a)
    measure.insert(0, voice_b)

    events = list(ArrangementEngine._iter_measure_notes(measure))

    assert [float(el.offset) for el in events] == [0.0, 2.0]
    assert [el.pitch.nameWithOctave for el in events] == ["C4", "E4"]


def test_full_pool_empty_measure_fallback_uses_target_transposition():
    score = stream.Score()
    high_source = _make_part(
        "High Source",
        [
            _make_measure(1, [(0, note.Note("C5"))]),
            _make_measure(2, [(0, note.Rest(quarterLength=4))], time_signature=""),
        ],
    )
    low_source = _make_part(
        "Low Source",
        [
            _make_measure(1, [(0, note.Rest(quarterLength=4))]),
            _make_measure(2, [(0, note.Note("C2"))], time_signature=""),
        ],
    )
    score.append(high_source)
    score.append(low_source)

    result = ArrangementEngine().arrange(score, ["Trumpet", "Tuba"])

    tuba_notes = _get_measure_notes(result, "Tuba", 1)

    assert [n.pitch.midi for n in tuba_notes] == [36]


def test_full_pool_gap_fill_uses_target_transposition():
    score = stream.Score()
    high_source = _make_part(
        "High Source",
        [
            _make_measure(1, [(2, note.Note("C5"))]),
            _make_measure(2, [(0, note.Rest(quarterLength=4))], time_signature=""),
        ],
    )
    low_source = _make_part(
        "Low Source",
        [
            _make_measure(1, [(0, note.Note("C2"))]),
            _make_measure(2, [(0, note.Note("C2"))], time_signature=""),
        ],
    )
    score.append(high_source)
    score.append(low_source)

    result = ArrangementEngine().arrange(score, ["Trumpet", "Tuba"])

    tuba_notes = _get_measure_notes(result, "Tuba", 1)
    note_positions = {(float(n.offset), n.pitch.midi) for n in tuba_notes}

    assert (0.0, 36) in note_positions
    assert (2.0, 36) in note_positions
