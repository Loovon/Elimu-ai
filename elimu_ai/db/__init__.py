"""
elimu_ai/db/__init__.py

PostgreSQL repository layer.

All database access passes through repository classes.
No raw SQL is executed from tools or the orchestrator.

Available repositories:
  MemoryRepository        — conversation summaries
  AnalyticsRepository     — request/response analytics
  SchedulerRepository     — job run history
  QuizRepository          — saved quizzes
  RecommendationRepository— recommendation cache
  ForumRepository         — forum thread operations (read-only via HTTP)
  UserRepository          — user profile lookups (read-only)

Import:
    from elimu_ai.db.repositories import MemoryRepository, AnalyticsRepository
"""
