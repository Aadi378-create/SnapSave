from pathlib import Path
import threading
from core.json_store import read_json,write_json

_lock=threading.RLock()
PREF_FILE=Path(__file__).resolve().parents[1]/"data/user_preferences.json"

def load_preferences():
    with _lock:
        return read_json(PREF_FILE)

def save_preferences(prefs):
    with _lock:
        write_json(PREF_FILE,prefs)

def record_selection(category,brand):
    with _lock:
        prefs=load_preferences()
        counts=prefs.setdefault(category,{})
        counts[brand]=counts.get(brand,0)+1
        save_preferences(prefs)

def get_preferences(category):
    return load_preferences().get(category,{})
