
from elimu_ai.router import decide_persona
from elimu_ai.tools.teacher import teacher_response
from elimu_ai.tools.library import recommend_materials
from elimu_ai.tools.quiz import generate_quiz
from elimu_ai.tools.community import create_discussion

def run_agent(question, history=None):
    persona = decide_persona(question)
    if persona == "quiz":
        return generate_quiz(question)
    elif persona == "community":
        return create_discussion(question)
    elif persona == "librarian":
        return recommend_materials(question)
    else:
        return teacher_response(question, history=history or [])

if __name__ == "__main__":
    hist = []
    while True:
        q = input("\nYou: ")
        if q.lower() == "exit":
            break
        ans = run_agent(q, hist)
        print("\nAgent:", ans)
        hist.append({"role": "user", "content": q})
        hist.append({"role": "assistant", "content": ans})
