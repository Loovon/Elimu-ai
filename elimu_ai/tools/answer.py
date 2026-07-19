
from datetime import timedelta

def unanswered_threads():
    from django.utils import timezone
    from forum.models import Thread
    cutoff = timezone.now() - timedelta(hours=3)
    return Thread.objects.filter(created_at__lt=cutoff)

def answer_unanswered_threads():
    from django.contrib.auth.models import User
    from forum.models import Post
    from elimu_ai.tools.library import recommend_materials
    ai_user, _ = User.objects.get_or_create(
        username="TeacherAI",
        defaults={"email": "teacherai@elimutalks.ai", "is_active": True},
    )
    count = 0
    for thread in unanswered_threads():
        if thread.posts.count() == 1:
            answer = recommend_materials(thread.title)
            Post.objects.create(thread=thread, author=ai_user, content=answer)
            count += 1
    return count
