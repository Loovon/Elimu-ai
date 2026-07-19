# elimu_ai/service.py

import chromadb
from ollama import embeddings, chat

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_collection("elimu_library")


def ask_ai(question):
    question_embedding = embeddings(
        model="nomic-embed-text",
        prompt=question
    )["embedding"]

    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=3
    )

    context = "\n\n".join(results["documents"][0])

    prompt = f"""
You are an Elimu Talks AI tutor.

Context:
{context}

Question:
{question}

Answer:
"""

    response = chat(
        model="qwen2.5-coder:7b",
        messages=[{"role": "user", "content": prompt}]
    )

    return response["message"]["content"]