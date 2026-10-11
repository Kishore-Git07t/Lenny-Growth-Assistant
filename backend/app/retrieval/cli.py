"""CLI entrypoint for testing semantic vector retrieval and source citations.

Usage:
    # Basic semantic search:
    python -m backend.app.retrieval.cli --query "How should founders understand their customers?"

    # Custom top-k results:
    python -m backend.app.retrieval.cli --query "What is product-market fit?" --top-k 3

    # Diagnostic verbose mode:
    python -m backend.app.retrieval.cli --query "Retention and churn tactics" --verbose
"""

import argparse
import logging
import sys

from backend.app.database import (
    DatabaseUnavailableException,
    DatabaseUnconfiguredException,
    get_db_session,
)
from backend.app.embeddings.client import EmbeddingError
from backend.app.retrieval.service import (
    DEFAULT_TOP_K,
    SemanticRetrievalService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("retrieval_cli")


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for the retrieval CLI."""
    parser = argparse.ArgumentParser(
        description="Search ingested podcast transcripts using semantic vector search and retrieve grounded citations.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        required=True,
        help="Search question or keyword phrase to query.",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Number of nearest passages to retrieve (1 to 10).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Ollama embedding model override (defaults to configured model, e.g. nomic-embed-text).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Display detailed diagnostic output including character offsets and raw scores.",
    )
    return parser


def main() -> int:
    """Run the read-only retrieval CLI workflow."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args()

    cleaned_query = args.query.strip()
    if not cleaned_query:
        print("ERROR: Search query cannot be empty or whitespace-only.")
        return 1

    print("\n" + "=" * 70)
    print(" LENNY GROWTH ASSISTANT — SEMANTIC RETRIEVAL & CITATION CLI")
    print("=" * 70)
    print(f" Query       : \"{cleaned_query}\"")
    print(f" Top-K       : {args.top_k}")
    print(f" Model       : {args.model or 'Default (nomic-embed-text)'}")
    print("=" * 70 + "\n")

    try:
        with get_db_session() as db:
            service = SemanticRetrievalService(
                db=db,
                model=args.model,
            )
            response = service.retrieve(
                query=cleaned_query,
                top_k=args.top_k,
            )
    except DatabaseUnconfiguredException:
        print("ERROR: Database is not configured. Please set DATABASE_URL in environment or .env file.")
        return 2
    except DatabaseUnavailableException as exc:
        print(f"ERROR: Database connection failed: {exc}")
        return 2
    except EmbeddingError as exc:
        print(f"ERROR: Ollama embedding generation failed: {exc}")
        print("Please ensure Ollama is running and nomic-embed-text is pulled: ollama pull nomic-embed-text")
        return 2
    except Exception as exc:
        print(f"FATAL ERROR during semantic retrieval: {exc}")
        logger.exception("Retrieval failed")
        return 2

    # Print Index Coverage
    cov = response.coverage
    print("-" * 70)
    print(" CORPUS & INDEX COVERAGE REPORT")
    print("-" * 70)
    print(f" Total Episodes in Corpus : {cov.total_episodes}")
    print(f" Indexed Episodes         : {cov.indexed_episodes}")
    print(f" Total Transcript Chunks  : {cov.total_chunks}")
    print(f" Indexed Vector Chunks    : {cov.indexed_chunks}")
    print(f" Status                   : {'PARTIAL INDEX ACTIVE' if cov.is_partial else 'COMPLETE INDEX'}")
    print(f" Details                  : {cov.description}")
    if response.disclaimer:
        print(f"\n [!] NOTICE: {response.disclaimer}")
    print("-" * 70 + "\n")

    if response.status == "no_indexed_content":
        print("ZERO EMBEDDINGS FOUND:")
        print("No transcript passages have been embedded yet with model '%s'." % cov.model_name)
        print("Run the embedding pipeline first: python -m backend.app.embeddings.cli\n")
        return 1

    if response.status == "insufficient_evidence" or not response.items:
        print("NO EVIDENCE FOUND:")
        print("No matching transcript passages were found in the currently indexed subset.")
        if cov.is_partial:
            print("Note: Only %d episodes are indexed; this topic may appear in unindexed episodes." % cov.indexed_episodes)
        print()
        return 1

    # Print Top Retrieved Passages with Verifiable Citations
    print(f"RETRIEVED {len(response.items)} GROUNDED PASSAGE(S):\n")

    for rank, item in enumerate(response.items, start=1):
        guest_display = f" (Guest: {item.guest_name})" if item.guest_name else ""
        ts_display = f" [at {item.timestamp_label}]" if item.timestamp_label else ""

        print(f"#{rank} — {item.episode_title}{guest_display}{ts_display}")
        print(f"    Similarity Score : {item.similarity_score:.4f}  (Cosine Distance: {item.cosine_distance:.4f})")
        print(f"    Episode Slug     : {item.episode_slug}")
        print(f"    Chunk ID         : {item.chunk_id} (Index: {item.chunk_index})")
        if item.timestamped_url:
            print(f"    Citation URL     : {item.timestamped_url}")
        elif item.youtube_url:
            print(f"    Citation URL     : {item.youtube_url} (Timestamp unavailable)")
        else:
            print(f"    Citation URL     : [No external YouTube link recorded]")

        if args.verbose:
            offsets = f"chars {item.char_start}..{item.char_end}" if item.char_start is not None else "offsets N/A"
            time_range = f"{item.start_seconds:.1f}s..{item.end_seconds:.1f}s" if item.start_seconds is not None else "time N/A"
            print(f"    Provenance       : {offsets}, {time_range}")

        # Display transcript excerpt indented
        print("\n    Excerpt:")
        indented_excerpt = "\n".join(f"        {line}" for line in item.content.splitlines())
        print(indented_excerpt)
        print("\n" + "-" * 70)

    print("\nRetrieval completed successfully.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
