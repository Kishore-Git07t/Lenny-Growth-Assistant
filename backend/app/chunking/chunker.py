"""Deterministic, boundary-aware transcript chunking module.

Splits podcast transcript text into coherent passages suitable for embedding,
preferring speaker-turn, paragraph, and sentence boundaries.
Preserves character offsets, word counts, and timestamp citations without modifying
original dialogue.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ChunkingConfig:
    """Configuration parameters for transcript chunking."""

    target_words: int = 300
    max_words: int = 450
    overlap_words: int = 50
    min_words: int = 80
    version: str = "v1"

    def fingerprint(self) -> str:
        """Compute a deterministic hash fingerprint representing this configuration."""
        import hashlib
        config_str = (
            f"ver={self.version}:target={self.target_words}:"
            f"max={self.max_words}:overlap={self.overlap_words}:min={self.min_words}"
        )
        return hashlib.sha256(config_str.encode("utf-8")).hexdigest()[:16]


@dataclass
class ChunkResult:
    """Structured representation of a generated transcript chunk."""

    chunk_index: int
    content: str
    word_count: int
    char_start: int
    char_end: int
    start_seconds: Optional[float]
    end_seconds: Optional[float]


@dataclass
class TextUnit:
    """Atomic text unit (sentence or short paragraph) with exact source offsets."""

    text: str
    char_start: int
    char_end: int
    word_count: int
    timestamps: List[float] = field(default_factory=list)


def parse_timestamp_to_seconds(ts_str: str) -> Optional[float]:
    """Parse HH:MM:SS or MM:SS timestamp string into total seconds.

    Examples:
        "00:00:00" -> 0.0
        "00:01:01" -> 61.0
        "01:13:28" -> 4408.0
        "05:04"    -> 304.0
    """
    cleaned = ts_str.strip("()[]: \t")
    parts = cleaned.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600.0 + int(m) * 60.0 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60.0 + float(s)
    except (ValueError, TypeError):
        return None
    return None


def extract_timestamps_from_text(text: str) -> List[float]:
    """Extract all valid timestamps in seconds found in text."""
    # Matches patterns like (00:01:01), [00:01:01], (05:04), [05:04]
    matches = re.findall(r"[\(\[](\d{1,2}:\d{2}(?::\d{2})?)[\)\]]", text)
    seconds_list: List[float] = []
    for m in matches:
        sec = parse_timestamp_to_seconds(m)
        if sec is not None:
            seconds_list.append(sec)
    return seconds_list


def segment_into_units(text: str, target_words: int) -> List[TextUnit]:
    """Split transcript text into atomic semantic units (paragraphs or sentences) with exact offsets."""
    if not text or not text.strip():
        return []

    units: List[TextUnit] = []

    # 1. Split into paragraphs while tracking character offsets
    # Matches non-empty blocks separated by one or more blank lines
    for p_match in re.finditer(r"[^\r\n]+(?:\r?\n[^\r\n]+)*", text):
        raw_p = p_match.group(0)
        p_text = raw_p.strip()
        if not p_text:
            continue

        p_offset = raw_p.find(p_text)
        p_start = p_match.start() + p_offset
        p_end = p_start + len(p_text)
        words = p_text.split()

        # If paragraph fits comfortably within target_words, keep as single unit
        if len(words) <= target_words:
            ts = extract_timestamps_from_text(p_text)
            units.append(
                TextUnit(
                    text=p_text,
                    char_start=p_start,
                    char_end=p_end,
                    word_count=len(words),
                    timestamps=ts,
                )
            )
        else:
            # Very long speaker turn/monologue: break into sentence-level units
            # Preserves sentence boundaries (. ? !)
            for s_match in re.finditer(r"[^.!?\r\n]+(?:[.!?]+(?:\s+|$)|$)", p_text):
                raw_s = s_match.group(0)
                s_text = raw_s.strip()
                if not s_text:
                    continue

                s_offset = raw_s.find(s_text)
                s_start = p_start + s_match.start() + s_offset
                s_end = s_start + len(s_text)
                s_words = s_text.split()
                s_ts = extract_timestamps_from_text(s_text)

                units.append(
                    TextUnit(
                        text=s_text,
                        char_start=s_start,
                        char_end=s_end,
                        word_count=len(s_words),
                        timestamps=s_ts,
                    )
                )

    return units


def chunk_transcript_text(
    transcript_text: str,
    config: Optional[ChunkingConfig] = None,
) -> List[ChunkResult]:
    """Deterministically partition transcript text into coherent passages with citation metadata.

    Algorithm:
    1. Breaks transcript into units preserving paragraph and speaker boundaries.
    2. Breaks over-length monologues along sentence boundaries.
    3. Assembles chunks targeting 250-400 words (configurable).
    4. Seeds subsequent chunks with ~40-60 words of trailing overlap context.
    5. Extracts earliest and latest timestamps in chunk for YouTube citation deep-linking.
    6. Retains exact original characters with verified char_start/char_end offsets.
    """
    cfg = config or ChunkingConfig()

    if not transcript_text or not transcript_text.strip():
        return []

    units = segment_into_units(transcript_text, target_words=cfg.target_words)
    if not units:
        return []

    total_words = sum(u.word_count for u in units)

    # Edge case: short transcript fits in a single chunk
    if total_words <= cfg.target_words:
        char_start = units[0].char_start
        char_end = units[-1].char_end
        raw_slice = transcript_text[char_start:char_end]
        leading_ws = len(raw_slice) - len(raw_slice.lstrip())
        trailing_ws = len(raw_slice) - len(raw_slice.rstrip())
        exact_char_start = char_start + leading_ws
        exact_char_end = char_end - trailing_ws
        content = transcript_text[exact_char_start:exact_char_end]

        all_ts: List[float] = []
        for u in units:
            all_ts.extend(u.timestamps)

        start_sec = all_ts[0] if all_ts else None
        end_sec = all_ts[-1] if len(all_ts) > 1 else start_sec

        return [
            ChunkResult(
                chunk_index=0,
                content=content,
                word_count=len(content.split()),
                char_start=exact_char_start,
                char_end=exact_char_end,
                start_seconds=start_sec,
                end_seconds=end_sec,
            )
        ]

    # Multi-chunk assembly with bounded overlap
    chunks: List[ChunkResult] = []
    chunk_index = 0
    i = 0
    last_emitted_end_unit_idx = -1

    while i < len(units):
        chunk_units: List[TextUnit] = []
        current_words = 0
        curr_idx = i

        while curr_idx < len(units):
            unit = units[curr_idx]

            # If adding unit would exceed hard max and we already have sufficient words, stop
            if chunk_units and (current_words + unit.word_count > cfg.max_words):
                break

            chunk_units.append(unit)
            current_words += unit.word_count
            curr_idx += 1

            if current_words >= cfg.target_words:
                break

        if not chunk_units:
            break

        # Check that chunk introduces new content beyond previous chunk
        emitted_end_unit_idx = curr_idx - 1
        if emitted_end_unit_idx <= last_emitted_end_unit_idx and curr_idx < len(units):
            # Advance to force inclusion of next new unit
            curr_idx = last_emitted_end_unit_idx + 2
            if curr_idx <= len(units):
                chunk_units = units[i:curr_idx]
                emitted_end_unit_idx = curr_idx - 1

        last_emitted_end_unit_idx = emitted_end_unit_idx

        # Construct chunk
        char_start = chunk_units[0].char_start
        char_end = chunk_units[-1].char_end
        raw_slice = transcript_text[char_start:char_end]
        leading_ws = len(raw_slice) - len(raw_slice.lstrip())
        trailing_ws = len(raw_slice) - len(raw_slice.rstrip())
        exact_char_start = char_start + leading_ws
        exact_char_end = char_end - trailing_ws
        content = transcript_text[exact_char_start:exact_char_end]
        word_cnt = len(content.split())

        # Collect timestamps
        all_ts = []
        for u in chunk_units:
            all_ts.extend(u.timestamps)

        start_sec = all_ts[0] if all_ts else None
        end_sec = all_ts[-1] if len(all_ts) > 1 else start_sec

        chunks.append(
            ChunkResult(
                chunk_index=chunk_index,
                content=content,
                word_count=word_cnt,
                char_start=exact_char_start,
                char_end=exact_char_end,
                start_seconds=start_sec,
                end_seconds=end_sec,
            )
        )
        chunk_index += 1

        if curr_idx >= len(units):
            break

        # Compute overlap for the next chunk:
        # Step backwards from curr_idx to gather ~overlap_words of trailing context
        overlap_accum = 0
        overlap_start = curr_idx

        for back_idx in range(curr_idx - 1, i, -1):
            overlap_accum += units[back_idx].word_count
            overlap_start = back_idx
            if overlap_accum >= cfg.overlap_words:
                break

        # Ensure forward progress: i must advance
        if overlap_start > i and overlap_start < curr_idx:
            i = overlap_start
        else:
            i = curr_idx

    return chunks
