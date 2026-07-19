# elimu_ai/router.py
def decide_persona(question: str) -> str:
    text = question.lower()
    quiz_kws = ["quiz","test me","give me questions","mcq","multiple choice",
                "practice questions","practise questions","generate questions",
                "exam questions","past paper questions"]
    if any(k in text for k in quiz_kws):
        return "quiz"
    community_kws = ["forum","discussion","create a post","start a thread",
                     "community","debate","what does everyone think"]
    if any(k in text for k in community_kws):
        return "community"
    librarian_kws = ["find","get me","i need","looking for","where can i",
                     "do you have","download","recommend","notes","past paper",
                     "assessment","scheme","lesson plan","homework","booklet",
                     "materials","resources","revision","topical","send me",
                     "share","link","buy","purchase","need notes","need exam",
                     "need assessment","need scheme","need revision","need past"]
    if any(k in text for k in librarian_kws):
        return "librarian"
    return "teacher"
