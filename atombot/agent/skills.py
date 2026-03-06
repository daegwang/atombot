from __future__ import annotations

import re
from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

class SkillsLoader:
    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace_skills, self.builtin_skills = workspace / "skills", (builtin_skills_dir or BUILTIN_SKILLS_DIR)

    def list_skills(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []; seen: set[str] = set()
        for root in (self.workspace_skills, self.builtin_skills):
            if not root.exists(): continue
            for d in root.iterdir():
                if not d.is_dir() or d.name in seen: continue
                p = d / "SKILL.md"
                if p.exists(): out.append({"name": d.name, "path": str(p)}); seen.add(d.name)
        return out

    def load_skill(self, name: str) -> str | None:
        for root in (self.workspace_skills, self.builtin_skills):
            p = root / name / "SKILL.md"
            if p.exists(): return p.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, names: list[str]) -> str: return "\n\n---\n\n".join(f"### Skill: {n}\n\n{self._strip_frontmatter(c)}" for n in names if (c := self.load_skill(n)))

    def get_always_skills(self) -> list[str]:
        return [s["name"] for s in self.list_skills() if str((self.get_skill_metadata(s["name"]) or {}).get("always", "")).strip().lower() in {"1", "true", "yes", "on"}]

    def get_skill_metadata(self, name: str) -> dict | None:
        if not (c := self.load_skill(name)) or not (m := re.match(r"^---\n(.*?)\n---", c, re.DOTALL)): return None
        return {k.strip(): v.strip().strip('"\'') for line in m.group(1).split("\n") if ":" in line for k, v in [line.split(":", 1)]}

    @staticmethod
    def _strip_frontmatter(c: str) -> str:
        if c.startswith("---") and (m := re.match(r"^---\n.*?\n---\n?", c, re.DOTALL)): return c[m.end() :].strip()
        return c
