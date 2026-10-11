"""Utilities for grounded source citation generation and timestamped URL formatting."""

from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def format_seconds_to_timestamp(seconds: Optional[float]) -> Optional[str]:
    """Convert float seconds to human-readable HH:MM:SS or MM:SS format.

    Examples:
        0.0 -> "00:00"
        65.0 -> "01:05"
        3720.0 -> "01:02:00"
    """
    if seconds is None or seconds < 0:
        return None

    total_secs = int(seconds)
    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_timestamped_youtube_url(
    youtube_url: Optional[str],
    video_id: Optional[str] = None,
    start_seconds: Optional[float] = None,
) -> Optional[str]:
    """Construct a direct timestamped YouTube URL from episode metadata.

    Preserves existing valid query parameters (e.g. v=..., feature=...) and
    appends or updates the 't' parameter without damaging the URL structure.

    Args:
        youtube_url: Base YouTube URL from podcast episode (e.g. https://www.youtube.com/watch?v=XYZ).
        video_id: Optional fallback 11-char YouTube video ID if URL is missing.
        start_seconds: Starting timestamp of the transcript passage in seconds.

    Returns:
        Direct timestamped URL (e.g. 'https://www.youtube.com/watch?v=XYZ&t=65s'),
        base episode URL if timestamp is missing, or None if no URL can be constructed.
    """
    raw_url = youtube_url.strip() if youtube_url else ""

    # Fallback to video_id if raw_url is missing
    if not raw_url and video_id and video_id.strip():
        raw_url = f"https://www.youtube.com/watch?v={video_id.strip()}"

    if not raw_url:
        return None

    # If no timestamp is available or seconds < 0, return the raw URL
    if start_seconds is None or start_seconds < 0:
        return raw_url

    timestamp_param = f"{int(start_seconds)}s"

    try:
        parsed = urlparse(raw_url)
        if not parsed.scheme or not parsed.netloc:
            # Malformed URL string: return None without fabricating
            return None

        query_params = parse_qs(parsed.query, keep_blank_values=True)
        # Update or set 't' parameter cleanly
        query_params["t"] = [timestamp_param]

        # Re-encode query string with consistent parameter ordering
        new_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        # Fallback safely to raw URL if parsing fails unexpectedly
        return raw_url
