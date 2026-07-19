# elimu_ai/tools/community.py
# Community persona: finds relevant existing threads OR creates a new one.

def create_discussion(topic):
    """
    1. First check if a relevant thread already exists on ElimuTalks.
    2. If yes, recommend it.
    3. If no, create a new thread on the most relevant category.
    """
    try:
        import os, sys
        sys.path.insert(0, r"C:\Users\Lootus\MyAgent")
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django; django.setup()

        from django.db.models import Q
        from forum.models import Thread, Category

        # Search for existing related threads
        keywords = [w for w in topic.lower().split() if len(w) > 3]
        q = Q()
        for kw in keywords[:4]:
            q |= Q(title__icontains=kw)

        existing = Thread.objects.filter(q).select_related("category")[:3]
        if existing.exists():
            lines = [
                f"There are already some great discussions about this on ElimuTalks! "
                f"Here are the most relevant ones:",
                ""
            ]
            for t in existing:
                lines.append(f"- {t.title}")
                lines.append(f"  Category: {t.category.name}")
                lines.append(f"  /thread/{t.slug}/")
                lines.append("")
            lines.append(
                "You can also start a new thread if you have a different angle on this topic."
            )
            return "\n".join(lines)

    except Exception:
        pass

    # No existing threads — create a new one
    try:
        from elimu_ai.tools.forum import create_discussion as _forum_create
        return _forum_create(topic)
    except Exception as e:
        return (
            f"That's a great topic for discussion: {topic}\n\n"
            f"What do you think? Share your thoughts below — the community would love to hear them."
        )
