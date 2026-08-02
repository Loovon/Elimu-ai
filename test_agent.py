from elimu_ai.agent import run_agent

tests = [

    "Grade 7 Mathematics revision notes",

    "Generate a quiz on photosynthesis",

    "Create a discussion about KCSE preparation",

    "Where can I find CBC Mathematics exams?",

    "Explain Newton's First Law."
]

for t in tests:

    print("=" * 80)
    print("QUESTION")
    print(t)

    answer = run_agent(t)

    print("\nANSWER\n")
    print(answer)
