"""
Persistent student memory — level, vocabulary, weak areas, session history.
Stores per-user data in a JSON file.
"""
import json
import threading
from datetime import datetime
from pathlib import Path


class StudentMemory:
    """Simple JSON-backed student progress tracker."""

    def __init__(self, data_path: str):
        self._path = Path(data_path)
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    def _load(self):
        if self._path.exists():
            with open(self._path) as f:
                self._data = json.load(f)

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, user_id: str) -> dict:
        """Get or create student profile."""
        with self._lock:
            if user_id not in self._data:
                self._data[user_id] = {
                    "level": "A1",
                    "weak_areas": [],
                    "vocabulary": [],
                    "session_count": 0,
                    "last_session": None,
                    "topics_covered": [],
                    "mistakes": [],
                    "strengths": [],
                    "notes": "",
                }
                self._save()
            return self._data[user_id]

    def update(self, user_id: str, updates: dict):
        """Merge updates into student profile."""
        with self._lock:
            profile = self.get(user_id)
            profile.update(updates)
            profile["last_session"] = datetime.now().isoformat()
            self._data[user_id] = profile
            self._save()

    def record_session(self, user_id: str):
        """Increment session count."""
        with self._lock:
            profile = self.get(user_id)
            profile["session_count"] += 1
            profile["last_session"] = datetime.now().isoformat()
            self._data[user_id] = profile
            self._save()

    def add_vocabulary(self, user_id: str, words: list[str]):
        """Add new words to tracked vocabulary."""
        with self._lock:
            profile = self.get(user_id)
            for w in words:
                w = w.lower().strip()
                if w not in profile["vocabulary"]:
                    profile["vocabulary"].append(w)
            self._data[user_id] = profile
            self._save()

    def add_weak_area(self, user_id: str, area: str):
        """Mark a grammar/topic as a weak area."""
        with self._lock:
            profile = self.get(user_id)
            if area not in profile["weak_areas"]:
                profile["weak_areas"].append(area)
            self._data[user_id] = profile
            self._save()

    def summary(self, user_id: str) -> str:
        """Return a readable progress summary."""
        p = self.get(user_id)
        return (
            f"Level: {p['level']}\n"
            f"Sessions: {p['session_count']}\n"
            f"Weak areas: {', '.join(p['weak_areas']) or 'None tracked yet'}\n"
            f"Vocabulary tracked: {len(p['vocabulary'])} words\n"
            f"Topics: {', '.join(p['topics_covered'][:10]) or 'None yet'}"
        )
