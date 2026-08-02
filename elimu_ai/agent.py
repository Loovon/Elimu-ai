from elimu_ai.router import decide_persona

from elimu_ai.qdrant_db import search

from elimu_ai.gemini import generate

from elimu_ai.prompts import SYSTEM_PROMPT

from elimu_ai.helpers import (
    clean_answer,
    rewrite_links,
    referral_url,
)

from elimu_ai.tools.teacher import teacher_response
from elimu_ai.tools.quiz import quiz_prompt
from elimu_ai.tools.community import community_prompt
from elimu_ai.tools.library import library_prompt


def build_context(hits):
    """
    Convert Qdrant search results into context for Gemini.
    """

    context = ""

    for hit in hits:

        p = hit.payload

        context += f"""

Title:
{p.get('title','')}

Description:
{p.get('description','')}

URL:
{p.get('url','')}

"""

    return context


def build_prompt(persona, question, context, history=None):

    if persona == "teacher":
        return teacher_response(question, history or [])

    elif persona == "quiz":
        return quiz_prompt(question, context)

    elif persona == "community":
        return community_prompt(question, context)

    elif persona == "librarian":
        return library_prompt(question, context)

    return SYSTEM_PROMPT.format(
        context=context,
        question=question,
    )


def run_agent(question, history=None):

    ##################################################
    # Decide persona
    ##################################################

    persona = decide_persona(question)

    ##################################################
    # Search Qdrant
    ##################################################

    hits = search(question)

    ##################################################
    # Build RAG Context
    ##################################################

    context = build_context(hits)

    ##################################################
    # Persona Prompt
    ##################################################

    prompt = build_prompt(
        persona,
        question,
        context,
        history,
    )

    ##################################################
    # Gemini
    ##################################################

    raw_answer = generate(prompt)

    ##################################################
    # Cleanup
    ##################################################

    answer = rewrite_links(
        clean_answer(raw_answer)
    )

    ##################################################
    # Sources
    ##################################################

    sources = []

    for hit in hits:

        try:
            sources.append(
                referral_url(
                    hit.payload["url"]
                )
            )

        except Exception:
            pass

    return {
        "persona": persona,
        "answer": answer,
        "sources": sources,
    }


if __name__ == "__main__":

    history = []

    while True:

        q = input("\nYou: ")

        if q.lower() == "exit":
            break

        result = run_agent(q, history)

        print("\nPersona :", result["persona"])

        print("\nAnswer:\n")

        print(result["answer"])

        if result["sources"]:

            print("\nSources:\n")

            for s in result["sources"]:
                print("-", s)

        history.append(
            {
                "role": "user",
                "content": q,
            }
        )

        history.append(
            {
                "role": "assistant",
                "content": result["answer"],
            }
        )
