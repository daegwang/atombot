from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from .memory import MemoryStore
from .skills import SkillsLoader
from .tools import TOOLS, LocalTools
from ..provider.provider import LLMProvider

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "AGENTS.md"

def _load_rules(primary: Path, fallback: Path) -> str:
    for p in (primary, fallback):
        try: text = p.read_text(encoding="utf-8").strip()
        except OSError: continue
        if text: return text
    raise RuntimeError(f"Missing or unreadable prompt file: {primary} (fallback: {fallback})")

class Agent:
    def __init__(self, workspace: Path, llm: LLMProvider):
        self.workspace, self.llm = workspace, llm
        self.memory, self.skills = MemoryStore(workspace), SkillsLoader(workspace)
        self.tools = LocalTools(workspace)
        self.workspace_prompt_path = (workspace / "AGENTS.md").resolve()
        self.skill_summary = "; ".join(f"{n}: {str((self.skills.get_skill_metadata(n) or {}).get('description', '')).strip() or 'no description'}" for n in (s["name"] for s in self.skills.list_skills()))
        self.skills_text = self.skills.load_skills_for_context(self.skills.get_always_skills())
        self.recent: list[dict] = []; self.max_steps = 30

    def _build_messages(self, user_text: str, created_at_iso: str = "") -> list[dict]:
        parts = [_load_rules(self.workspace_prompt_path, PROMPT_PATH), "## Memory files\n- long-term: memory/MEMORY.md\n- history: memory/history/YYYY-MM-DD.jsonl"]
        recalled = self.memory.search_history(user_text, k=5)
        if self.skills_text: parts.append("## Skills\n" + self.skills_text)
        if (text := self.memory.read_memory().strip()): parts.append("## Long-term memory\n" + text)
        if recalled: parts.append("## Relevant history\n" + "\n\n".join(recalled))
        system = "\n\n---\n\n".join(parts) + (f"\n\n## Skill Discovery\n- available: {self.skill_summary}" if self.skill_summary else "") + (f"\n\n## Runtime\n- created_at_iso: {created_at_iso}" if created_at_iso else "")
        return [{"role": "system", "content": system}, *self.recent[-10:], {"role": "user", "content": user_text}]

    def ask(self, user_text: str, context: dict | None = None) -> str:
        created_at_iso = datetime.now().astimezone().replace(microsecond=0).isoformat()
        tool_ctx = {**(context or {}), "created_at_iso": created_at_iso}
        is_cron = bool(tool_ctx.get("is_cron"))
        self.tools.set_context(tool_ctx)
        messages = self._build_messages(f"[Scheduled Task] Timer finished.\nInstruction: {user_text.strip()}." if is_cron else user_text, created_at_iso=created_at_iso)
        final = ""

        for _ in range(self.max_steps):
            resp = self.llm.chat(messages, tools=TOOLS)
            if not resp["tool_calls"]:
                final = (resp["text"] or "").strip() or "(empty response)"
                messages.append({"role": "assistant", "content": final}); break
            messages.append({"role": "assistant", "content": resp["text"] or "", "tool_calls": [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}} for tc in resp["tool_calls"]]})
            for tc in resp["tool_calls"]:
                messages.append({"role": "tool", "tool_call_id": tc["id"], "name": tc["name"], "content": self.tools.dispatch(tc["name"], tc["arguments"])[:5000]})

        if not final: final = "I couldn't finish this in one pass (too many tool steps). Please try again with a more specific request."
        self.recent = [*self.recent, {"role": "user", "content": user_text}, {"role": "assistant", "content": final}][-10:]
        self.memory.append_turn(user_text, final)
        return final
