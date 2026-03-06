import json
from datetime import datetime
from pathlib import Path

class MemoryStore:
    def __init__(self, workspace: Path):
        self.dir = workspace / "memory"; self.dir.mkdir(parents=True, exist_ok=True)
        self.memory_path, self.history_dir = self.dir / "MEMORY.md", self.dir / "history"
        self.memory_path.touch(exist_ok=True); self.history_dir.mkdir(parents=True, exist_ok=True)

    def read_memory(self) -> str: return self.memory_path.read_text(encoding="utf-8")

    def append_turn(self, user_text: str, assistant_text: str) -> None:
        now = datetime.now()
        row = {"ts": now.strftime("%Y-%m-%d %H:%M"), "user": user_text.strip(), "assistant": assistant_text.strip()}
        with (self.history_dir / f"{now.strftime('%Y-%m-%d')}.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def search_history(self, query: str, k: int = 5) -> list[str]:
        needle = (query or "").strip().lower()
        if not needle: return []
        hits: list[str] = []
        for p in sorted(self.history_dir.glob("*.jsonl")):
            for raw in p.read_text(encoding="utf-8").splitlines():
                if not raw.strip(): continue
                try: row = json.loads(raw); ts, user, assistant = (str(row.get(k, "")).strip() for k in ("ts", "user", "assistant"))
                except json.JSONDecodeError: continue
                if needle in (block := f"[{ts}]\nUSER: {user}\nASSISTANT: {assistant}").lower(): hits.append(block)
        return hits[-k:][::-1]
