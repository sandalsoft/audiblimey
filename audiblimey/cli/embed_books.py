"""CLI tool for generating book embeddings using OpenAI text-embedding-3-small."""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate embeddings for books in audiblimey using OpenAI"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed all books, including those that already have embeddings",
    )

    args = parser.parse_args()

    try:
        from audiblimey.engine.embeddings import run_embedding_pipeline

        stats = run_embedding_pipeline(force=args.force)

        logger.info("Summary: %d embedded, %d skipped, %d errors",
                     stats["embedded"], stats["skipped"], stats["errors"])

        if stats["errors"] > 0:
            logger.warning("Some books failed to embed. Re-run to retry.")
            sys.exit(1)

    except EnvironmentError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
