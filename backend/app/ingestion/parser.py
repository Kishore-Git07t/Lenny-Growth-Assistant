"""Markdown transcript and YAML frontmatter parser for Lenny's Podcast episodes.

Official Data Source:
    https://github.com/ChatPRD/lennys-podcast-transcripts
    Maintained by ChatPRD. All original transcript and podcast content is
    copyrighted by Lenny Rachitsky and respective interviewees.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, Optional
import urllib.parse

import yaml

from backend.app.utils.serialization import make_json_serializable


class TranscriptIngestionError(Exception):
    """Base exception for transcript parsing and ingestion failures."""
    pass


class TranscriptParseError(TranscriptIngestionError):
    """Raised when transcript content or YAML frontmatter is malformed."""
    pass


class EmptyTranscriptError(TranscriptIngestionError):
    """Raised when a transcript file is empty or lacks substantive content."""
    pass


@dataclass
class ParsedTranscript:
    """Structured representation of a parsed podcast episode transcript."""

    slug: str
    guest_name: Optional[str]
    title: str
    publish_date: Optional[date]
    youtube_url: Optional[str]
    video_id: Optional[str]
    description: Optional[str]
    transcript_text: str
    content_checksum: str
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    source_path: Optional[str] = None


def parse_date(value: Any) -> Optional[date]:
    """Safely convert date/datetime or string to datetime.date object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        val_clean = value.strip()
        if not val_clean:
            return None
        # ISO formats e.g. YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
        try:
            return date.fromisoformat(val_clean[:10])
        except ValueError:
            pass
        # Common date format e.g. YYYY/MM/DD
        match = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", val_clean)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
    return None


def extract_video_id(url_or_id: Optional[str]) -> Optional[str]:
    """Extract YouTube 11-character video ID from a URL or raw ID."""
    if not url_or_id:
        return None
    cleaned = str(url_or_id).strip()
    if not cleaned:
        return None

    # If it's already an 11-char alphanumeric ID
    if re.fullmatch(r"^[a-zA-Z0-9_-]{11}$", cleaned):
        return cleaned

    # Try parsing URL
    try:
        parsed = urllib.parse.urlparse(cleaned)
        if "youtube.com" in parsed.netloc:
            queries = urllib.parse.parse_qs(parsed.query)
            if "v" in queries and queries["v"]:
                return queries["v"][0]
        elif "youtu.be" in parsed.netloc:
            path_part = parsed.path.strip("/")
            if len(path_part) == 11:
                return path_part
    except Exception:
        pass
    return None


def compute_content_checksum(raw_bytes: bytes) -> str:
    """Compute SHA-256 hex digest for byte content."""
    return hashlib.sha256(raw_bytes).hexdigest()


def parse_transcript_content(
    content: str,
    fallback_slug: str,
    checksum: str,
    source_path: Optional[str] = None,
) -> ParsedTranscript:
    """Safely extract YAML frontmatter and transcript markdown body.

    Handles:
    - Missing frontmatter (entire content treated as transcript)
    - Separator dashes inside markdown body
    - Missing optional fields with safe fallbacks
    - Malformed YAML frontmatter
    - Empty files
    """
    if not content or not content.strip():
        raise EmptyTranscriptError("Transcript content is empty.")

    content = content.lstrip("\ufeff")
    lines = content.splitlines(keepends=True)
    first_non_empty_idx = next((i for i, line in enumerate(lines) if line.strip()), -1)

    if first_non_empty_idx == -1:
        raise EmptyTranscriptError("Transcript content consists only of whitespace.")

    frontmatter_raw = ""
    body_raw = content

    # Check if file begins with YAML frontmatter opening delimiter at column 0 (no leading whitespace)
    if lines[first_non_empty_idx].rstrip() == "---":
        closing_idx = -1
        for i in range(first_non_empty_idx + 1, len(lines)):
            # Boundary delimiters must appear at column 0 (never indented inside multiline scalars)
            if lines[i].rstrip() in ("---", "..."):
                closing_idx = i
                break

        if closing_idx == -1:
            raise TranscriptParseError(
                "Unterminated YAML frontmatter: missing closing '---' delimiter."
            )

        frontmatter_raw = "".join(lines[first_non_empty_idx + 1:closing_idx])
        body_raw = "".join(lines[closing_idx + 1:])

    # Parse YAML frontmatter safely
    metadata: Dict[str, Any] = {}
    if frontmatter_raw.strip():
        try:
            parsed_yaml = yaml.safe_load(frontmatter_raw)
            if isinstance(parsed_yaml, dict):
                metadata = parsed_yaml
            elif parsed_yaml is not None:
                metadata = {"_unstructured": parsed_yaml}
        except yaml.YAMLError as exc:
            raise TranscriptParseError(f"Malformed YAML frontmatter: {exc}") from exc

    transcript_text = body_raw.strip()
    if not transcript_text:
        raise EmptyTranscriptError(
            "Transcript file contains frontmatter but empty or missing transcript text."
        )

    # Resolve core episode fields with robust fallbacks
    slug = str(metadata.get("slug") or fallback_slug).strip().lower()
    guest_name = metadata.get("guest") or metadata.get("guest_name") or metadata.get("name")
    if guest_name:
        guest_name = str(guest_name).strip()

    title = metadata.get("title")
    if title:
        title = str(title).strip()
    elif guest_name:
        title = f"Episode with {guest_name}"
    else:
        title = fallback_slug.replace("-", " ").title()

    publish_date = parse_date(
        metadata.get("publish_date") or metadata.get("date") or metadata.get("published_at")
    )

    youtube_url = metadata.get("youtube_url") or metadata.get("url") or metadata.get("video_url")
    if youtube_url:
        youtube_url = str(youtube_url).strip()

    video_id = metadata.get("video_id") or extract_video_id(youtube_url)
    if video_id:
        video_id = str(video_id).strip()

    description = metadata.get("description")
    if description:
        description = str(description).strip()

    # Ensure all values stored in raw_metadata are strictly JSON-serializable
    json_safe_metadata = make_json_serializable(metadata)

    return ParsedTranscript(
        slug=slug,
        guest_name=guest_name,
        title=title,
        publish_date=publish_date,
        youtube_url=youtube_url,
        video_id=video_id,
        description=description,
        transcript_text=transcript_text,
        content_checksum=checksum,
        raw_metadata=json_safe_metadata,
        source_path=source_path,
    )


def parse_transcript_file(
    file_path: Path,
    relative_to: Optional[Path] = None,
) -> ParsedTranscript:
    """Read a transcript file from disk and parse into a ParsedTranscript.

    The episode slug is inferred from the parent directory name (e.g. episodes/{slug}/transcript.md),
    which is canonical for the ChatPRD dataset.
    """
    if not file_path.exists() or not file_path.is_file():
        raise TranscriptParseError(f"Transcript file not found: {file_path}")

    raw_bytes = file_path.read_bytes()
    checksum = compute_content_checksum(raw_bytes)

    # Determine slug: directory name of the file (e.g. 'elena-verna')
    # If the file is not named 'transcript.md', fallback to file stem
    if file_path.name.lower() == "transcript.md":
        fallback_slug = file_path.parent.name
    else:
        fallback_slug = file_path.stem

    source_path = (
        file_path.relative_to(relative_to).as_posix()
        if relative_to
        else file_path.as_posix()
    )

    # Decode UTF-8 with replace fallback for unexpected binary bytes
    content = raw_bytes.decode("utf-8", errors="replace")

    return parse_transcript_content(
        content=content,
        fallback_slug=fallback_slug,
        checksum=checksum,
        source_path=source_path,
    )
