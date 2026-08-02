import json

from sentence_transformers import SentenceTransformer

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

QDRANT_URL="https://bec088f0-2eaf-4bbb-ad5b-a93b27aaec5b.us-east-2-0.aws.cloud.qdrant.io"
QDRANT_API_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6ZWJhNTUyY2YtNTgzYy00N2I1LTg4MGMtMDQwNGNkM2RjYzgyIn0.NJj_3YWuCR06jROVzG6K8nrjnaL1K2E2dn1bIEtSqJc"

COLLECTION="elimu_library"

model=SentenceTransformer("BAAI/bge-small-en-v1.5")

qdrant=QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

with open("elimu_catalogue.json","r",encoding="utf8") as f:
    docs=json.load(f)

print("Documents:",len(docs))

BATCH_SIZE=100

batch=[]

for idx,item in enumerate(docs):

    embedding=model.encode(
        item["_chroma_text"],
        normalize_embeddings=True
    ).tolist()

    batch.append(

        PointStruct(
            id=idx,
            vector=embedding,
            payload=item
        )

    )

    if len(batch)==BATCH_SIZE:

        qdrant.upsert(
            collection_name=COLLECTION,
            wait=True,
            points=batch
        )

        print(f"Uploaded {idx+1}/{len(docs)}")

        batch=[]

if batch:

    qdrant.upsert(
        collection_name=COLLECTION,
        wait=True,
        points=batch
    )

print("Finished!")
