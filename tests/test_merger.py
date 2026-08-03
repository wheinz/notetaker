from src.merger import Segment, format_timestamp, render_markdown


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
