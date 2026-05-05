"""Telegram bot — owner-only memory-palace query interface.

Runs inside the FastAPI asyncio event loop via manual Application start/stop.
Only responds to the chat ID configured in TELEGRAM_CHAT_ID.

Commands
--------
/start | /help   — show available commands
/reset           — clear conversation history (starts fresh context)
/stats           — knowledge-graph node/edge counts
/sessions        — active public sessions
/whoasked        — last 5 first-turn visitor messages
/reload          — force re-index all memory files without restart
/config          — show current LLM provider, model, and RAG settings
(any text)       — query the memory palace (full personal-tier access)
(voice message)  — transcribed via Whisper then queried as text
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .providers import LLMProvider, Message
from .rag import RAGRetriever

log = logging.getLogger("ask-my-agent.telegram")

_MAX_HISTORY_TURNS = 20        # per-side turns kept for context
_TELEGRAM_CHAR_LIMIT = 4096    # Telegram hard limit per message
_AMS = ZoneInfo("Europe/Amsterdam")

# Directories to look for image/document files at runtime (in container)
_PUBLIC_DIR = Path("/app/public")
_DATA_DIR   = Path("/app/data")

# Regex to find markdown image tags: ![alt text](/path/to/image.ext)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((/[^\)]+)\)")
# Regex to find markdown links to documents: [text](/path/to/file.pdf)
_MD_DOC_RE   = re.compile(r"\[([^\]]+)\]\((/[^\)]+\.(?:pdf|docx|xlsx|csv|zip))\)")


# ── helpers ──────────────────────────────────────────────────────────────────

def _split_message(text: str) -> list[str]:
    """Split a long string into ≤4096-char pieces at paragraph or line breaks."""
    if len(text) <= _TELEGRAM_CHAR_LIMIT:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= _TELEGRAM_CHAR_LIMIT:
            parts.append(text)
            break
        cut = text.rfind("\n\n", 0, _TELEGRAM_CHAR_LIMIT)
        if cut == -1:
            cut = text.rfind("\n", 0, _TELEGRAM_CHAR_LIMIT)
        if cut == -1:
            cut = _TELEGRAM_CHAR_LIMIT
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts


def _resolve_media_path(url_path: str) -> Path | None:
    """Try to locate a file referenced by a URL path inside container volumes."""
    # Strip leading slash
    rel = url_path.lstrip("/")
    candidates = [
        _PUBLIC_DIR / rel,             # /app/public/avatar_sebastiaan.png
        _DATA_DIR / rel,               # /app/data/documents/...
        _DATA_DIR / "documents" / rel, # /app/data/documents/filename
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


# ── bot class ─────────────────────────────────────────────────────────────────

class TelegramBot:
    """Embeddable async Telegram bot for owner-only memory palace access."""

    def __init__(
        self,
        *,
        bot_token: str,
        owner_chat_id: str,
        retriever: RAGRetriever,
        provider: LLMProvider,
        log_path: Path,
        knowledge: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self._token = bot_token
        self._owner_id: int = int(owner_chat_id) if owner_chat_id else 0
        self._retriever = retriever
        self._provider = provider
        self._log_path = log_path
        self._knowledge = knowledge
        self._settings = settings

        # Per-owner conversation history (list of Message alternating user/assistant)
        self._history: list[Message] = []

        self._stop_event = asyncio.Event()
        self._app: Application | None = None
        # Turn counter — incremented on each query to track conversation depth
        self._turn: int = 0

    # ── helpers ───────────────────────────────────────────────────────────────

    def _log_turn(
        self, user_message: str, response: str, latency_ms: int, *, error: str | None = None
    ) -> None:
        """Append a NDJSON entry to the shared log_path so the admin log viewer shows it."""
        self._turn += 1
        now = datetime.now(tz=_AMS)
        entry: dict[str, Any] = {
            "event": "chat" if not error else "chat_error",
            "session_id": f"telegram-{self._owner_id}",
            "tier": "personal",
            "channel": "telegram",
            "turn": self._turn,
            "ts": now.astimezone(timezone.utc).isoformat(),
            "timestamp": now.isoformat(),
            "user_message": user_message,
            "response_text": response,
            "response_chars": len(response),
            "latency_ms": latency_ms,
        }
        if error:
            entry["error"] = error
        try:
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to write telegram log: %s", exc)

    def _docs_for_chunks(self, chunks: list) -> list[tuple[str, Path, str]]:
        """Return (title, path) pairs for any retrieved nodes that have document attachments.

        Role checking has already happened at retrieval time — every chunk in `chunks`
        was returned because the caller's roles matched.  We simply look up whether the
        node that produced the chunk has a `file_path` in its metadata.
        """
        if self._knowledge is None:
            return []
        seen: set[str] = set()
        result: list[tuple[str, Path, str]] = []
        for chunk in chunks:
            if not chunk.file.startswith("node:"):
                continue
            node_id = chunk.file[len("node:"):]
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self._knowledge.get_node(node_id)
            if node is None:
                continue
            meta: dict = node.metadata if isinstance(node.metadata, dict) else json.loads(node.metadata or "{}")
            fp: str = meta.get("file_path", "")
            if not fp:
                continue
            file_path = _DATA_DIR / fp
            if file_path.exists() and file_path.is_file():
                display_name: str = meta.get("original_filename") or file_path.name
                result.append((node.title, file_path, display_name))
        return result

    # ── security ─────────────────────────────────────────────────────────────

    def _is_owner(self, update: Update) -> bool:
        return bool(update.effective_chat and update.effective_chat.id == self._owner_id)

    async def _guard(self, update: Update) -> bool:
        """Return True if caller is the owner; otherwise send a rejection."""
        if self._is_owner(update):
            return True
        if update.effective_message:
            await update.effective_message.reply_text(
                "This is a private interface — not authorised."
            )
        return False

    # ── command handlers ─────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.effective_message.reply_text(
            "🧠 *Memory palace*\n\n"
            "Type anything to query your knowledge base with full personal-tier access.\n"
            "Send a voice message and it will be transcribed then answered.\n\n"
            "*Commands*\n"
            "/cv — send CV PDF directly\n"
            "/photo — send profile photo\n"
            "/reset — clear conversation history\n"
            "/stats — knowledge graph node & edge counts\n"
            "/sessions — currently active public sessions\n"
            "/whoasked — last 5 visitor first messages\n"
            "/reload — re-index all memory files without restart\n"
            "/config — show current LLM & RAG settings\n"
            "/help — show this message",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._cmd_start(update, ctx)

    async def _cmd_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        self._history.clear()
        self._turn = 0
        await update.effective_message.reply_text("🧹 Conversation history cleared.")

    async def _cmd_photo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Send the profile photo directly."""
        if not await self._guard(update):
            return
        candidates = [
            _PUBLIC_DIR / "avatar_sebastiaan.png",
            _PUBLIC_DIR / "avatar_digitaltwin.png",
        ]
        photo_path = next((p for p in candidates if p.exists()), None)
        if photo_path is None:
            await update.effective_message.reply_text("⚠️ No profile photo found.")
            return
        with photo_path.open("rb") as f:
            await update.effective_message.reply_photo(
                photo=f,
                caption="📸 Sebastiaan den Boer",
            )

    async def _cmd_cv(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Send the CV PDF directly."""
        if not await self._guard(update):
            return
        if self._knowledge is None:
            await update.effective_message.reply_text("⚠️ Knowledge DB unavailable.")
            return
        node = self._knowledge.get_node("cv")
        if node is None:
            await update.effective_message.reply_text("⚠️ CV node not found in knowledge DB.")
            return
        meta: dict = node.metadata if isinstance(node.metadata, dict) else json.loads(node.metadata or "{}")
        fp: str = meta.get("file_path", "")
        if not fp:
            await update.effective_message.reply_text("⚠️ No file attached to the CV node.")
            return
        file_path = _DATA_DIR / fp
        if not file_path.exists():
            await update.effective_message.reply_text(f"⚠️ File not found at `{fp}`.")
            return
        with file_path.open("rb") as f:
            await update.effective_message.reply_document(
                document=f,
                filename="sebastiaan_den_boer_cv.pdf",
                caption="📄 Sebastiaan den Boer — CV",
            )

    async def _cmd_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        lines: list[str] = ["📊 *Knowledge graph*"]
        if self._knowledge is not None:
            try:
                lines.append(f"Nodes: {self._knowledge.node_count()}")
                lines.append(f"Edges: {self._knowledge.edge_count()}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"DB error: {exc}")
        else:
            lines.append("(knowledge DB unavailable)")
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_sessions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        from .session import store  # local to avoid circular at module level

        active = store.active_sessions()
        if not active:
            await update.effective_message.reply_text("No active sessions right now.")
            return
        emoji = {"public": "🟢", "recruiter": "🟡", "personal": "🔵"}
        lines = ["🗂 *Active sessions*"]
        for s in active[:10]:
            e = emoji.get(s.tier, "⚪")
            lines.append(f"{e} [{s.tier}] turn {s.turns} · `{s.session_id[:8]}…`")
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_whoasked(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        from .logging_ import read_recent_chats  # local import

        recent = read_recent_chats(self._log_path, n=5)
        if not recent:
            await update.effective_message.reply_text("No visitor conversations logged yet.")
            return
        emoji = {"public": "🟢", "recruiter": "🟡", "personal": "🔵"}
        lines = ["👥 *Last 5 visitor conversations*"]
        for ev in recent:
            tier = ev.get("tier", "?")
            ts = str(ev.get("ts", ""))[:16]
            # The first user message is stored in the "messages" field of the log event
            # or fall back to a generic label
            preview = str(ev.get("user_message", ""))[:70] or "(no preview)"
            if len(str(ev.get("user_message", ""))) > 70:
                preview += "…"
            e = emoji.get(tier, "⚪")
            lines.append(f"{e} [{tier}] {ts}\n  \"{preview}\"")
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_reload(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.effective_message.reply_text("🔄 Re-indexing memory files…")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._retriever.reindex_all)
            await update.effective_message.reply_text("✅ Re-index complete.")
        except Exception as exc:  # noqa: BLE001
            log.exception("telegram /reload error: %s", exc)
            await update.effective_message.reply_text(f"⚠️ Re-index failed: {exc}")

    async def _cmd_config(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        if self._settings is None:
            await update.effective_message.reply_text("⚠️ Settings unavailable.")
            return
        s = self._settings
        lines = [
            "⚙️ *Live config*",
            f"Provider: `{s.llm_provider}`",
            f"Model: `{s.model_name or '(default)'}`",
            f"Embedding: `{s.embedding_provider}` / `{s.embedding_model}`",
            f"RAG top-k: `{s.rag_top_k}`",
            f"RAG min-score: `{s.rag_min_score}`",
            f"RAG context turns: `{s.rag_context_turns}`",
            f"TTS voice: `{s.tts_voice}`",
            f"Rate-limit enabled: `{s.rate_limit_enabled}`",
        ]
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    # ── voice message handler ─────────────────────────────────────────────────

    async def _on_voice(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Transcribe an owner voice note with Whisper then answer as a normal query."""
        if not await self._guard(update):
            return
        if self._settings is None or not self._settings.openai_api_key:
            await update.effective_message.reply_text(
                "⚠️ Voice notes require OPENAI_API_KEY (Whisper)."
            )
            return

        await update.effective_chat.send_action(ChatAction.TYPING)

        # Download the voice file from Telegram.
        voice = update.effective_message.voice or update.effective_message.audio
        if voice is None:
            return
        tg_file = await ctx.bot.get_file(voice.file_id)

        try:
            from openai import AsyncOpenAI

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            await tg_file.download_to_drive(tmp_path)

            client = AsyncOpenAI(api_key=self._settings.openai_api_key)
            with tmp_path.open("rb") as f:
                resp = await client.audio.transcriptions.create(
                    model=self._settings.stt_model,
                    file=(tmp_path.name, f, "audio/ogg"),
                )
            transcript = (getattr(resp, "text", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            log.exception("voice transcription error: %s", exc)
            await update.effective_message.reply_text(f"⚠️ Transcription failed: {exc}")
            return
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

        if not transcript:
            await update.effective_message.reply_text("⚠️ Could not transcribe audio.")
            return

        # Echo transcript so the owner knows what was heard.
        await update.effective_message.reply_text(f"🎙 _{transcript}_", parse_mode=ParseMode.MARKDOWN)

        # Inject transcript as if it were a typed message and answer.
        # Build a minimal synthetic Update-like object is complex, so we call
        # the query logic directly.
        await self._query_and_reply(update, transcript)

    # ── free-text query ───────────────────────────────────────────────────────

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        user_text = (update.effective_message.text or "").strip()
        if not user_text:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        await self._query_and_reply(update, user_text)

    async def _query_and_reply(self, update: Update, user_text: str) -> None:
        """Core query logic — shared by text messages and voice note transcripts."""
        # Append user turn; trim history to stay within token budget.
        self._history.append(Message(role="user", content=user_text))
        if len(self._history) > _MAX_HISTORY_TURNS * 2:
            self._history = self._history[-(_MAX_HISTORY_TURNS * 2):]

        t0 = time.monotonic()
        try:
            # Personal tier → all roles visible.
            user_turns = [m.content for m in self._history if m.role == "user"]
            chunks = self._retriever.retrieve(
                user_turns=user_turns,
                caller_roles=["public", "recruiter", "personal"],
            )

            # Build system prompt from knowledge DB + document manifest.
            system_text = self._knowledge.get_system_prompt() or ""
            # Collect any document attachments from retrieved nodes (role-checked at retrieval time)
            retrieved_docs = self._docs_for_chunks(chunks)

            context = self._retriever.context_block(chunks)
            full_system = system_text + ("\n\n" + context if context else "")

            # Formatting instructions for clean output.
            full_system += """

FORMATTING RULES:
- Use **bold** sparingly — only for key terms or single-word emphasis. Never bold entire sentences.
- Prefer short paragraphs (2-3 sentences) for readability.
- Use bullet lists when listing items.
- Keep a conversational, natural tone."""

            # Collect streamed tokens.
            tokens: list[str] = []
            async for token, _meta in self._provider.stream(
                system=full_system,
                messages=self._history,
                max_tokens=1200,
            ):
                if token:
                    tokens.append(token)

            response = "".join(tokens).strip() or "(No response generated.)"
            self._history.append(Message(role="assistant", content=response))
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._log_turn(user_text, response, latency_ms)

            # ── Proactively send document attachments from retrieved nodes ─
            # (role check already applied by the retriever; no LLM markdown needed)
            for doc_title, doc_path, doc_filename in retrieved_docs:
                try:
                    with doc_path.open("rb") as f:
                        await update.effective_message.reply_document(
                            document=f,
                            filename=doc_filename,
                            caption=f"📎 {doc_title}",
                        )
                except Exception as doc_exc:
                    log.warning("could not send document %s: %s", doc_path, doc_exc)

            # ── Images embedded in response markdown (e.g. avatar photos) ──
            images_sent = False
            image_matches = _MD_IMAGE_RE.findall(response)
            for alt_text, img_path in image_matches:
                file_path = _resolve_media_path(img_path)
                if file_path:
                    try:
                        with file_path.open("rb") as f:
                            await update.effective_message.reply_photo(
                                photo=f,
                                caption=alt_text or None,
                            )
                        images_sent = True
                    except Exception as img_exc:
                        log.warning("could not send image %s: %s", file_path, img_exc)

            # ── Strip image markdown from text before sending ─────────────
            text_response = _MD_IMAGE_RE.sub("", response).strip()
            # If we only had an image and no meaningful text, skip the text message
            if not text_response and images_sent:
                return

            # Send reply, splitting if over Telegram's character limit.
            for part in _split_message(text_response or response):
                await update.effective_message.reply_text(part)

        except Exception as exc:  # noqa: BLE001
            log.exception("telegram bot query error: %s", exc)
            self._log_turn(user_text, "", int((time.monotonic() - t0) * 1000), error=str(exc))
            await update.effective_message.reply_text(f"⚠️ Error: {exc}")

    # ── daily digest ─────────────────────────────────────────────────────────

    async def _daily_digest(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Morning digest: yesterday's conversation stats. Scheduled at 08:00 AMS."""
        if not self._owner_id:
            return
        try:
            from collections import Counter, defaultdict
            import json

            lines: list[str] = []
            total = today_cnt = 0
            tier_counts: dict[str, int] = defaultdict(int)

            if self._log_path.exists():
                now = datetime.now(tz=_AMS)
                today_str = now.strftime("%Y-%m-%d")
                yesterday_str = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                                 .__class__.fromtimestamp(
                                     now.timestamp() - 86400, tz=_AMS
                                 ).strftime("%Y-%m-%d"))

                sessions_yesterday: set[str] = set()
                with self._log_path.open() as fh:
                    for raw_line in fh:
                        try:
                            ev = json.loads(raw_line)
                        except Exception:
                            continue
                        ts_raw = ev.get("ts") or ev.get("timestamp", "")
                        try:
                            ts = datetime.fromisoformat(ts_raw)
                        except Exception:
                            continue
                        day = ts.astimezone(_AMS).strftime("%Y-%m-%d")
                        if day == yesterday_str:
                            sid = ev.get("session_id", "?")
                            sessions_yesterday.add(sid)
                            tier_counts[ev.get("tier", "public")] += 1

                yesterday_cnt = len(sessions_yesterday)
                tier_summary = " | ".join(
                    f"{t}: {c}" for t, c in sorted(tier_counts.items())
                ) or "none"
                lines = [
                    f"☀️ *Daily digest* — {yesterday_str}",
                    f"Conversations yesterday: *{yesterday_cnt}*",
                    f"Tier breakdown: {tier_summary}",
                ]
            else:
                lines = ["☀️ *Daily digest* — no log file found."]

            await ctx.bot.send_message(
                chat_id=self._owner_id,
                text="\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("daily digest error: %s", exc)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start long-polling in the current event loop. Returns after stop() is called."""
        if not self._token:
            log.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
            return
        if not self._owner_id:
            log.warning("TELEGRAM_CHAT_ID not set — Telegram bot will not start")
            return

        self._app = Application.builder().token(self._token).build()

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("reset", self._cmd_reset))
        self._app.add_handler(CommandHandler("stats", self._cmd_stats))
        self._app.add_handler(CommandHandler("sessions", self._cmd_sessions))
        self._app.add_handler(CommandHandler("whoasked", self._cmd_whoasked))
        self._app.add_handler(CommandHandler("reload", self._cmd_reload))
        self._app.add_handler(CommandHandler("config", self._cmd_config))
        self._app.add_handler(CommandHandler("cv", self._cmd_cv))
        self._app.add_handler(CommandHandler("photo", self._cmd_photo))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        self._app.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self._on_voice)
        )

        async with self._app:
            await self._app.updater.start_polling(drop_pending_updates=True)
            await self._app.start()
            # Schedule daily digest at 08:00 Amsterdam time.
            if self._app.job_queue is not None:
                self._app.job_queue.run_daily(
                    self._daily_digest,
                    time=dtime(hour=8, minute=0, tzinfo=_AMS),
                    name="daily_digest",
                )
            log.info("Telegram bot started (owner_id=%d)", self._owner_id)
            await self._stop_event.wait()
            await self._app.updater.stop()
            await self._app.stop()
        log.info("Telegram bot stopped")

    def stop(self) -> None:
        """Signal the bot to shut down gracefully."""
        self._stop_event.set()


# ══════════════════════════════════════════════════════════════════════════════
# PublicTelegramBot — open to anyone, tier detection via /start <token>
# ══════════════════════════════════════════════════════════════════════════════

_PUBLIC_BOT_WELCOME = (
    "👋 Hi! I'm *Basbot*, Sebastiaan den Boer's digital twin.\n\n"
    "Ask me anything about Sebastiaan's career, projects, values, or views on AI.\n\n"
    "I'll answer as Sebastiaan would — honest, direct, a bit nerdy.\n\n"
    "💡 If you received an access token, send `/start <token>` to unlock more depth.\n"
    "Type /help for a quick overview."
)

_PUBLIC_BOT_HELP = (
    "🤖 *Basbot — Sebastiaan's digital twin*\n\n"
    "Just type your question and I'll answer.\n\n"
    "Commands:\n"
    "/start [token] — begin (optionally with an access token)\n"
    "/reset — clear this conversation\n"
    "/cv — download Sebastiaan's CV\n"
    "/help — show this message\n\n"
    "_Responses are generated by AI and may not be 100% accurate._"
)

_MAX_PUBLIC_TURNS = 20         # per user, per conversation
_MAX_PUBLIC_HISTORY = 20       # message pairs kept in context


class PublicTelegramBot:
    """Public-facing Telegram bot with per-user sessions and tier detection.

    Anyone can message it. Access tokens (from credentials.yaml) upgrade the
    session's tier. Owner notifications fire on first message from a new user.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        owner_chat_id: str,
        retriever: RAGRetriever,
        provider: LLMProvider,
        log_path: Path,
        knowledge: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self._token = bot_token
        self._owner_id: int = int(owner_chat_id) if owner_chat_id else 0
        self._retriever = retriever
        self._provider = provider
        self._log_path = log_path
        self._knowledge = knowledge
        self._settings = settings

        # {telegram_user_id: {"history": [...], "tier": str, "turns": int, "first_seen": bool}}
        self._sessions: dict[int, dict] = {}

        self._stop_event = asyncio.Event()
        self._app: Application | None = None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_session(self, user_id: int) -> dict:
        if user_id not in self._sessions:
            self._sessions[user_id] = {
                "history": [],
                "tier": "public",
                "roles": ["public"],
                "turns": 0,
                "notified": False,
            }
        return self._sessions[user_id]

    def _resolve_token(self, token: str) -> tuple[str, list[str]]:
        """Look up an access token and return (tier, roles). Falls back to public."""
        if self._settings is None or not token:
            return "public", ["public"]
        from .config import load_tokens
        try:
            tokens = load_tokens(self._settings.credentials_path)
            entry = tokens.get(token)
            if entry:
                tier = entry.get("tier", "public")
                from .config import _TIER_TO_ROLES
                roles = _TIER_TO_ROLES.get(tier, ["public"])
                return tier, roles
        except Exception:  # noqa: BLE001
            pass
        return "public", ["public"]

    async def _notify_owner(self, user: Any, session: dict, first_message: str) -> None:
        """Notify the owner on Telegram when a new public user starts chatting."""
        if not self._owner_id or not self._app:
            return
        tier = session["tier"]
        tier_emoji = {"public": "🟢", "work": "🟡", "personal": "🔵"}.get(tier, "⚪")
        extra = "\n🔔 <b>Work-tier access</b> — check follow-up!" if tier == "work" else ""
        name = ""
        if user:
            parts = [user.first_name or "", user.last_name or ""]
            name = " ".join(p for p in parts if p).strip()
            if user.username:
                name += f" (@{user.username})"
        msg = (
            f"{tier_emoji} <b>New public bot user</b>{extra}\n"
            f"Tier: <b>{tier}</b>\n"
            f"User: {name or '(unknown)'} [id:{getattr(user, 'id', '?')}]\n"
            f"First message: <i>{first_message[:200]}</i>"
        )
        try:
            await self._app.bot.send_message(
                chat_id=self._owner_id,
                text=msg,
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("owner notification failed: %s", exc)

    def _log_turn(
        self,
        user_id: int,
        tier: str,
        user_message: str,
        response: str,
        latency_ms: int,
        *,
        error: str | None = None,
    ) -> None:
        from datetime import datetime, timezone
        entry: dict[str, Any] = {
            "event": "chat" if not error else "chat_error",
            "session_id": f"telegram-public-{user_id}",
            "tier": tier,
            "channel": "telegram_public",
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message[:200],
            "response_chars": len(response),
            "latency_ms": latency_ms,
        }
        if error:
            entry["error"] = error
        try:
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to write public telegram log: %s", exc)

    # ── command handlers ─────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id if update.effective_user else 0
        session = self._get_session(user_id)

        # Token upgrade
        if ctx.args:
            token = ctx.args[0].strip()
            tier, roles = self._resolve_token(token)
            session["tier"] = tier
            session["roles"] = roles
            session["history"] = []
            session["turns"] = 0
            tier_label = {"public": "public", "work": "work (extended)", "personal": "personal (full)"}.get(tier, tier)
            await update.effective_message.reply_text(
                f"✅ Token accepted — you now have *{tier_label}* access. Ask away!",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        session["history"] = []
        session["turns"] = 0
        await update.effective_message.reply_text(
            _PUBLIC_BOT_WELCOME,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            _PUBLIC_BOT_HELP,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id if update.effective_user else 0
        session = self._get_session(user_id)
        session["history"] = []
        session["turns"] = 0
        await update.effective_message.reply_text("🧹 Conversation cleared. Ask me anything!")

    async def _cmd_cv(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Send CV PDF if available."""
        if self._knowledge is None:
            await update.effective_message.reply_text("⚠️ Knowledge unavailable.")
            return
        node = self._knowledge.get_node("cv")
        if node is None:
            await update.effective_message.reply_text("⚠️ CV not found.")
            return
        meta: dict = node.metadata if isinstance(node.metadata, dict) else json.loads(node.metadata or "{}")
        fp: str = meta.get("file_path", "")
        if not fp:
            await update.effective_message.reply_text("⚠️ No CV file attached.")
            return
        file_path = _DATA_DIR / fp
        if not file_path.exists():
            await update.effective_message.reply_text("⚠️ CV file not found on server.")
            return
        with file_path.open("rb") as f:
            await update.effective_message.reply_document(
                document=f,
                filename="sebastiaan_den_boer_cv.pdf",
                caption="📄 Sebastiaan den Boer — CV",
            )

    # ── free-text query ───────────────────────────────────────────────────────

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        user_id = user.id if user else 0
        session = self._get_session(user_id)
        user_text = (update.effective_message.text or "").strip()
        if not user_text:
            return

        # Soft turn cap
        if session["turns"] >= _MAX_PUBLIC_TURNS:
            await update.effective_message.reply_text(
                "You've reached the session limit for now. Send /reset to start fresh, "
                "or reach out to Sebastiaan directly via LinkedIn."
            )
            return

        await update.effective_chat.send_action(ChatAction.TYPING)

        # First-message owner notification
        if not session["notified"]:
            session["notified"] = True
            asyncio.create_task(self._notify_owner(user, session, user_text))

        session["history"].append(Message(role="user", content=user_text))
        if len(session["history"]) > _MAX_PUBLIC_HISTORY * 2:
            session["history"] = session["history"][-(_MAX_PUBLIC_HISTORY * 2):]

        t0 = time.monotonic()
        try:
            user_turns = [m.content for m in session["history"] if m.role == "user"]
            chunks = self._retriever.retrieve(
                user_turns=user_turns,
                caller_roles=session["roles"],
            )

            system_text = self._knowledge.get_system_prompt() if self._knowledge else ""
            context = self._retriever.context_block(chunks)
            full_system = (system_text or "") + ("\n\n" + context if context else "")
            # Public bot: always English unless user writes in another language
            full_system += "\n\nIMPORTANT: Match the language the user is writing in. Default to English."

            tokens: list[str] = []
            async for token, _meta in self._provider.stream(
                system=full_system,
                messages=session["history"],
                max_tokens=800,
            ):
                if token:
                    tokens.append(token)

            response = "".join(tokens).strip() or "(No response generated.)"
            session["history"].append(Message(role="assistant", content=response))
            session["turns"] += 1

            latency_ms = int((time.monotonic() - t0) * 1000)
            self._log_turn(user_id, session["tier"], user_text, response, latency_ms)

            # Strip image markdown from public response (no file serving for public)
            text_response = _MD_IMAGE_RE.sub("", response).strip()

            for part in _split_message(text_response or response):
                await update.effective_message.reply_text(part)

        except Exception as exc:  # noqa: BLE001
            log.exception("public telegram bot error: %s", exc)
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._log_turn(user_id, session["tier"], user_text, "", latency_ms, error=str(exc))
            await update.effective_message.reply_text(
                "⚠️ Something went wrong on my end. Try again in a moment."
            )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        if not self._token:
            log.info("TELEGRAM_PUBLIC_BOT_TOKEN not set — public Telegram bot disabled")
            return
        if not self._owner_id:
            log.warning("TELEGRAM_CHAT_ID not set — public bot owner notifications disabled (bot will still run)")

        self._app = Application.builder().token(self._token).build()

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("reset", self._cmd_reset))
        self._app.add_handler(CommandHandler("cv", self._cmd_cv))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        async with self._app:
            await self._app.updater.start_polling(drop_pending_updates=True)
            await self._app.start()
            log.info("Public Telegram bot started (token set)")
            await self._stop_event.wait()
            await self._app.updater.stop()
            await self._app.stop()
        log.info("Public Telegram bot stopped")

    def stop(self) -> None:
        self._stop_event.set()
