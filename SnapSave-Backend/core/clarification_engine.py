from rapidfuzz import process


def needs_clarification(match_data, threshold=0.75):
    """
    Decide whether we need to ask the user to clarify the product.
    """

    confidence = match_data.get("confidence", 0)

    if confidence < threshold:
        return True

    return False


def suggest_options(query, vocabulary, limit=4):
    """
    Suggest possible products when match confidence is low.
    """

    if not vocabulary:
        return []

    results = process.extract(query, vocabulary, limit=limit)

    suggestions = []

    for r in results:
        suggestions.append(r[0])

    return suggestions


def build_clarification_message(query, suggestions):
    """
    Create a user-friendly clarification message.
    """

    if not suggestions:
        return "Could you clarify the product?"

    message = "Which product did you mean?\n\n"

    for i, option in enumerate(suggestions, start=1):
        message += f"{i}. {option}\n"

    message += "\nType the number or product name."

    return message