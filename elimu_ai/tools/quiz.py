# elimu_ai/tools/quiz.py
# Quiz persona: generates questions from RAG context.

import os
import re
from urllib.parse import quote
from elimu_ai.gemini import generate


_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        import chromadb
        _client = chromadb.PersistentClient(path=_CHROMA_PATH)
        try:
            _collection = _client.get_collection("elimu_library")
        except Exception:
            _collection = None
    return _collection


def _rag_context(question, n=5):
    try:
        col = _get_collection()
        if not col:
            return ""
        q_emb = _llm_embed(question)
        results = col.query(query_embeddings=[q_emb], n_results=n)
        docs = results["documents"][0]
        return "\n\n".join(docs) if docs else ""
    except Exception:
        return ""


def _strip_md(text):
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{2,3}([^*\n]+)\*{2,3}", r"\1", text)
    text = re.sub(r"_{2,3}([^_\n]+)_{2,3}", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"_([^_\n]+)_", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_quiz(question):
    lib_link = "https://www.elimulibrary.com/?s=" + quote(question)
    rag = _rag_context(question)

    prompt = (
        "You are a KCSE quiz master on ElimuTalks. Write in plain text — no markdown, "
        "no asterisks, no hashes, no dashes as bullets.\n\n"
        "Generate a quiz on: " + question + "\n\n"
        "Use ONLY this Elimu Library content as your source:\n"
        + (rag or "No specific content found — use general Kenyan curriculum knowledge.")
        + "\n\nFormat exactly like this:\n"
        "Multiple Choice Questions\n"
        "1. Question text\n"
        "A) option  B) option  C) option  D) option\n"
        "Answer: X\n\n"
        "Write 5 multiple choice and 3 structured questions with model answers.\n"
        "Do NOT write any URLs — they will be added separately."
    )
    try:
        resp_text = generate(prompt)
        answer = _strip_md(resp_text or "")
    except Exception:
        answer = "Could not generate quiz right now."

    # Append catalog links — never let LLM write URLs
    try:
        import sys
        sys.path.insert(0, r"C:\\Users\\Lootus\\MyAgent")
        from elimu_ai.tools.teacher import _extract_ctx
        from elimu_ai.catalog_search import search_catalog, format_recommendations, catalog_available
        ctx = _extract_ctx([{"content": question}])
        if catalog_available():
            results = search_catalog(
                grade=ctx.get("grade"),
                subject=ctx.get("subject"),
                keyword=question,
                max_results=3,
            )
            doc_results = [r for r in results if "/site/document/" in r.get("url", "")]
            if doc_results:
                answer += "\n\n" + format_recommendations(doc_results, question)
                return answer
    except Exception:
        pass

    answer += "\n\nFind revision materials here: " + lib_link
    answer += "\nPay via M-Pesa Till 323253: https://www.elimulibrary.com/pay/"
    return answer
