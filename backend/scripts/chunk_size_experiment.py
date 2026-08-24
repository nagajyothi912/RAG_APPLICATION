"""Compare retrieval for the notebook's three chunk sizes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.rag_service import VectorStore, build_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk-size retrieval experiment from untitled13.py")
    parser.add_argument("docs_dir", nargs="?", default=str(ROOT / "data" / "docs"))
    args = parser.parse_args()

    test_questions = [
        "What are the benefits of AirFiber_1199_1M plan",
        "What is the capital of mongolia ?",
    ]

    for size in [150, 500, 1200]:
        print("\n" + "=" * 60)
        print(f"CHUNK_SIZE = {size}")
        print("=" * 60)
        exp_chunks = build_chunks(args.docs_dir, chunk_size=size, overlap=int(size * 0.1))
        exp_store = VectorStore()
        exp_store.index(exp_chunks)
        print(f"Indexed {len(exp_chunks)} chunks")
        for question in test_questions:
            results = exp_store.search(question, top_k=1)
            if results:
                chunk, score = results[0]
                print(f"  [{score:.2f}] {question}  ->  {chunk.source} (chunk #{chunk.chunk_id})")
            else:
                print(f"  [none] {question}")


if __name__ == "__main__":
    main()
