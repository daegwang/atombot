from __future__ import annotations
import json, shlex, subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from ..scheduler.cron import CronStore

def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, **({"required": required} if required else {})}}}

TOOLS = [_fn(n, d, p, r) for n, d, p, r in [
    ("read_file", "Read file", {"path": {"type": "string"}}, ["path"]),
    ("write_file", "Write file", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    ("update_memory", "Replace memory", {"content": {"type": "string"}}, ["content"]),
    ("exec", "Run shell command in workspace", {"command": {"type": "string"}, "timeout_s": {"type": "integer"}}, ["command"]),
    ("web_fetch", "Fetch URL content", {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, ["url"]),
    ("list_dir", "List directory", {"path": {"type": "string"}}, None),
    ("cron_job", "Cron add/list/remove", {"action": {"type": "string", "enum": ["add", "list", "remove"]}, "next_at": {"type": "string"}, "every_s": {"type": "integer"}, "prompt": {"type": "string"}, "id": {"type": "string"}}, ["action"]),
]]

def _to_unix(next_at: str) -> int:
    s = (next_at or "").strip()
    if not s: raise ValueError("add requires next_at (ISO datetime)")
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception: raise ValueError("next_at must be ISO datetime")

class LocalTools:
    def __init__(self, workspace: Path):
        self.workspace, self._context = workspace.resolve(), {}

    def _resolve(self, rel: str) -> Path:
        path = (self.workspace / (rel or ".")).resolve()
        if path != self.workspace and self.workspace not in path.parents: raise ValueError("Path escapes workspace")
        return path

    def set_context(self, context: dict | None) -> None: self._context = context or {}

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists(): return f"ERROR: file not found: {path}"
        if p.is_dir(): return f"ERROR: not a file: {path}"
        return p.read_text(encoding="utf-8")[:10000]

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
        return f"OK: wrote {path} ({len(content)} chars)"

    def update_memory(self, content: str) -> str:
        if not (text := (content or "").strip()): return "ERROR: content is empty"
        p = self._resolve("memory/MEMORY.md"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text + "\n", encoding="utf-8")
        return f"OK: replaced memory/MEMORY.md ({len(text)} chars)"

    def exec(self, command: str, timeout_s: int | None = None) -> str:
        if not (cmd := (command or "").strip()): return "ERROR: command is empty"
        t = max(1, min(int(timeout_s or 20), 120))
        try:
            argv = shlex.split(cmd)
        except ValueError as err:
            return f"ERROR: invalid command: {err}"
        if not argv: return "ERROR: command is empty"
        if (base := Path(argv[0]).name.lower()) in {"sudo", "su", "dd", "mkfs", "fdisk", "shutdown", "reboot", "halt", "poweroff", "chmod", "chown", "chgrp"}: return f"ERROR: blocked dangerous command: {base}"
        try:
            p = subprocess.run(argv, shell=False, cwd=str(self.workspace), capture_output=True, text=True, timeout=t)
        except subprocess.TimeoutExpired:
            return f"ERROR: command timed out after {t}s"
        out, err = (p.stdout or "").strip()[:10000], (p.stderr or "").strip()[:10000]
        return "\n".join([f"exit={p.returncode}"] + ([f"stdout:\n{out}"] if out else []) + ([f"stderr:\n{err}"] if err else []))

    def web_fetch(self, url: str, max_chars: int | None = None) -> str:
        if not (u := (url or "").strip()): return "ERROR: url is empty"
        p = urlparse(u)
        if p.scheme not in {"http", "https"} or not p.netloc: return "ERROR: url must be http/https"
        n = min(int(max_chars or 20000), 20000)
        try:
            with urlopen(Request(u, headers={"User-Agent": "atombot/1.0"}), timeout=15) as r:
                text = r.read(n * 3).decode("utf-8", errors="ignore")
        except Exception as err:
            return f"ERROR: fetch failed: {err}"
        return text[:n].strip() or "(empty content)"

    def list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.exists(): return f"ERROR: path not found: {path}"
        if p.is_file(): return p.name
        return "\n".join(rows) if (rows := [c.relative_to(self.workspace).as_posix() + ("/" if c.is_dir() else "") for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:200]]) else "(empty)"

    def cron_job(self, action: str, prompt: str = "", id: str = "", next_at: str = "", every_s: int | None = None) -> str:
        cron, act = CronStore(self._resolve("cron/cron.json")), (action or "").strip().lower()
        chat_id = str(self._context.get("chat_id") or "default")
        if act == "list": return json.dumps(j, ensure_ascii=False, indent=2) if (j := cron.list_for(chat_id)) else "[]"
        if act == "remove": return "ERROR: remove requires id" if not (target := str(id).strip()) else ("OK: reminder removed" if cron.remove(chat_id=chat_id, job_id=target) else "ERROR: job not found")
        if act != "add": return "ERROR: action must be add, list, or remove"
        if not (prompt := prompt.strip()): return "ERROR: add requires non-empty prompt"
        try: cron.add(chat_id=chat_id, prompt=prompt, next_at=_to_unix(next_at), every_s=int(every_s or 0))
        except Exception as err: return f"ERROR: {err}"
        return "OK: reminder scheduled"

    def dispatch(self, name: str, args: dict) -> str:
        try:
            m = {"read_file": lambda: self.read_file(args["path"]), "write_file": lambda: self.write_file(args["path"], args["content"]), "update_memory": lambda: self.update_memory(args["content"]), "exec": lambda: self.exec(args["command"], args.get("timeout_s")), "web_fetch": lambda: self.web_fetch(args["url"], args.get("max_chars")), "list_dir": lambda: self.list_dir(args.get("path", ".")), "cron_job": lambda: self.cron_job(args["action"], args.get("prompt", ""), args.get("id", ""), args.get("next_at"), args.get("every_s"))}.get(name)
            return m() if m else f"ERROR: unknown tool: {name}"
        except Exception as err:
            return f"ERROR: {type(err).__name__}: {err}"
