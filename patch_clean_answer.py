from pathlib import Path

path = Path("ai_service.py")
text = path.read_text()

old = 'return {"answer": response.text, "sources": [h.payload["url"] for h in hits]}'

new = '''
answer = clean_answer(response.text)

return {
    "answer": answer,
    "sources": [h.payload["url"] for h in hits]
}
'''

if old in text:
    text = text.replace(old, new)
    path.write_text(text)
    print("Answer cleaning added.")
else:
    print("Return statement not found.")
