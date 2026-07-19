# elimu_ai/tools/teacher.py
# Teacher persona: explains concepts using RAG, appends catalog links.
# Gracefully handles Ollama being down — always returns catalog links.

import os, re, sys
from urllib.parse import quote
from elimu_ai.llm import generate as _llm_generate, embed as _llm_embed

_CHROMA_PATH = r"C:\Users\Lootus\MyAgent\chroma_db"
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

def _extract_ctx(messages):
    ctx = {"grade": None, "subject": None, "term": None, "year": None, "doc_type": None}
    text = " ".join(m.get("content", "") for m in messages).lower()

    m = re.search(r"grade\s*(\d+|pp1|pp2)", text, re.I)
    if m:
        ctx["grade"] = "Grade " + m.group(1).upper()
    m = re.search(r"form\s*(\d)", text, re.I)
    if m and not ctx["grade"]:
        ctx["grade"] = "Form " + m.group(1)
    m = re.search(r"term\s*(\d)", text, re.I)
    if m:
        ctx["term"] = m.group(1)
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        ctx["year"] = m.group(1)

    subjects = [
        "mathematics activities", "mathematics", "maths",
        "english activities", "english",
        "kiswahili activities", "kiswahili",
        "integrated science", "social studies", "environmental activities",
        "creative arts", "pre-technical studies", "agriculture and nutrition",
        "biology", "chemistry", "physics", "history", "geography",
        "cre", "ire", "business studies", "computer studies",
        "agriculture", "science",
    ]
    for s in subjects:
        if s in text:
            ctx["subject"] = s.title()
            break

    doc_types = ["exam", "assessment", "notes", "schemes", "lesson plan",
                 "homework", "past paper", "revision", "booklet", "topical"]
    for d in doc_types:
        if d in text:
            ctx["doc_type"] = d.title()
            break
    return ctx

def _needs_clarification(ctx, question):
    resource_kws = [
        "find", "get", "need", "looking for", "where", "exam",
        "assessment", "notes", "scheme", "past paper", "revision",
        "homework", "materials", "resources", "send", "download", "buy", "link",
        "recommend", "suggestion",
    ]
    if not any(k in question.lower() for k in resource_kws):
        return ""
    # If we have at least a subject, we can search — no clarification needed
    if ctx.get("subject"):
        return ""
    if not ctx["grade"] and not ctx["subject"]:
        return (
            "Sure, happy to help! Just so I find exactly the right thing "
            "— which grade or form is this for, and which subject?"
        )
    if not ctx["subject"]:
        return "Got it, " + (ctx["grade"] or "") + "! Which subject do you need?"
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

SYSTEM = (
    "You are a helpful educational assistant on ElimuTalks, Kenya's school community platform.\n"
    "Tone: warm, direct, like a knowledgeable teacher or older sibling.\n\n"
    "ABSOLUTE RULES — violating any of these is not allowed:\n"
    "1. ONLY reference content from elimulibrary.com or ElimuTalks (this platform).\n"
    "2. NEVER mention any other website: not Teacher.co.ke, Wikipedia, Google, YouTube, "
    "Khan Academy, KNEC portal, Longhorn, or any other site. If you are tempted to mention "
    "another site, instead say: try the Elimu Library.\n"
    "3. If the exact document does not exist in your context, say so honestly and suggest "
    "the user search the Elimu Library — do NOT invent document names or recommend other sites.\n"
    "4. NEVER write any URLs — document links are appended automatically after your answer.\n"
    "5. No markdown — no #, **, __, -, backticks. Plain text only.\n"
    "6. Keep answers to 2-3 short paragraphs maximum."
)

