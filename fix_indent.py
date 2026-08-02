from pathlib import Path

file = Path("ai_service.py")

text = file.read_text()

# convert tabs to 4 spaces
text = text.expandtabs(4)

# remove trailing whitespace
text = "\n".join(line.rstrip() for line in text.splitlines())

file.write_text(text)

print("Indentation normalized.")
