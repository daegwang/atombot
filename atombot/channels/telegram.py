from __future__ import annotations
import asyncio
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from atombot.agent import Agent
from atombot.scheduler.cron import CronStore

@dataclass
class TelegramSettings:
    token: str = ""
    allow_from: list[str] | None = None

class TelegramGateway:
    BOT_COMMANDS = [BotCommand("start", "Show startup guide"), BotCommand("new", "Reset current chat"), BotCommand("help", "List command usage")]
    TXT = {"help": "Available commands:\n/start, /new, /help", "unauth": "Unauthorized user.", "unauth_start": "You are not on the allowlist. Ask the owner to add your Telegram ID in channels.telegram.allow_from.", "start": "Atombot gateway is online.\nUse /new to start a clean session.\nUse /help to view command usage.", "new": "Started a new conversation.", "busy": "Still processing your previous message. Please wait and try again."}

    def __init__(self, settings: TelegramSettings, agent_factory: Callable[[], Agent], cron_path: Path):
        self.settings, self.agent_factory = settings, agent_factory
        self._app, self._agents, self._active, self._cron, self._cron_task = None, {}, {}, CronStore(cron_path), None
    def _allowed(self, uid, username):
        allow, sid, uname = self.settings.allow_from or [], str(uid), (username or "").lstrip("@")
        return bool(allow) and ("*" in allow or sid in allow or (uname and uname in allow))
    async def _access(self, update, denied=None):
        if not (m := update.message) or not (u := update.effective_user): return False
        if self._allowed(u.id, u.username): return True
        await m.reply_text(denied or self.TXT["unauth"]); return False
    def _agent(self, cid):
        if cid not in self._agents: self._agents[cid] = self.agent_factory()
        return self._agents[cid]
    async def _on_cmd(self, update, context, key, denied=None, reset=False):
        if not await self._access(update, denied): return
        if reset: self._agents[str(update.message.chat_id)] = self.agent_factory()
        await update.message.reply_text(self.TXT[key])
    async def _send_chunks(self, chat_id: int, text: str):
        if not self._app: return
        for chunk in _chunks(text): await self._app.bot.send_message(chat_id=chat_id, text=chunk)
    async def _ask(self, cid, prompt, is_cron=False):
        task = asyncio.create_task(asyncio.to_thread(self._agent(cid).ask, prompt, {"chat_id": cid, "is_cron": is_cron})); self._active[cid] = task
        try: return await task
        finally: self._active.pop(cid, None)
    async def run_forever(self):
        token = self.settings.token.strip()
        if not token: raise RuntimeError("Missing Telegram token")
        self._app = Application.builder().token(token).build()
        for c, kw in (("start", {"key": "start", "denied": self.TXT["unauth_start"]}), ("new", {"key": "new", "reset": True}), ("help", {"key": "help"})):
            self._app.add_handler(CommandHandler(c, partial(self._on_cmd, **kw)))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        await self._app.initialize(); await self._app.start(); await self._app.bot.set_my_commands(self.BOT_COMMANDS)
        await self._app.updater.start_polling(allowed_updates=["message"], drop_pending_updates=True)
        self._cron_task = asyncio.create_task(self._cron_loop())
        try:
            while True: await asyncio.sleep(1)
        finally: await self.shutdown()
    async def shutdown(self):
        for t in list(self._active.values()): t.cancel()
        self._active.clear(); task, self._cron_task = self._cron_task, None
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError): await task
        if self._app: await self._app.updater.stop(); await self._app.stop(); await self._app.shutdown(); self._app = None
    async def _on_message(self, update, context):
        if not update.message or not update.message.text or not await self._access(update): return
        cid, text = str(update.message.chat_id), update.message.text.strip()
        if not text: return
        if (r := self._active.get(cid)) and not r.done(): await update.message.reply_text(self.TXT["busy"]); return
        async def typing():
            while True:
                try: await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
                except Exception: pass
                await asyncio.sleep(4)
        t = asyncio.create_task(typing())
        try: result = await self._ask(cid, text)
        except asyncio.CancelledError: return
        except Exception as err: await update.message.reply_text(f"Error: {err}"); return
        finally:
            t.cancel()
            with suppress(asyncio.CancelledError): await t
        for chunk in _chunks(result): await update.message.reply_text(chunk)
    async def _cron_loop(self):
        while True:
            try:
                await asyncio.sleep(20)
                if not self._app: continue
                for job in self._cron.due():
                    cid, job_id = str(job.get("chat_id", "")), str(job.get("id", ""))
                    if not cid or not job_id: continue
                    if (r := self._active.get(cid)) and not r.done(): continue
                    prompt = str(job.get("prompt", "")).strip()
                    if not prompt: self._cron.remove(chat_id=None, job_id=job_id); continue
                    try: tg_chat_id = int(cid)
                    except Exception: self._cron.remove(chat_id=None, job_id=job_id); continue
                    try:
                        await self._send_chunks(tg_chat_id, await self._ask(cid, prompt, is_cron=True))
                    except Exception as err:
                        try: await self._send_chunks(tg_chat_id, f"error: {err}")
                        except Exception: pass
                    self._cron.mark_ran(job_id=job_id)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(1)

def _chunks(text, max_len=3900):
    text = (text or "").strip() or "(empty response)"
    if len(text) <= max_len: return [text]
    out = []
    while text:
        if len(text) <= max_len: out.append(text); break
        piece = text[:max_len]; pivot = max(piece.rfind("\n"), piece.rfind(" "))
        out.append(text[: pivot if pivot >= 0 else max_len]); text = text[pivot if pivot >= 0 else max_len :].lstrip()
    return out
