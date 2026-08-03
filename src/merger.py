from dataclasses import dataclass


@dataclass
class Segment:
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_markdown(me: list[Segment], others: list[Segment], title: str) -> str:
    labeled = [("Me", seg) for seg in me] + [("Others", seg) for seg in others]
    # Stable sort by start time; "Me" first when timestamps tie.
    labeled.sort(key=lambda item: (item[1].start, 0 if item[0] == "Me" else 1))

    lines = [f"# {title}", ""]
    for speaker, seg in labeled:
        lines.append(f"**[{format_timestamp(seg.start)}] {speaker}:** {seg.text}")
    return "\n".join(lines).rstrip() + "\n"
