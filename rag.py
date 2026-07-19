import chromadb
from ollama import embeddings, chat

client = chromadb.PersistentClient(
    path="./chroma_db"
)

collection = client.get_collection(
    name="elimu_library"
)

while True:
    question = input("\nYou: ")

    if question.lower() == "exit":
        break

    question_embedding = embeddings(
        model="nomic-embed-text",
        prompt=question
    )["embedding"]

    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=3
    )

    context = "\n\n".join(
        results["documents"][0]
    )

    prompt = f"""
    You are an educational tutor for Elimu Talks.

    Context:
    {context}

    Question:
    {question}

    Answer:
    """

    response = chat(
        model="qwen2.5-coder:7b",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    print("\nAI:")
    print(response["message"]["content"])