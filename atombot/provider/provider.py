import json, subprocess, urllib.request
from typing import Optional

def _flatten(content) -> str:
    if isinstance(content, str): return content
    if isinstance(content, list): return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and "text" in p)
    return "" if content is None else str(content)

def _args(v):
    if isinstance(v, dict): return v
    if isinstance(v, str):
        try: return json.loads(v)
        except Exception: return {"raw": v}
    return {}

def _codex_prompt(messages: list[dict], tools: Optional[list[dict]]) -> str:
    p = "\n\n".join(f"{m.get('role', 'user').upper()}:\n{_flatten(m.get('content'))}" for m in messages if isinstance(m, dict) and m.get("content")).strip()
    if not tools: return p
    defs = [{"name": (t.get("function") or {}).get("name"), "description": (t.get("function") or {}).get("description", ""), "parameters": (t.get("function") or {}).get("parameters", {})} for t in tools if isinstance(t, dict)]
    return p + ("\n\nAvailable tools (JSON):\n" + json.dumps(defs, ensure_ascii=False) + "\nReturn ONLY JSON with shape: {\"text\":\"...\",\"tool_calls\":[{\"name\":\"tool_name\",\"arguments\":{}}]}.\nWhen a tool is needed, set tool_calls; when final, set tool_calls to [] and put answer in text.")

def _codex_parse(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines(); raw = "\n".join(lines[1:-1] if len(lines) >= 2 and lines[-1].strip().startswith("```") else lines[1:]).strip()
    try: d = json.loads(raw)
    except Exception: return {"text": text or "(empty response)", "tool_calls": []}
    if not isinstance(d, dict): return {"text": text or "(empty response)", "tool_calls": []}
    t = [{"id": f"codex_{i}", "name": tc["name"], "arguments": _args(tc.get("arguments", {}))} for i, tc in enumerate(d.get("tool_calls") or [], 1) if isinstance(tc, dict) and tc.get("name")]
    return {"text": _flatten(d.get("text", "")), "tool_calls": t}

class LLMProvider:
    def __init__(self, model: str, api_key: str, base_url: str, cwd: Optional[str] = None):
        self.model, self.api_key, self.base_url = model, api_key, base_url.rstrip("/")
        self.cwd = cwd

    def _chat_codex(self, messages: list[dict], tools: Optional[list[dict]]) -> dict:
        try: p = subprocess.run(["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", _codex_prompt(messages, tools)], cwd=self.cwd, capture_output=True, text=True, timeout=300)
        except FileNotFoundError as err: raise RuntimeError("Codex CLI not found. Install and ensure `codex` is on PATH.") from err
        if p.returncode != 0: raise RuntimeError(f"Codex CLI call failed: {(p.stderr or p.stdout or '').strip() or f'exit={p.returncode}'}")
        out = (p.stdout or p.stderr or "").strip()
        return _codex_parse(out) if tools else {"text": out or "(empty response)", "tool_calls": []}

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> dict:
        if self.base_url == "codex": return self._chat_codex(messages, tools)
        body = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools: body["tools"], body["tool_choice"] = tools, "auto"
        req = urllib.request.Request(url=f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp: msg = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]
        return {"text": _flatten(msg.get("content")), "tool_calls": [{"id": x["id"], "name": x["function"]["name"], "arguments": _args(x["function"].get("arguments", "{}"))} for x in msg.get("tool_calls", [])]}
