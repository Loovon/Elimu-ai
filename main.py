"""
main.py

CLI entry point for local development and testing.
Runs a simple REPL that exercises run_agent() directly.
"""

from elimu_ai.agent import run_agent


def main() -> None:
    print("Elimu AI — interactive mode. Type 'exit' to quit.\n")
    history = []

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() == "exit":
            break

        result = run_agent(question, history)

        print(f"\nPersona : {result['persona']}")
        print(f"Tools   : {', '.join(result['tools'])}")
        print(f"\nAnswer:\n{result['answer']}")

        if result["sources"]:
            print("\nSources:")
            for s in result["sources"]:
                print(f"  - {s}")

        print()

        history.append({"role": "user",      "content": question})
        history.append({"role": "assistant", "content": result["answer"]})


if __name__ == "__main__":
    main()