def _get_catalog_links(ctx, question):
    """Get exact document URLs from catalog. Never calls LLM."""
    try:
        from elimu_ai.catalog_search import search_catalog, format_recommendations, catalog_available
        from elimu_ai.tools.library import _infer_doc_type
        if not catalog_available():
            raise Exception("no catalog")

        doc_type = _infer_doc_type(question)

        # Build targeted search based on doc_type
        variants = []
        if ctx.get("grade") and ctx.get("subject"):
            g, s = ctx["grade"], ctx["subject"]
            yr, tm = ctx.get("year") or "2026", ctx.get("term")
            if doc_type == "notes":
                variants = [
                    {"grade": g, "subject": s, "keyword": "notes"},
                    {"grade": g, "subject": s, "year": yr, "keyword": "notes"},
                ]
            elif doc_type == "scheme":
                variants = [{"grade": g, "subject": s, "keyword": "schemes"}]
            else:
                variants = [
                    {"grade": g, "subject": s, "term": tm, "year": yr},
                    {"grade": g, "subject": s, "keyword": doc_type},
                ]
        else:
            variants = [{"keyword": question, "max_results": 5}]

        all_results = []
        seen = set()
        for kw in variants:
            kw.setdefault("max_results", 5)
            for r in search_catalog(**kw):
                url = r.get("url", "")
                if url and "/site/document/" in url and url not in seen:
                    seen.add(url)
                    all_results.append(r)

        if all_results:
            return "\n" + format_recommendations(all_results[:5], question)
    except Exception:
        pass

    # Fallback search link
    search_q = question
    if ctx.get("grade") and ctx.get("subject"):
        parts = [ctx.get("year", "2026"), ctx["grade"], ctx["subject"]]
        if ctx.get("term"):
            parts.append("term " + ctx["term"])
        search_q = " ".join(p for p in parts if p)
    return (
        "\n\nSearch the Elimu Library: "
        + "https://www.elimulibrary.com/?s=" + quote(search_q)
    )

# Kenyan curriculum: subjects available by level
_GRADE_SUBJECTS = {
    # Lower Primary (1-3): Activities-based
    "grade1": ["mathematics activities", "english activities", "kiswahili activities",
               "environmental activities", "creative arts", "ire", "cre"],
    "grade2": ["mathematics activities", "english activities", "kiswahili activities",
               "environmental activities", "creative arts", "ire", "cre"],
    "grade3": ["mathematics activities", "english activities", "kiswahili activities",
               "environmental activities", "creative arts", "ire", "cre"],
    # Upper Primary (4-6)
    "grade4": ["mathematics", "english", "kiswahili", "science", "social studies",
               "creative arts", "agriculture", "ire", "cre"],
    "grade5": ["mathematics", "english", "kiswahili", "science", "social studies",
               "creative arts", "agriculture", "ire", "cre"],
    "grade6": ["mathematics", "english", "kiswahili", "science", "social studies",
               "creative arts", "agriculture", "ire", "cre"],
    # JSS (7-9)
    "grade7": ["mathematics", "english", "kiswahili", "integrated science",
               "social studies", "pre-technical studies", "agriculture and nutrition",
               "creative arts", "ire", "cre"],
    "grade8": ["mathematics", "english", "kiswahili", "integrated science",
               "social studies", "pre-technical studies", "agriculture and nutrition",
               "creative arts", "ire", "cre"],
    "grade9": ["mathematics", "english", "kiswahili", "integrated science",
               "social studies", "pre-technical studies", "agriculture and nutrition",
               "creative arts", "ire", "cre"],
    # Senior (10-12) / Secondary (Form 1-4)
    "grade10": ["mathematics", "english", "kiswahili", "biology", "chemistry",
                "physics", "history", "geography", "business studies", "cre", "ire"],
}
# Form levels
for f in ["form1","form2","form3","form4"]:
    _GRADE_SUBJECTS[f] = _GRADE_SUBJECTS["grade10"]

