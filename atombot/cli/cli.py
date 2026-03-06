import asyncio
import json
import re
import subprocess
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Optional
from ..agent import Agent
from ..provider.provider import LLMProvider

APP_DIR_NAME = ".atombot"
OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_CONFIG = {"api_base": OPENAI_BASE, "model": "gpt-4o-mini", "api_key": ""}
SPEC_PROVIDERS = [
    {"name": "lmstudio", "api_base": "http://127.0.0.1:1234/v1", "probe": "http://127.0.0.1:1234/v1/models", "root": "data", "field": "id"},
    {"name": "ollama", "api_base": "http://127.0.0.1:11434/v1", "probe": "http://127.0.0.1:11434/api/tags", "root": "models", "field": "name"},
]
DETECTED_LOCAL_MODELS_MSG = "Detected local models:"
SELECT_PROMPT_TMPL = "Select model [1-{count}] (default 1): "
SELECT_PROVIDER_PROMPT_TMPL = "Select provider [1-{count}] (default 1): "
INVALID_SELECTION_MSG = "Invalid selection. Enter a number from the list."

def _pick(*values: object) -> str:
    for v in values:
        if isinstance(v, str) and v.strip(): return v.strip()
    return ""

def _section(title: str) -> None: print(f"\n=== {title} ===")
def app_home() -> Path: return (Path.home() / APP_DIR_NAME).expanduser().resolve()
def _clear_screen() -> None: print("\033[2J\033[H", end="")

def write_config(path: Path, config: dict) -> None:
    tmp = path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); tmp.replace(path)

def fetch_json(url: str, timeout: float = 1.0) -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(url=url, method="GET"), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def discover_codex_models() -> list[tuple[str, str, str]]:
    try:
        p = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=2)
        if p.returncode != 0: return []
    except Exception:
        return []
    models: set[str] = set()
    cache = (Path.home() / ".codex" / "models_cache.json").expanduser()
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            for m in data.get("models", []) if isinstance(data, dict) else []:
                if not isinstance(m, dict): continue
                slug = _pick(m.get("slug"))
                if slug: models.add(slug)
        except Exception:
            pass
    cfg = (Path.home() / ".codex" / "config.toml").expanduser()
    if cfg.exists():
        try:
            text = cfg.read_text(encoding="utf-8")
            models.update(m.strip() for m in re.findall(r'^\s*model\s*=\s*["\']([^"\']+)["\']', text, flags=re.M) if m.strip())
        except Exception:
            pass
    if not models: models.add("gpt-5")
    return [("codex", m, "codex") for m in sorted(models)]

def discover_models() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for p in SPEC_PROVIDERS:
        name, base, probe = _pick(p.get("name")), _pick(p.get("api_base")), _pick(p.get("probe"))
        root, field = _pick(p.get("root")), _pick(p.get("field"))
        if not (name and base and probe and root and field): continue
        for item in fetch_json(probe).get(root, []):
            model = _pick(item.get(field)) if isinstance(item, dict) else ""
            if model: out.append((base, model, name))
    out.extend(discover_codex_models())
    items = sorted(set(out), key=lambda x: (x[2], x[1].lower()))
    codex = sorted([x for x in items if x[2] == "codex"], key=lambda x: x[1].lower(), reverse=True)
    return [x for x in items if x[2] != "codex"] + codex

def choose_model(options: list[tuple[str, str, str]]) -> Optional[tuple[str, str]]:
    _section("Onboarding 1/2: Model Selection")
    if not options: print("No local models detected. Keeping current model settings."); return None
    grouped: dict[str, list[tuple[str, str, str]]] = {}
    for item in options: grouped.setdefault(item[2], []).append(item)
    providers = sorted(grouped.keys(), key=lambda p: (p != "codex", p))
    print("Detected providers:")
    for i, p in enumerate(providers, start=1): print(f"  [{i}] {p} ({len(grouped[p])} models)")
    print("Pick a provider number, or press Enter for default [1].")
    selected_provider = providers[0]
    while True:
        try: raw = input(SELECT_PROVIDER_PROMPT_TMPL.format(count=len(providers))).strip()
        except EOFError: print(); break
        if not raw: break
        if raw.isdigit() and 1 <= int(raw) <= len(providers): selected_provider = providers[int(raw) - 1]; break
        print(INVALID_SELECTION_MSG)
    models = grouped[selected_provider]
    print(f"\n{DETECTED_LOCAL_MODELS_MSG} ({selected_provider})")
    for i, (_, model, _) in enumerate(models, start=1): print(f"  [{i}] {model}")
    print("Pick a model number, or press Enter for default [1].")
    while True:
        try: raw = input(SELECT_PROMPT_TMPL.format(count=len(models))).strip()
        except EOFError: print(); return models[0][:2]
        if not raw: return models[0][:2]
        if raw.isdigit() and 1 <= int(raw) <= len(models): return models[int(raw) - 1][:2]
        print(INVALID_SELECTION_MSG)

