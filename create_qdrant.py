from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

QDRANT_URL = "https://bec088f0-2eaf-4bbb-ad5b-a93b27aaec5b.us-east-2-0.aws.cloud.qdrant.io"
QDRANT_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6ZWJhNTUyY2YtNTgzYy00N2I1LTg4MGMtMDQwNGNkM2RjYzgyIn0.NJj_3YWuCR06jROVzG6K8nrjnaL1K2E2dn1bIEtSqJc"

qdrant = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

COLLECTION = "elimu_library"

if qdrant.collection_exists(COLLECTION):
    qdrant.delete_collection(COLLECTION)

qdrant.create_collection(
    collection_name=COLLECTION,
    vectors_config=VectorParams(
        size=384,
        distance=Distance.COSINE,
    ),
)

print("Collection created successfully!")
