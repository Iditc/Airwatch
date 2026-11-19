"""Export event context, retrieved evidence and missing inputs as JSON."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from scripts.build_sqlite_knowledge_base import DATA_DIR
from src.knowledge_base.rag import prepare_rag_context
from src.schemas.knowledge_retrieval import KnowledgeRetrievalRequest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="JSON file matching KnowledgeRetrievalRequest")
    parser.add_argument("--database", type=Path, default=DATA_DIR / "knowledge_base.sqlite3")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    try:
        request = KnowledgeRetrievalRequest.model_validate_json(args.request.read_bytes())
        context = prepare_rag_context(
            args.database,
            request,
            limit=args.limit,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Context preparation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(context.model_dump(mode="json"), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
