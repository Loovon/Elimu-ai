from pathlib import Path

path = Path("ai_service.py")
text = path.read_text()

if "from helpers import clean_answer" in text:
    print("Already imported.")
    raise SystemExit

lines = text.splitlines()

for i, line in enumerate(lines):
    if line.startswith("from") or line.startswith("import"):
        last_import = i

lines.insert(last_import + 1, "from helpers import clean_answer")

path.write_text("\n".join(lines))

print("Import added.")
