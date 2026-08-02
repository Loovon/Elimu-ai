from google import genai

from elimu_ai.config import GEMINI_API_KEY, LLM_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)


def generate(prompt: str):

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt,
    )

    return response.text
