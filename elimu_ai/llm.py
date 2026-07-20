# elimu_ai/llm.py
#
# Unified LLM gateway for Elimu AI.
# All tools call generate() and embed() — never import ollama or google directly.
#
# Switch providers by setting the AI_PROVIDER environment variable:
#   AI_PROVIDER=ollama        (default — local, free, requires Ollama running)
#   AI_PROVIDER=gemini        (Google Gemini API — requires GEMINI_API_KEY)
#   AI_PROVIDER=openai        (OpenAI — requires OPENAI_API_KEY)
#
# Model overrides:
#   OLLAMA_MODEL=qwen2.5-coder:7b     (default Ollama model)
#   OLLAMA_EMBED_MODEL=nomic-embed-text
#   GEMINI_MODEL=gemini-1.5-flash     (default Gemini model)
#   OPENAI_MODEL=gpt-4o-mini          (default OpenAI model)

import os
from typing import Optional

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_OLLAMA_MODEL  = "qwen2.5:0.5b"
_DEFAULT_EMBED_MODEL   = "nomic-embed-text"
_DEFAULT_GEMINI_MODEL  = "gemini-1.5-flash"
_DEFAULT_OPENAI_MODEL  = "gpt-4o-mini"


def _provider() -> str:
    return os.getenv("AI_PROVIDER", "ollama").lower().strip()


# ── Chat: generate a text response ───────────────────────────────────────────
def generate(
    prompt: str,
    system: Optional[str] = None,
    history: Optional[list] = None,
    temperature: float = 0.7,
) -> str:
    """
    Generate a chat response.

    Args:
        prompt:      The user message.
        system:      Optional system prompt.
        history:     Optional list of {"role": "user"|"assistant", "content": str}
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).

    Returns:
        The model's text response as a plain string.
        Returns an empty string on failure (callers should handle gracefully).
    """
    provider = _provider()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for m in (history or []):
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": prompt})

    try:
        if provider == "gemini":
            return _generate_gemini(messages, temperature)
        elif provider == "openai":
            return _generate_openai(messages, temperature)
        else:
            return _generate_ollama(messages)
    except Exception as e:
        # Log but never crash the calling tool
        _log_error(f"generate() [{provider}] failed: {e}")
        return ""


# ── Embeddings ────────────────────────────────────────────────────────────────
def embed(text: str) -> list:
    """
    Generate an embedding vector for text.
    Used by the RAG pipeline (chromadb queries).

    Returns a list of floats, or [] on failure.
    """
    provider = _provider()
    try:
        if provider == "gemini":
            return _embed_gemini(text)
        elif provider == "openai":
            return _embed_openai(text)
        else:
            return _embed_ollama(text)
    except Exception as e:
        _log_error(f"embed() [{provider}] failed: {e}")
        return []


# ── Ollama ────────────────────────────────────────────────────────────────────
def _generate_ollama(messages: list) -> str:
    from ollama import chat
    model = os.getenv("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL)
    response = chat(model=model, messages=messages)
    return response["message"]["content"]


def _embed_ollama(text: str) -> list:
    from ollama import embeddings
    model = os.getenv("OLLAMA_EMBED_MODEL", _DEFAULT_EMBED_MODEL)
    return embeddings(model=model, prompt=text)["embedding"]


# ── Google Gemini ─────────────────────────────────────────────────────────────
def _generate_gemini(messages: list, temperature: float) -> str:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", _DEFAULT_GEMINI_MODEL)
    model = genai.GenerativeModel(model_name)

    # Convert messages to Gemini format
    # Gemini uses "user" / "model" roles; system becomes first user message
    history = []
    current_prompt = ""
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "system":
            history.append({"role": "user",  "parts": [content]})
            history.append({"role": "model", "parts": ["Understood. I will follow these instructions."]})
        elif role == "user":
            current_prompt = content
        elif role == "assistant":
            history.append({"role": "user",  "parts": [current_prompt]})
            history.append({"role": "model", "parts": [content]})
            current_prompt = ""

    chat_session = model.start_chat(history=history[:-0] if history else [])
    response = chat_session.send_message(current_prompt or messages[-1]["content"])
    return response.text


def _embed_gemini(text: str) -> list:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    genai.configure(api_key=api_key)
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


# ── OpenAI ────────────────────────────────────────────────────────────────────
def _generate_openai(messages: list, temperature: float) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    model = os.getenv("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content


def _embed_openai(text: str) -> list:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


# ── Logging ───────────────────────────────────────────────────────────────────
def _log_error(msg: str):
    """Non-crashing error logger."""
    try:
        import logging
        logging.getLogger("elimu_ai.llm").warning(msg)
    except Exception:
        pass
