from pypdf import PdfReader
from ollama import embeddings
import chromadb

reader = PdfReader("Documents/biology.pdf")

text = ""

for page in reader.pages:
    text += page.extract_text() or ""

chunk_size = 500

chunks = [
    text[i:i + chunk_size]
    for i in range(0, len(text), chunk_size)
]

client = chromadb.PersistentClient(
    path="./chroma_db"
)

collection = client.get_or_create_collection(
    name="elimu_library"
)

for i, chunk in enumerate(chunks):

    response = embeddings(
        model="nomic-embed-text",
        prompt=chunk
    )

    embedding = response["embedding"]

    collection.add(
    ids=[str(i)],
    documents=[chunk],
    embeddings=[embedding],
    metadatas=[
        {
            "subject": "Biology",
            "source": "biology.pdf"
        }
    ]
)
print(f"Saved {len(chunks)} chunks.")
