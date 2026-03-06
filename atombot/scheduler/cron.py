from __future__ import annotations
import json
import time
from pathlib import Path

class CronStore:
    def __init__(self, path: Path):
        self.path = path; self.jobs: list[dict] = []; self._load()

    def _load(self) -> None:
        if not self.path.exists(): self.jobs = []; return
        try:
            self.jobs = data if isinstance((data := json.loads(self.path.read_text(encoding="utf-8"))), list) else []
        except Exception: self.jobs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True); self.path.write_text(json.dumps(self.jobs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def add(self, chat_id: str, prompt: str, next_at: int, every_s: int = 0) -> str:
        self._load()
        jid = str(max([int(j.get("id", 0)) for j in self.jobs if str(j.get("id", "")).isdigit()] + [0]) + 1)
        self.jobs.append({"id": jid, "chat_id": str(chat_id), "prompt": prompt.strip(), "next_at": int(next_at), "every_s": max(0, int(every_s or 0)), "enabled": True, "created_at": int(time.time())})
        self._save(); return jid

    def list_for(self, chat_id: str | None = None) -> list[dict]:
        self._load()
        return list(self.jobs) if chat_id is None else [j for j in self.jobs if str(j.get("chat_id")) == str(chat_id)]

    def remove(self, chat_id: str | None, job_id: str) -> bool:
        self._load()
        target, before = str(job_id).strip(), len(self.jobs)
        self.jobs = [j for j in self.jobs if str(j.get("id")) != target] if chat_id is None else [j for j in self.jobs if not (str(j.get("chat_id")) == str(chat_id) and str(j.get("id")) == target)]
        if changed := (len(self.jobs) != before): self._save()
        return changed

    def due(self, now: int | None = None) -> list[dict]:
        self._load()
        return [j for j in self.jobs if j.get("enabled", True) and int(j.get("next_at", 0) or 0) <= (int(time.time()) if now is None else int(now))]

    def mark_ran(self, job_id: str, now: int | None = None) -> bool:
        self._load()
        ts = int(time.time()) if now is None else int(now)
        target = str(job_id)
        for j in self.jobs:
            if str(j.get("id")) != target: continue
            every_s = int(j.get("every_s", 0) or 0)
            j["next_at"] = ts + every_s if every_s > 0 else j.get("next_at", ts)
            if every_s <= 0: j["enabled"] = False
            self._save(); return True
        return False
