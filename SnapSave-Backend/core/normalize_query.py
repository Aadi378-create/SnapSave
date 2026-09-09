from data.synonyms import SYNONYMS


def normalize_query(text):

    words = text.lower().split()

    normalized_words = []

    for w in words:

        if w in SYNONYMS:
            normalized_words.append(SYNONYMS[w])
        else:
            normalized_words.append(w)

    return " ".join(normalized_words)