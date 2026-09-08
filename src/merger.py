import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Segment:
    start: float
    end: float
    text: str
    no_speech_prob: float = 0.0


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _normalized_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _overlaps(a: Segment, b: Segment, padding: float) -> bool:
    return a.start - padding <= b.end and b.start - padding <= a.end


def _text_similarity(a: str, b: str) -> float:
    words_a = _normalized_words(a)
    words_b = _normalized_words(b)
    if not words_a or not words_b:
        return 0.0

    text_ratio = SequenceMatcher(None, " ".join(words_a), " ".join(words_b)).ratio()
    set_a = set(words_a)
    set_b = set(words_b)
    containment = len(set_a & set_b) / min(len(set_a), len(set_b))
    return max(text_ratio, containment)


def remove_echo_duplicates(
    me: list[Segment],
    others: list[Segment],
    similarity_threshold: float = 0.72,
    overlap_padding: float = 0.75,
    min_words: int = 4,
) -> list[Segment]:
    deduped: list[Segment] = []
    for mic_segment in me:
        if len(_normalized_words(mic_segment.text)) < min_words:
            deduped.append(mic_segment)
            continue

        duplicate = any(
            _overlaps(mic_segment, other_segment, overlap_padding)
            and _text_similarity(mic_segment.text, other_segment.text)
            >= similarity_threshold
            for other_segment in others
        )
        if not duplicate:
            deduped.append(mic_segment)
    return deduped


def remove_repetitions(
    segments: list[Segment],
    similarity_threshold: float = 0.85,
    min_words: int = 3,
) -> list[Segment]:
    """Collapse runs of near-identical consecutive segments into one.

    Whisper sometimes hallucinates the same phrase repeatedly on silence or
    low-level audio. Segments with fewer than ``min_words`` are left untouched.
    """
    deduped: list[Segment] = []
    for segment in segments:
        if not deduped or len(_normalized_words(segment.text)) < min_words:
            deduped.append(segment)
            continue
        if _text_similarity(deduped[-1].text, segment.text) >= similarity_threshold:
            continue
        deduped.append(segment)
    return deduped


def render_markdown(me: list[Segment], others: list[Segment], title: str) -> str:
    labeled = [("Me", seg) for seg in me] + [("Others", seg) for seg in others]
    # Stable sort by start time; "Me" first when timestamps tie.
    labeled.sort(key=lambda item: (item[1].start, 0 if item[0] == "Me" else 1))

    lines = [f"# {title}", ""]
    for speaker, seg in labeled:
        lines.append(f"**[{format_timestamp(seg.start)}] {speaker}:** {seg.text}")
    return "\n".join(lines).rstrip() + "\n"
