# elimu_ai/tools/teacher.py

from elimu_ai.qdrant_db import search
from elimu_ai.gemini import generate
from elimu_ai.prompts import SYSTEM_PROMPT

from elimu_ai.helpers import (
    clean_answer,
    rewrite_links,
    referral_url,
)

from elimu_ai.catalog_search import (
    search_catalog,
    format_recommendations,
)


def teacher_response(question, history=None):
    """
    Teacher Persona

    Retrieves context from Qdrant,
    generates a Gemini response,
    appends Elimu Library resources.
    """

    if history is None:
        history = []

    ########################################
    # Search Vector Database
    ########################################

    hits = search(question)

    context = ""

    for hit in hits:

        p = hit.payload

        context += f"""
Title:
{p.get("title","")}

Description:
{p.get("description","")}

URL:
{p.get("url","")}
"""

    ########################################
    # Prompt
    ########################################

    prompt = SYSTEM_PROMPT.format(

        context=context,

        question=question,

    )

    ########################################
    # Gemini
    ########################################

    response = generate(prompt)

    ########################################
    # Clean Answer
    ########################################

    answer = rewrite_links(

        clean_answer(response)

    )

    ########################################
    # Catalog Recommendations
    ########################################

    try:

        results = search_catalog(

            keyword=question,

            max_results=5,

        )

        if results:

            answer += "\n\n"

            answer += format_recommendations(

                results,

                question,

            )

    except Exception:

        pass

    ########################################
    # Sources
    ########################################

    sources = []

    for h in hits:

        try:

            sources.append(

                referral_url(

                    h.payload["url"]

                )

            )

        except Exception:

            pass

    return {

        "answer": answer,

        "sources": sources,

    }