def apply_onboarding_defaults(config: dict, interactive_setup: bool) -> None:
    options = discover_models(); selected = choose_model(options) if interactive_setup and options else (options[0][:2] if options else None)
    if selected:
        config["api_base"], config["model"] = selected
        config["api_key"] = _pick(config.get("api_key"), "local")

def _split_csv(raw: str) -> list[str]: return [p.lstrip("@") for p in (x.strip() for x in raw.split(",")) if p]
def _keep_channels(config: dict, channels: dict) -> None:
    if channels: config["channels"] = channels

def apply_telegram_onboarding(config: dict, interactive_setup: bool) -> None:
    channels = config.get("channels") if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    current_token = _pick(telegram.get("token"))
    current_allow = telegram.get("allow_from") if isinstance(telegram.get("allow_from"), list) else []
    if not interactive_setup: _keep_channels(config, channels); return

    _section("Onboarding 2/2: Gateway Setup")
    print("Configure Telegram now, or type 'skip' to skip for now.")
    try: raw_token = input(f"Telegram bot token [{current_token or 'YOUR_BOT_TOKEN'}]: ").strip()
    except EOFError: print(); raw_token = ""
    if raw_token.lower() == "skip": _keep_channels(config, channels); return
    token = raw_token or current_token
    if not token: print("Skipping Telegram setup: token is required."); _keep_channels(config, channels); return
    if raw_token and raw_token != current_token: print("Token updated")

    default_allow = ",".join(str(v).lstrip("@") for v in current_allow)
    try: raw_allow = input(f"Telegram allowlist CSV (ids/usernames or * ) [{default_allow or 'YOUR_TELEGRAM_USER_ID'}]: ").strip()
    except EOFError: print(); raw_allow = ""
    if raw_allow.lower() == "skip":
        if raw_token and token and current_allow:
            channels["telegram"] = {"token": token, "allow_from": [str(v).lstrip("@") for v in current_allow if str(v).strip()]}
            config["channels"] = channels; print("Allowlist unchanged; saved updated token."); return
        _keep_channels(config, channels); return

    allow = _split_csv(raw_allow) if raw_allow else [str(v).lstrip("@") for v in current_allow if str(v).strip()]
    if not allow: print("Skipping Telegram setup: allowlist is required."); _keep_channels(config, channels); return
    channels["telegram"] = {"token": token, "allow_from": allow}; config["channels"] = channels
    print("Telegram gateway settings saved.")

def _load_existing_config(path: Path) -> Optional[dict]:
    if not path.exists(): return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw: print(f"Config file is empty, regenerating: {path}"); return None
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        print(f"Invalid config JSON, regenerating: {path}")
        return None

def ensure_global_config(interactive_setup: bool = False) -> Path:
    home = app_home(); home.mkdir(parents=True, exist_ok=True)
    path = home / "config.json"
    if isinstance(_load_existing_config(path), dict): return path
    config = dict(DEFAULT_CONFIG); apply_onboarding_defaults(config, interactive_setup)
    write_config(path, config); print(f"Initialized config: {path}")
    return path

