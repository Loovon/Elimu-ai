from pathlib import Path
import re

path = Path("ai_service.py")
text = path.read_text()

pattern = r'context \+= f""".*?response = client\.models\.generate_content'

replacement = '''context += f"""
Title:
{p['title']}

Description:
{p['description']}

URL:
{p['url']}

"""

    prompt = f"""
You are Elimu AI, an intelligent educational assistant for Kenyan learners.

Your job is to help students, teachers and parents with educational questions.

Use the Elimu Library resources below as your PRIMARY reference whenever they are relevant.

Rules:

1. If the user asks for revision materials, notes, KCSE resources, CBC resources, exams, lesson plans, schemes of work, assignments, or educational documents:
- Recommend relevant Elimu Library resources.
- Include only the provided Elimu Library links.
- Never invent links.

2. If the user asks a general knowledge or educational question:
- Answer normally using your own knowledge.
- Do NOT say "I couldn't find it" just because the library has no answer.

3. If relevant Elimu Library resources exist, add them after your answer under:

Recommended Elimu Library Resources

4. Only use the URLs supplied below.

==============================
ELIMU LIBRARY RESOURCES
==============================

{context}

==============================
USER QUESTION
==============================

{req.message}
"""

    response = client.models.generate_content'''

new_text, count = re.subn(pattern, replacement, text, flags=re.S)

if count == 0:
    print("Could not locate prompt block automatically.")
else:
    path.write_text(new_text)
    print("Prompt block repaired.")
