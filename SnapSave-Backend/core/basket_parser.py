import re


def parse_basket_input(user_text):
    """
    Convert messy grocery text into a list of items.
    """

    if not user_text:
        return []

    text = user_text.lower().strip()

    # Replace common separators
    text = text.replace("\n", ",")
    text = text.replace(" and ", ",")
    text = text.replace(";", ",")

    # Remove extra spaces
    text = re.sub(r"\s+", " ", text)

    # Split items
    items = [i.strip() for i in text.split(",") if i.strip()]

    return items