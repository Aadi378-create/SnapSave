import json
import os

PREF_FILE = "data/user_preferences.json"


def load_preferences():

    if not os.path.exists(PREF_FILE):
        return {}

    with open(PREF_FILE, "r") as f:
        return json.load(f)


def save_preferences(prefs):

    with open(PREF_FILE, "w") as f:
        json.dump(prefs, f, indent=2)


def record_selection(category, brand):

    prefs = load_preferences()

    if category not in prefs:
        prefs[category] = {}

    if brand not in prefs[category]:
        prefs[category][brand] = 0

    prefs[category][brand] += 1

    save_preferences(prefs)


def get_preferences(category):

    prefs = load_preferences()

    return prefs.get(category, {})