def load_config(path: Path) -> dict:
    if not path.exists(): raise RuntimeError(f"Missing config file: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict): raise RuntimeError(f"Invalid config format: {path}")
    if not _pick(loaded.get("api_base")): raise RuntimeError(f"Missing required config key: api_base ({path})")
    if not _pick(loaded.get("model")): raise RuntimeError(f"Missing required config key: model ({path})")
    return loaded

def get_secret(config: dict) -> str:
    if _pick(config.get("api_base")) == "codex": return _pick(config.get("api_key"))
    value = _pick(config.get("api_key"))
    if value: return value
    raise RuntimeError("Missing secret: api_key (set in config.json)")

def ensure_workspace_layout() -> Path:
    workspace = (app_home() / "workspace").resolve()
    for p in (workspace, workspace / "projects", workspace / "memory", workspace / "memory" / "history", workspace / "cron", workspace / "skills"):
        p.mkdir(parents=True, exist_ok=True)
    prompts = (Path(__file__).resolve().parent.parent / "prompts")
    for src_name, dst_name in (("AGENTS.md", "AGENTS.md"),):
        src, dst = prompts / src_name, workspace / dst_name
        if src.exists() and not dst.exists(): shutil.copyfile(src, dst)
    mem_src = prompts / "MEMORY.md"
    mem_dst = workspace / "memory" / "MEMORY.md"
    if mem_src.exists() and not mem_dst.exists(): shutil.copyfile(mem_src, mem_dst)
    builtin_skills = (Path(__file__).resolve().parent.parent / "skills")
    for d in builtin_skills.iterdir() if builtin_skills.exists() else []:
        src = d / "SKILL.md"
        if not d.is_dir() or not src.exists(): continue
        dst = workspace / "skills" / d.name / "SKILL.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists(): shutil.copyfile(src, dst)
    return workspace

def build_agent_from_config(config: dict) -> Agent:
    workspace = ensure_workspace_layout()
    return Agent(workspace=workspace, llm=LLMProvider(model=_pick(config.get("model")), api_key=get_secret(config), base_url=_pick(config.get("api_base")), cwd=str(workspace)))

def build_agent() -> Agent:
    interactive = len(sys.argv) == 1 and sys.stdin.isatty() and sys.stdout.isatty()
    return build_agent_from_config(load_config(ensure_global_config(interactive_setup=interactive)))

def _parse_telegram_settings(config: dict) -> tuple[bool, str, list[str]]:
    channels = config.get("channels") if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    token = _pick(telegram.get("token"))
    allow_from = [str(v).lstrip("@") for v in telegram.get("allow_from", [])] if isinstance(telegram.get("allow_from"), list) else []
    return bool(telegram), token, allow_from

def run_gateway_command() -> int:
    config = load_config(ensure_global_config(interactive_setup=False))
    enabled, token, allow_from = _parse_telegram_settings(config)
    if not enabled: print("Telegram is disabled. Add channels.telegram in ~/.atombot/config.json or run `atombot onboard`."); return 1
    if not token: print("Missing Telegram token. Set channels.telegram.token or run `atombot onboard`."); return 1
    if not allow_from: print("Missing Telegram allowlist. Set channels.telegram.allow_from to ['*'] or specific user IDs/usernames, or run `atombot onboard`."); return 1
    try: from ..channels import TelegramGateway, TelegramSettings
    except Exception as err: print(f"Telegram dependency missing: {err}"); print("Install python-telegram-bot>=22,<23"); return 1
    gateway = TelegramGateway(settings=TelegramSettings(token=token, allow_from=allow_from), agent_factory=lambda: build_agent_from_config(config), cron_path=(app_home() / "workspace" / "cron" / "cron.json"))
    print("Atombot gateway started (Telegram). Press Ctrl+C to stop.")
    try: asyncio.run(gateway.run_forever())
    except KeyboardInterrupt: print("\nAtombot gateway stopped.")
    return 0

def run_onboard_command() -> int:
    path = ensure_global_config(interactive_setup=False); config = load_config(path)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    apply_onboarding_defaults(config, interactive); apply_telegram_onboarding(config, interactive)
    ensure_workspace_layout()
    write_config(path, config); print(f"\nOnboarding completed: {path}")
    return 0

def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "onboard": run_onboard_command(); return
    if len(sys.argv) >= 2 and sys.argv[1] == "gateway": run_gateway_command(); return
    try: agent = build_agent()
    except RuntimeError as err: print(f"Config error: {err}"); print(f"Set api_key in {app_home() / 'config.json'}." ); return
    if len(sys.argv) > 1: print(agent.ask(" ".join(sys.argv[1:]))); return
    if sys.stdout.isatty(): _clear_screen()
    print("Atombot ready. Type 'exit' to quit.")
    while True:
        try: text = input("> ").strip()
        except EOFError: print(); break
        if not text: continue
        if text.lower() in {"exit", "quit"}: break
        print(agent.ask(text))

if __name__ == "__main__": main()
