"""
main.py

Interactive CLI for local development and testing.
Exercises run_agent() directly without starting the FastAPI server.

Usage:
    python main.py
"""

from __future__ import annotations

from elimu_ai.agent import run_agent


def main() -> None:
    print("Elimu AI — interactive mode")
    print("Type 'exit' to quit.\n")
    history = []

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break

        result = run_agent(question, history)

        print(f"\nPersona : {result['persona']}")
        print(f"Tools   : {', '.join(result['tools'])}")
        print(f"\n{result['answer']}")

        if result["sources"]:
            print("\nSources:")
            for s in result["sources"]:
                print(f"  {s}")
        print()

        history.append({"role": "user",      "content": question})
        history.append({"role": "assistant", "content": result["answer"]})


if __name__ == "__main__":
    main()
