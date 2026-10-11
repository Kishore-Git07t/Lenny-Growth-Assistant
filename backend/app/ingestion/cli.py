"""CLI entrypoint for Lenny's Podcast transcript ingestion.

Usage:
    # Dry run preview (read-only):
    python -m backend.app.ingestion.cli --dry-run

    # Full execution against configured database:
    python -m backend.app.ingestion.cli

    # Custom corpus directory:
    python -m backend.app.ingestion.cli --dir .local/corpus/lennys-podcast-transcripts

    # Force re-ingest all episodes regardless of checksums:
    python -m backend.app.ingestion.cli --force
"""

import argparse
import logging
from pathlib import Path
import sys

from backend.app.config import get_project_root, get_settings
from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    get_db_session,
)
from backend.app.ingestion.service import TranscriptIngestionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingestion_cli")


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for the ingestion CLI."""
    parser = argparse.ArgumentParser(
        description="Ingest Lenny's Podcast markdown transcripts into PostgreSQL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Path to the transcript repository root or episodes/ directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview discovery and parsing outcomes without making database changes.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest and update all transcripts even if checksums match.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print details for every ingested or skipped file.",
    )
    return parser


def main() -> int:
    """Run the ingestion CLI workflow."""
    parser = build_parser()
    args = parser.parse_args()

    settings = get_settings()
    project_root = get_project_root()

    # Determine corpus directory
    if args.dir:
        source_path = Path(args.dir)
        if not source_path.is_absolute():
            source_path = (project_root / source_path).resolve()
    else:
        configured_dir = Path(settings.corpus_transcripts_dir)
        source_path = configured_dir if configured_dir.is_absolute() else (project_root / configured_dir).resolve()

    print("\n" + "=" * 65)
    print(" LENNY GROWTH ASSISTANT — TRANSCRIPT INGESTION CLI")
    print("=" * 65)
    print(f" Source Directory : {source_path}")
    print(f" Dry Run Mode     : {'ENABLED (Read-Only Preview)' if args.dry_run else 'DISABLED (Writing to DB)'}")
    print(f" Force Re-ingest  : {args.force}")
    print("=" * 65 + "\n")

    if not source_path.exists() or not source_path.is_dir():
        print(f"ERROR: Specified corpus directory does not exist: {source_path}")
        print("Please clone or extract the transcript corpus to this location before running:")
        print("  git clone https://github.com/ChatPRD/lennys-podcast-transcripts .local/corpus/lennys-podcast-transcripts\n")
        return 1

    try:
        with get_db_session() as db:
            service = TranscriptIngestionService(db=db)
            report = service.ingest_directory(
                source_dir=source_path,
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
        print(f"FATAL ERROR during database ingestion: {exc}")
        logger.exception("Ingestion failed")
        return 2

    # Validate discovery outcome
    if report.total_files_discovered == 0:
        print("\n" + "-" * 65)
        print(" INGESTION RUN SUMMARY — ZERO TRANSCRIPTS DISCOVERED")
        print("-" * 65)
        items = list(source_path.iterdir()) if source_path.is_dir() else []
        if not items:
            print(f"ERROR: Specified corpus directory is completely empty: {source_path}")
            print("Please clone or extract the transcript corpus to this location:")
            print("  git clone https://github.com/ChatPRD/lennys-podcast-transcripts .local/corpus/lennys-podcast-transcripts\n")
        elif not (source_path / "episodes").is_dir() and not any(source_path.rglob("*.md")):
            print(f"ERROR: No Markdown files found in corpus directory: {source_path}")
            print("Unsupported corpus directory layout. Expected 'episodes/{slug}/transcript.md' structure.\n")
        else:
            print(f"WARNING: No matching transcript files discovered in: {source_path}")
            print("Please verify that transcript files are named 'transcript.md' within episode subdirectories.\n")
        return 1

    # Print summary table
    mode_label = "DRY-RUN PREVIEW (READ-ONLY — NO DATABASE CHANGES)" if report.dry_run else "DATABASE COMMITTED"
    print("\n" + "-" * 65)
    print(f" INGESTION RUN SUMMARY — {mode_label}")
    print("-" * 65)
    print(f" Total files discovered : {report.total_files_discovered}")
    if report.dry_run:
        print(f" Would import (new)     : {report.imported}")
        print(f" Would update (diff)    : {report.updated}")
        print(f" Would skip (unchanged) : {report.skipped}")
    else:
        print(f" Successfully imported  : {report.imported}")
        print(f" Updated (content diff) : {report.updated}")
        print(f" Skipped (unchanged)    : {report.skipped}")
    print(f" Failed (malformed)     : {report.failed}")
    print(f" Execution time         : {report.duration_seconds:.2f}s")
    print("-" * 65)

    if args.verbose or report.failed > 0:
        print("\nIndividual file details:")
        for d in report.details:
            if args.verbose or d.status == "failed":
                err_str = f" - Error: {d.error}" if d.error else ""
                print(f"  [{d.status.upper():8}] {d.slug} ({d.file_path}){err_str}")

    if report.dry_run:
        print("\nDry-run preview completed successfully. Zero database records were modified.\n")
    else:
        print("\nIngestion process completed successfully.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
