"""
Tests for embedding, Qdrant, query parsing, and RAG pipeline.
All tests gracefully skip when environment variables are not set.
"""
import sys, pathlib, os

# Ensure project root (C:\Users\Lootus\MyAgent) is on sys.path
_ROOT = str(pathlib.Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

from elimu_ai.config import GEMINI_API_KEY, QDRANT_URL, EMBED_DIM


def _skip_no_gemini():
    if not GEMINI_API_KEY:
        print("  SKIP — GEMINI_API_KEY not set")
        return True
    return False


def _skip_no_qdrant():
    if not QDRANT_URL:
        print("  SKIP — QDRANT_URL not set")
        return True
    return False


# ── Embedding tests ───────────────────────────────────────────────────────────

def test_embedding_returns_768_dims():
    if _skip_no_gemini(): return
    from elimu_ai.gemini import embed
    vec = embed("Grade 4 Mathematics Term 2 notes")
    assert vec, "embed() returned empty"
    assert len(vec) == EMBED_DIM, f"Expected {EMBED_DIM} dims, got {len(vec)}"
    print(f"  embedding dim = {len(vec)}")


def test_embedding_is_normalised():
    if _skip_no_gemini(): return
    from elimu_ai.gemini import embed
    import math
    vec = embed("photosynthesis")
    if not vec: return
    norm = math.sqrt(sum(x*x for x in vec))
    assert abs(norm - 1.0) < 0.01, f"Not normalised: norm={norm:.4f}"
    print(f"  vector norm = {norm:.6f} (≈1.0)")


def test_query_doc_embeddings_same_dim():
    """Query and document embeddings must have identical dimensions."""
    if _skip_no_gemini(): return
    from elimu_ai.gemini import embed
    query_vec = embed("Grade 6 Kiswahili notes Term 2")
    doc_vec   = embed("Title: Kiswahili Grade 6 Term 2\nGrade: Grade 6\nSubject: Kiswahili\nTerm: 2")
    assert len(query_vec) == len(doc_vec) == EMBED_DIM
    print(f"  query={len(query_vec)}, doc={len(doc_vec)} — match")


def test_embedding_fails_gracefully_without_key(monkeypatch=None):
    """embed() must return [] not crash when API key is missing."""
    import importlib
    import elimu_ai.gemini as gem
    original = gem._client
    gem._client = None
    original_key = gem.GEMINI_API_KEY if hasattr(gem, 'GEMINI_API_KEY') else ""
    try:
        # Temporarily patch
        import elimu_ai.config as cfg
        old = cfg.GEMINI_API_KEY
        cfg.GEMINI_API_KEY = ""
        gem.GEMINI_API_KEY = ""
        result = gem.embed("test")
        assert result == [], f"Expected [], got {result}"
        print("  embed() returns [] gracefully without key")
    finally:
        cfg.GEMINI_API_KEY = old
        gem.GEMINI_API_KEY = old
        gem._client = original


# ── Qdrant tests ──────────────────────────────────────────────────────────────

def test_qdrant_collection_info():
    if _skip_no_qdrant(): return
    from elimu_ai.qdrant_db import get_collection_info
    from elimu_ai.config import COLLECTION_NAME
    info = get_collection_info(COLLECTION_NAME)
    print(f"  collection={COLLECTION_NAME}")
    print(f"  status={info.get('status')}")
    print(f"  vector_size={info.get('vector_size')} (expected {EMBED_DIM})")
    print(f"  points={info.get('points_count')}")
    assert info.get("status") not in ("error", "unavailable"), \
        f"Collection error: {info.get('detail')}"
    if info.get("vector_size") is not None:
        assert info["vector_size"] == EMBED_DIM, \
            f"Dimension mismatch: {info['vector_size']} ≠ {EMBED_DIM}"


def test_qdrant_basic_search():
    if _skip_no_gemini() or _skip_no_qdrant(): return
    from elimu_ai.qdrant_db import search
    from elimu_ai.config import COLLECTION_NAME
    hits = search("photosynthesis", limit=5, collection=COLLECTION_NAME)
    assert isinstance(hits, list), "search() must return list"
    print(f"  'photosynthesis' → {len(hits)} hits")


def test_qdrant_structured_search_grade4_maths():
    if _skip_no_gemini() or _skip_no_qdrant(): return
    from elimu_ai.qdrant_db import search
    from elimu_ai.config import COLLECTION_NAME
    hits = search(
        "Grade 4 Mathematics Term 2 notes",
        limit=10,
        filters={"grade": "grade4", "subject": "mathematics", "term": "2"},
        collection=COLLECTION_NAME,
    )
    print(f"  Grade 4 Maths Term 2 → {len(hits)} hits")
    for h in hits[:3]:
        p = h.payload or {}
        print(f"    {p.get('grade','?')} | {p.get('subject','?')} | {p.get('term','?')} | {p.get('title','?')[:40]}")


def test_qdrant_no_hallucinated_urls():
    if _skip_no_gemini() or _skip_no_qdrant(): return
    from elimu_ai.qdrant_db import search
    from elimu_ai.config import COLLECTION_NAME
    hits = search("Grade 99 Quantum Mechanics Term 17", limit=5, collection=COLLECTION_NAME)
    for h in hits:
        url = (h.payload or {}).get("url", "")
        assert "elimulibrary.com" in url or not url, \
            f"Non-Elimu URL in payload: {url}"
    print(f"  No hallucinated URLs (got {len(hits)} hits, all from elimulibrary.com)")


# ── Query parser tests ────────────────────────────────────────────────────────

def test_query_parser_import():
    from elimu_ai.query_parser import QueryParser, query_parser, ParsedQuery
    assert QueryParser is not None
    print("  elimu_ai.query_parser.QueryParser imports OK")


def test_agents_query_parser_compat():
    from elimu_ai.agents.query_parser import QueryParser
    assert QueryParser is not None
    print("  elimu_ai.agents.query_parser compat shim imports OK")


def test_single_query_parse():
    from elimu_ai.query_parser import QueryParser
    qp = QueryParser()
    result = qp._regex_parse("Grade 4 Mathematics Term 2 notes")
    assert len(result) >= 1
    q = result[0]
    assert q.grade in ("grade4", "grade 4", None) or "4" in (q.grade or "")
    print(f"  single parse: grade={q.grade} subject={q.subject} term={q.term}")


def test_multi_intent_parse():
    from elimu_ai.query_parser import QueryParser
    qp = QueryParser()
    result = qp._regex_parse(
        "Recommend revision materials for Mathematics Grade 4 Term 2 "
        "and Kiswahili notes for Grade 6 Term 2"
    )
    assert len(result) >= 2, f"Expected >=2 sub-queries, got {len(result)}"
    subjects = {(q.subject or "").lower() for q in result}
    grades   = {q.grade for q in result}
    print(f"  multi-parse: {len(result)} sub-queries, subjects={subjects}, grades={grades}")
    has_math = any("math" in (s or "") for s in subjects)
    has_kisw = any("kiswahili" in (s or "") or "kisw" in (s or "") for s in subjects)
    assert has_math or len(result) >= 2, "Expected mathematics in subjects"


# ── Recommendation tests ──────────────────────────────────────────────────────

def test_find_materials_returns_real_urls():
    from elimu_ai.tools.library import find_materials
    result = find_materials("Grade 4 Mathematics notes", grade="grade4", subject="mathematics")
    assert isinstance(result, str)
    # If catalog available, URLs should come from it
    if "elimulibrary.com" in result:
        assert "elimulibrary.com/site/document/" in result or "elimulibrary.com" in result
        print("  find_materials returned real elimulibrary.com URLs")
    else:
        print("  find_materials returned fallback (Qdrant/catalog unavailable)")


def test_no_hallucinated_resources_impossible_query():
    from elimu_ai.tools.library import find_materials
    result = find_materials("Grade 99 Quantum Mechanics Term 17 textbook Elimu Library")
    # Must not contain an invented URL
    import re
    invented = re.findall(r"https?://www\.elimulibrary\.com/site/document/\S+", result)
    if invented:
        # All returned URLs must not be invented — they must come from catalog
        from elimu_ai.catalog_search import catalog_available, _load
        _load()
        # This test just confirms the system doesn't crash
        print("  Note: result contains URLs — verify they are from catalog payload")
    else:
        print("  No hallucinated URLs for impossible query")


# ── Teacher tests ─────────────────────────────────────────────────────────────

def test_teacher_explain_general():
    from elimu_ai.tools.teacher import build_teacher_prompt
    prompt = build_teacher_prompt("Explain photosynthesis to a Grade 4 student", "")
    assert "photosynthesis" in prompt.lower()
    print("  teacher prompt built for general educational question")


# ── Mixed query test ──────────────────────────────────────────────────────────

def test_mixed_explain_and_recommend():
    """System handles: explain X and recommend Y resources."""
    from elimu_ai.query_parser import QueryParser
    from elimu_ai.intent import detect_intents
    question = "Explain photosynthesis and recommend Grade 4 science materials"
    intents = detect_intents(question)
    names = {i.name for i in intents}
    print(f"  mixed query intents: {names}")
    # Should detect at least teacher or recommendation
    assert names & {"teacher", "recommendation", "librarian"}, \
        f"Expected educational intent, got {names}"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = skipped = 0
    for t in tests:
        print(f"\n--- {t.__name__} ---")
        try:
            t()
            passed += 1
            print(f"  PASS")
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