def _grade_has_subject(grade, subject):
    """Return True/False and a suggestion if grade doesn't offer that subject."""
    if not grade or not subject:
        return True, None
    g_key = grade.lower().replace(" ", "")
    s_key = subject.lower().replace(" ", "").replace("activities","")
    subjects = _GRADE_SUBJECTS.get(g_key, [])
    if not subjects:
        return True, None  # Unknown grade — don't block
    match = any(s_key in s.replace(" ","") or s.replace(" ","") in s_key for s in subjects)
    if not match:
        # Find what grade this subject starts at
        suggestion = None
        for grade_key, subj_list in _GRADE_SUBJECTS.items():
            if any(s_key in s.replace(" ","") for s in subj_list):
                suggestion = grade_key.replace("grade","Grade ").replace("form","Form ")
                break
        return False, suggestion
    return True, None

def teacher_response(question, history=None, persona_name="Elimu AI"):
    if history is None:
        history = []
    all_msgs = history + [{"role": "user", "content": question}]
    ctx = _extract_ctx(all_msgs)

    clarify = _needs_clarification(ctx, question)
    if clarify:
        return clarify

    # Check if subject exists at this grade level in Kenyan curriculum
    has_subj, suggested_grade = _grade_has_subject(ctx.get('grade'), ctx.get('subject'))
    if not has_subj and suggested_grade:
        note = (
            f"{ctx['subject']} is not taught at {ctx['grade']} level in the Kenyan curriculum. "
            f"It starts from {suggested_grade}. "
            f"I'll show you the available {ctx['subject']} materials from {suggested_grade} onwards."
        )
        # Still search — return biology docs from the right grade
        link_block = _get_catalog_links({'grade': suggested_grade, 'subject': ctx['subject'],
                                         'term': ctx.get('term'), 'year': ctx.get('year')}, question)
        return note + link_block

    # Build search query
    search_q = question
    if ctx["grade"] and ctx["subject"]:
        parts = [ctx.get("year", "2026"), ctx["grade"], ctx["subject"]]
        if ctx["term"]:
            parts.append("term " + ctx["term"])
        search_q = " ".join(str(p) for p in parts if p is not None)

    rag = _rag_context(search_q)

    # ElimuTalks local content
    local_context = ""
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        from blog.models import Article
        from forum.models import Post
        from django.db.models import Q
        articles = Article.objects.filter(
            Q(title__icontains=question) | Q(content__icontains=question)
        )[:2]
        posts = Post.objects.filter(content__icontains=question)[:3]
        parts = []
        for a in articles:
            parts.append("ElimuTalks Article: " + a.title + "\n" + a.content[:300])
        for p in posts:
            parts.append("ElimuTalks Forum:\n" + p.content[:200])
        if parts:
            local_context = "\n\n".join(parts)
    except Exception:
        pass

    # Try LLM — but always return catalog links even if it fails
    answer = ""
    try:
        messages = [{"role": "system", "content": SYSTEM}]
        for m in history[-6:]:
            messages.append({"role": m["role"], "content": m["content"]})
        user_content = question
        ctx_parts = []
        if rag:
            ctx_parts.append("Elimu Library content:\n" + rag)
        if local_context:
            ctx_parts.append("ElimuTalks community content:\n" + local_context)
        if ctx_parts:
            user_content = "\n\n".join(ctx_parts) + "\n\nQuestion: " + question
        messages.append({"role": "user", "content": user_content})
        resp_text = _llm_generate(
            prompt=messages[-1]["content"],
            system=next((m["content"] for m in messages if m["role"]=="system"), None),
            history=[m for m in messages[1:-1] if m["role"] != "system"],
        )
        # Wrap in expected format
        class _Resp: pass
        resp = _Resp()
        resp_src = resp_text
        answer = _strip_md(resp_src if isinstance(resp_src, str) else "")
    except Exception:
        # Ollama down — still return catalog links
        answer = (
            "Here are the materials from the Elimu Library that match your request. "
            "You can click any link below to go directly to that document."
        )

    # ALWAYS append catalog links after the answer
    link_block = _get_catalog_links(ctx, question)
    return answer + link_block
