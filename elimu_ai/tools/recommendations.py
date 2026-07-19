def recommend_materials(
        question
):

    answer = answer_question(
        question
    )

    link = search_elimu_library(
        question
    )

    return f"""
{answer}

📚 Recommended Resources

{link}
"""