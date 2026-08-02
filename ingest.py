"""
ingest.py

PDF ingestion script — chunks a PDF and upserts embeddings into Qdrant.
Uses Gemini text-embedding-004 (via elimu_ai.gemini.embed).

Usage:
    python ingest.py Documents/biology.pdf --subject Biology --collection elimu_library
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def chunk_pdf(path: str, chunk_size: int = 500) -> list[str]:
    """Extract text from a PDF and split it into fixed-size chunks."""
    try:
        from pypdf import PdfReader
    except ImportError:
        print("Error: pypdf is not installed. Run: pip install pypdf")
        sys.exit(1)

    reader = PdfReader(path)
    text = "".join(page.extract_text() or "" for page in reader.pages)
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def ingest(
    pdf_path: str,
    subject: str = "General",
    collection: str = "elimu_library",
    chunk_size: int = 500,
) -> None:
    """Embed a PDF and upsert all chunks into Qdrant."""
    from elimu_ai.gemini import embed
    from elimu_ai.config import QDRANT_URL, QDRANT_API_KEY

    if not QDRANT_URL:
        print("Error: QDRANT_URL environment variable is not set.")
        sys.exit(1)

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct, VectorParams, Distance
    except ImportError:
        print("Error: qdrant-client is not installed. Run: pip install qdrant-client")
        sys.exit(1)

    source_name = Path(pdf_path).name
    chunks = chunk_pdf(pdf_path, chunk_size)
    print(f"Extracted {len(chunks)} chunks from '{source_name}'.")

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)

    # Ensure collection exists — vector size for text-embedding-004 is 768
    VECTOR_SIZE = 768
    try:
        client.get_collection(collection)
    except Exception:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"Created Qdrant collection '{collection}'.")

    points = []
    for i, chunk in enumerate(chunks):
        vector = embed(chunk)
        if not vector:
            print(f"  Skipped chunk {i}: embedding failed.")
            continue
        points.append(
            PointStruct(
                id=i,
                vector=vector,
                payload={
                    "text": chunk,
                    "subject": subject,
                    "source": source_name,
                },
            )
        )

    if points:
        client.upsert(collection_name=collection, points=points)
        print(f"Upserted {len(points)} points into '{collection}'.")
    else:
        print("No points to upsert.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a PDF into Qdrant.")
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("--subject",    default="General",        help="Subject label")
    parser.add_argument("--collection", default="elimu_library",  help="Qdrant collection name")
    parser.add_argument("--chunk-size", default=500, type=int,    help="Chunk size in characters")
    args = parser.parse_args()
    ingest(args.pdf, args.subject, args.collection, args.chunk_size)
