from ollama import chat

messages = [
    {
        'role': 'system',
        'content': 'You are my AI mentor helping me learn AI and build Elimu Talks.'
    }
]

print("AI Assistant Started!")
print("Type 'exit' to quit.\n")

while True:
    user_input = input("You: ")

    if user_input.lower() == "exit":
        break

    messages.append({
        'role': 'user',
        'content': user_input
    })

    response = chat(
        model='qwen2.5-coder:7b',
        messages=messages
    )

    ai_message = response['message']['content']

    print("\nAI:", ai_message)
    print()

    messages.append({
        'role': 'assistant',
        'content': ai_message
    })