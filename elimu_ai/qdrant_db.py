from google import genai
from qdrant_client import QdrantClient

from elimu_ai.config import (
    GEMINI_API_KEY,
    QDRANT_URL,
    QDRANT_API_KEY,
    COLLECTION_NAME,
)

# Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# Qdrant client
qdrant = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)


def embed(text: str):
    """
    Generate Gemini embeddings.
    """

    response = client.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )

    return response.embeddings[0].values


def search(question: str, limit=5):
    """
    Search Qdrant.
    """

    vector = embed(question)

    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=limit,
    )

    return results.points
