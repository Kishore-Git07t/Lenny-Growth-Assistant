"""CLI entrypoint for Lenny's Podcast transcript chunk vector embedding.

Usage:
    # Dry run preview (read-only):
    python -m backend.app.embeddings.cli --dry-run

    # Safe limited test (generate 4 embeddings):
    python -m backend.app.embeddings.cli --limit 4

    # Full production execution against configured PostgreSQL database:
    python -m backend.app.embeddings.cli

    # Target specific episode by slug:
    python -m backend.app.embeddings.cli --episode-slug brian-chesky

    # Force re-embed all chunks:
    python -m backend.app.embeddings.cli --force
"""

import argparse
import logging
import sys

from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    get_db_session,
)
from backend.app.embeddings.client import OllamaEmbeddingClient
from backend.app.embeddings.service import (
    DEFAULT_BATCH_SIZE,
    TranscriptEmbeddingService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("embedding_cli")


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for the embedding CLI."""
    parser = argparse.ArgumentParser(
        description="Generate and store 768-D vector embeddings for podcast transcript chunks using Ollama.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview pending embedding work without calling Ollama or writing to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of chunks to process (recommended for quick verification, e.g. --limit 4).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of chunks to embed and commit per batch (safe default: 4).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="nomic-embed-text",
        help="Ollama embedding model identifier.",
    )
    parser.add_argument(
        "--episode-slug",
        type=str,
        default=None,
        help="Filter chunks by parent episode slug.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-generation of embeddings even if checksum and model match existing records.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=10,
        help="Maximum chunk failures before halting the run.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output.",
    )
    return parser


def main() -> int:
    """Run the embedding CLI workflow."""
    parser = build_parser()
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print(" LENNY GROWTH ASSISTANT — VECTOR EMBEDDING PIPELINE CLI")
    print("=" * 65)
    print(f" Dry Run Mode   : {'ENABLED (Read-Only Preview)' if args.dry_run else 'DISABLED (Generating Embeddings)'}")
    print(f" Chunk Limit    : {args.limit if args.limit is not None else 'ALL'}")
    print(f" Batch Size     : {args.batch_size}")
    print(f" Embedding Model: {args.model}")
    print(f" Episode Filter : {args.episode_slug or 'ALL EPISODES'}")
    print(f" Force Re-embed : {args.force}")
    print(f" Max Errors     : {args.max_errors}")
    print("=" * 65 + "\n")

    try:
        with get_db_session() as db:
            client = OllamaEmbeddingClient(
                model=args.model,
            )
            service = TranscriptEmbeddingService(
                db=db,
                client=client,
                batch_size=args.batch_size,
            )
            report = service.embed_chunks(
                limit=args.limit,
                episode_slug=args.episode_slug,
                dry_run=args.dry_run,
                force=args.force,
                max_errors=args.max_errors,
            )
    except DatabaseUnconfiguredException:
        print("ERROR: Database is not configured. Please set DATABASE_URL in environment or .env file.")
        return 2
    except DatabaseUnavailableException as exc:
        print(f"ERROR: Database connection failed: {exc}")
        return 2
    except Exception as exc:
        print(f"FATAL ERROR during embedding pipeline execution: {exc}")
        logger.exception("Embedding pipeline failed")
        return 2

    if report.total_chunks_inspected == 0:
        print("\n" + "-" * 65)
        print(" EMBEDDING RUN SUMMARY — ZERO CHUNKS FOUND")
        print("-" * 65)
        print("No matching transcript chunks found in the database.")
        print("Please ensure transcripts have been chunked first using:")
        print("  python -m backend.app.chunking.cli\n")
        return 1

    mode_label = "DRY-RUN PREVIEW (READ-ONLY — ZERO NETWORK/DB CALLS)" if report.dry_run else "DATABASE COMMITTED"
    print("\n" + "-" * 65)
    print(f" EMBEDDING RUN SUMMARY — {mode_label}")
    print("-" * 65)
    print(f" Model name               : {report.model_name}")
    print(f" Batch size               : {report.batch_size}")
    print(f" Total chunks inspected   : {report.total_chunks_inspected}")
    if report.dry_run:
        print(f" Would embed (new)        : {report.chunks_embedded}")
        print(f" Would update (re-embed)  : {report.chunks_updated}")
        print(f" Would skip (current)     : {report.chunks_skipped}")
    else:
        print(f" Chunks embedded (new)    : {report.chunks_embedded}")
        print(f" Chunks updated (re-embed): {report.chunks_updated}")
        print(f" Chunks skipped (current) : {report.chunks_skipped}")
    print(f" Failed chunks            : {report.chunks_failed}")
    print(f" Execution time           : {report.duration_seconds:.2f}s")
    if report.error_summary:
        print(f" Stop reason              : {report.error_summary}")
    print("-" * 65)

    if report.dry_run:
        print("\nDry-run preview completed successfully. Zero embeddings were generated or written.\n")
    elif report.chunks_failed > 0:
        print(f"\nEmbedding run completed with {report.chunks_failed} errors.\n")
        return 2
    else:
        print("\nEmbedding pipeline completed successfully.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
