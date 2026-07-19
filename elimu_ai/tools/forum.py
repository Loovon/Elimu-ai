# elimu_ai/tools/forum.py  (patched by ElimuTalks)
from django.utils.text import slugify
from elimu_ai.llm import generate as _llm_generate


def _unique_slug(title):
    from forum.models import Thread
    slug = slugify(title)
    base, counter = slug, 1
    while Thread.objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"; counter += 1
    return slug


def generate_forum_post(topic):
    prompt = (
        f"Generate a short, engaging forum discussion post for ElimuTalks.\n"
        f"Topic: {topic}\n"
        f"Return JSON with keys: title (string), body (string). "
        f"No markdown, just valid JSON."
    )
    response_text = _llm_generate(prompt=prompt)
    class _R: pass
    response = _R()
    response_content = response_text
    import json, re
    raw = response_content if isinstance(response_content, str) else ""
    # extract first JSON object
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    # fallback
    return {"title": f"Discussion: {topic}", "body": raw.strip()}


def save_forum_post(title, body, category_slug, persona="TeacherAI"):
    from forum.models import Thread, Post, Category
    from django.contrib.auth.models import User

    category = Category.objects.filter(slug=category_slug).first()
    if not category:
        category = Category.objects.first()
    if not category:
        return None

    user, _ = User.objects.get_or_create(
        username=persona,
        defaults={"email": f"{persona.lower()}@elimutalks.ai", "is_active": True},
    )

    thread = Thread.objects.create(
        title=title, slug=_unique_slug(title), category=category, author=user
    )
    Post.objects.create(thread=thread, author=user, content=body)
    return thread


def create_discussion(topic):
    post_data = generate_forum_post(topic)
    title = post_data.get("title", f"Discussion: {topic}")
    body  = post_data.get("body",  topic)

    # Pick a relevant category based on keywords
    topic_lower = topic.lower()
    if "kcse" in topic_lower or "exam" in topic_lower:
        cat = "kcse"
    elif "cbc" in topic_lower:
        cat = "cbc"
    elif "teacher" in topic_lower or "classroom" in topic_lower:
        cat = "teachers"
    elif "parent" in topic_lower or "family" in topic_lower:
        cat = "parents"
    else:
        cat = "revision"

    thread = save_forum_post(title, body, cat, "CommunityAI")
    if thread:
        return (
            f"✅ New discussion created!\n\n"
            f"Title: {thread.title}\n"
            f"Category: {thread.category.name}\n"
            f"View it at: /thread/{thread.slug}/"
        )
    return f"Discussion topic ready: {title}\n\n{body}"
