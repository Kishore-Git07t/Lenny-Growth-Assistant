"""CLI entrypoint for Lenny's Podcast transcript chunking.

Usage:
    # Dry run preview (read-only):
    python -m backend.app.chunking.cli --dry-run

    # Full execution against configured PostgreSQL database:
    python -m backend.app.chunking.cli

    # Safe small-batch verification (first 5 episodes):
    python -m backend.app.chunking.cli --limit 5 --dry-run

    # Force re-chunk all episodes:
    python -m backend.app.chunking.cli --force

    # Process specific episode by slug:
    python -m backend.app.chunking.cli --slug brian-chesky
"""

import argparse
import logging
import sys

from backend.app.chunking.chunker import ChunkingConfig
from backend.app.chunking.service import TranscriptChunkingService
from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    get_db_session,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chunking_cli")


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for the chunking CLI."""
    parser = argparse.ArgumentParser(
        description="Chunk ingested Lenny's Podcast transcripts in PostgreSQL into retrieval passages.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview chunking results without inserting, updating, or deleting database records.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of episodes to process (useful for quick verification).",
    )
    parser.add_argument(
        "--slug",
        type=str,
        default=None,
        help="Target a specific episode slug for chunking.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-chunking even if checksums match existing chunks.",
    )
    parser.add_argument(
        "--target-words",
        type=int,
        default=300,
        help="Target words per chunk.",
    )
    parser.add_argument(
        "--overlap-words",
        type=int,
        default=50,
        help="Target words of overlap between consecutive chunks.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print details for every processed episode.",
    )
    return parser


def main() -> int:
    """Run the chunking CLI workflow."""
    parser = build_parser()
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print(" LENNY GROWTH ASSISTANT — TRANSCRIPT CHUNKING CLI")
    print("=" * 65)
    print(f" Dry Run Mode   : {'ENABLED (Read-Only Preview)' if args.dry_run else 'DISABLED (Writing to DB)'}")
    print(f" Episode Limit  : {args.limit if args.limit is not None else 'ALL'}")
    print(f" Target Slug    : {args.slug or 'ALL'}")
    print(f" Force Re-chunk : {args.force}")
    print(f" Target Words   : {args.target_words} (overlap: {args.overlap_words})")
    print("=" * 65 + "\n")

    cfg = ChunkingConfig(
        target_words=args.target_words,
        overlap_words=args.overlap_words,
    )

    try:
        with get_db_session() as db:
            service = TranscriptChunkingService(db=db, config=cfg)
            report = service.chunk_all_episodes(
                limit=args.limit,
                slug=args.slug,
                dry_run=args.dry_run,
                force=args.force,
            )
    except DatabaseUnconfiguredException:
        print("ERROR: Database is not configured. Please set DATABASE_URL in environment or .env file.")
        return 2
    except DatabaseUnavailableException as exc:
        print(f"ERROR: Database connection failed: {exc}")
        return 2
    except Exception as exc:
        print(f"FATAL ERROR during transcript chunking: {exc}")
        logger.exception("Chunking failed")
        return 2

    if report.total_episodes_inspected == 0:
        print("\n" + "-" * 65)
        print(" CHUNKING RUN SUMMARY — ZERO EPISODES FOUND")
        print("-" * 65)
        print("No matching podcast episodes found in the database.")
        print("Please ensure episodes have been ingested first using:")
        print("  python -m backend.app.ingestion.cli\n")
        return 1

    # Print summary table
    mode_label = "DRY-RUN PREVIEW (READ-ONLY — NO DATABASE CHANGES)" if report.dry_run else "DATABASE COMMITTED"
    print("\n" + "-" * 65)
    print(f" CHUNKING RUN SUMMARY — {mode_label}")
    print("-" * 65)
    print(f" Total episodes inspected : {report.total_episodes_inspected}")
    if report.dry_run:
        print(f" Would process (new)      : {report.episodes_processed}")
        print(f" Would update (rebuild)   : {report.episodes_updated}")
        print(f" Would skip (current)     : {report.episodes_skipped}")
    else:
        print(f" Episodes processed (new) : {report.episodes_processed}")
        print(f" Episodes updated (rebuilt): {report.episodes_updated}")
        print(f" Episodes skipped (current): {report.episodes_skipped}")
    print(f" Total chunks generated   : {report.total_chunks_created}")
    print(f" Failed episodes          : {report.failed_episodes}")
    print(f" Execution time           : {report.duration_seconds:.2f}s")
    print("-" * 65)

    if args.verbose or report.failed_episodes > 0:
        print("\nIndividual episode details:")
        for d in report.details:
            if args.verbose or d.status == "failed":
                err_str = f" - Error: {d.error}" if d.error else ""
                print(f"  [{d.status.upper():9}] {d.slug} ({d.chunks_count} chunks){err_str}")

    if report.dry_run:
        print("\nDry-run preview completed successfully. Zero database records were modified.\n")
    else:
        print("\nChunking process completed successfully.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
