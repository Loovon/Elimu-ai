from pathlib import Path

text = Path("ai_service.py").read_text()

start = text.find('prompt = f"""')

if start == -1:
    print("prompt block not found")
    exit()

print("Found prompt at character:", start)

print("=" * 60)
print(text[start:start+1200])
print("=" * 60)
