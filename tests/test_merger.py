from src.merger import (
    Segment,
    format_timestamp,
    remove_echo_duplicates,
    remove_repetitions,
    render_markdown,
)


def test_format_timestamp_zero():
    assert format_timestamp(0) == "00:00:00"


def test_format_timestamp_hours_minutes_seconds():
    assert format_timestamp(3661.9) == "01:01:01"


def test_render_interleaves_by_start_time():
    me = [Segment(start=10.0, end=12.0, text="let's review the roadmap")]
    others = [
        Segment(start=2.0, end=5.0, text="hello everyone"),
        Segment(start=20.0, end=23.0, text="sounds good"),
    ]
    md = render_markdown(me, others, title="Meeting 2026-07-28 14:30")

    lines = md.splitlines()
    assert lines[0] == "# Meeting 2026-07-28 14:30"
    body = [line for line in lines if line.startswith("**")]
    assert body == [
        "**[00:00:02] Others:** hello everyone",
        "**[00:00:10] Me:** let's review the roadmap",
        "**[00:00:20] Others:** sounds good",
    ]


def test_render_me_first_on_tie():
    me = [Segment(start=5.0, end=6.0, text="mine")]
    others = [Segment(start=5.0, end=6.0, text="theirs")]
    body = [
        line
        for line in render_markdown(me, others, title="t").splitlines()
        if line.startswith("**")
    ]
    assert body[0].endswith("mine")
    assert body[1].endswith("theirs")


def test_render_handles_empty_channels():
    md = render_markdown([], [], title="Empty")
    assert md == "# Empty\n"

    md = render_markdown([Segment(0.0, 1.0, "solo")], [], title="Solo")
    assert "**[00:00:00] Me:** solo" in md


def test_remove_echo_duplicates_removes_overlapping_similar_mic_segment():
    me = [Segment(10.0, 12.0, "we gaan een QR code genereren")]
    others = [Segment(9.8, 12.5, "we gaan een qr code genereren")]

    assert remove_echo_duplicates(me, others) == []


def test_remove_echo_duplicates_preserves_mic_only_segment():
    me = [Segment(20.0, 22.0, "ik ben het hier niet mee eens")]
    others = [Segment(9.8, 12.5, "ik ben het hier niet mee eens")]

    assert remove_echo_duplicates(me, others) == me


def test_remove_echo_duplicates_preserves_overlapping_different_text():
    me = [Segment(10.0, 12.0, "ik wil hier iets aan toevoegen")]
    others = [Segment(10.1, 12.5, "we gaan een qr code genereren")]

    assert remove_echo_duplicates(me, others) == me


def test_remove_echo_duplicates_preserves_short_backchannel():
    me = [Segment(10.0, 10.5, "ja")]
    others = [Segment(10.0, 10.5, "ja")]

    assert remove_echo_duplicates(me, others) == me


def test_remove_repetitions_collapses_identical_run():
    segments = [
        Segment(0.0, 2.0, "Is dat dan ook een RFC in september?"),
        Segment(2.0, 4.0, "Is dat dan ook een RFC in september?"),
        Segment(4.0, 6.0, "Is dat dan ook een RFC in september?"),
    ]
    assert remove_repetitions(segments) == [segments[0]]


def test_remove_repetitions_collapses_near_identical_run():
    segments = [
        Segment(0.0, 2.0, "we gaan een QR code genereren"),
        Segment(2.0, 4.0, "we gaan een qr code genereren"),
    ]
    assert remove_repetitions(segments) == [segments[0]]


def test_remove_repetitions_preserves_distinct_segments():
    segments = [
        Segment(0.0, 2.0, "RFC in september"),
        Segment(2.0, 4.0, "RFC in september"),
        Segment(4.0, 6.0, "een heel ander onderwerp"),
    ]
    assert remove_repetitions(segments) == [
        segments[0],
        segments[2],
    ]


def test_remove_repetitions_preserves_short_segments():
    segments = [
        Segment(0.0, 1.0, "ja"),
        Segment(1.0, 2.0, "ja"),
        Segment(2.0, 3.0, "ja"),
    ]
    assert remove_repetitions(segments) == segments
