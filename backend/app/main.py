"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .admin import router as admin_router
from .audio import router as audio_router
from .chat import router as chat_router
from .config import get_settings
from .knowledge import KnowledgeDB, apply_graph_customizations, migrate_from_memory, resync_seed_edges
from .logging_ import configure as configure_logging
from .providers import AnthropicProvider, LLMProvider, OllamaProvider, OpenAIProvider
from .rag import RAGRetriever, build_embedder
from .teams_webhook import router as teams_router
from .telegram_bot import TelegramBot, PublicTelegramBot
from .image_indexer import index_images_from_memory
from .translations import seed_translations, translate_stale, ensure_translations_table

log = logging.getLogger("ask-my-agent")


def _build_provider(settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY not set")
        model = settings.model_name or "claude-sonnet-4-6"
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=model)
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY not set")
        model = settings.model_name or "gpt-4o-mini"
        return OpenAIProvider(api_key=settings.openai_api_key, model=model)
    if settings.llm_provider == "ollama":
        model = settings.model_name or "llama3.2"
        return OllamaProvider(base_url=settings.ollama_base_url, model=model)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    log.info("starting ask-my-agent v%s (provider=%s, model=%s)",
             __version__, settings.llm_provider, settings.model_name)

    # Knowledge graph (SQLite) — additive migration on every startup.
    # New .md files in memory/ are picked up; existing nodes are left untouched.
    knowledge = KnowledgeDB(settings.knowledge_db_path)
    n = migrate_from_memory(settings.memory_path, knowledge)
    if n:
        log.info("memory sync: %d node(s) created or updated", n)
    # Create extra nodes/edges not backed by markdown and apply graph tweaks
    # (must run before resync_seed_edges so that notebook root nodes exist)
    _customizations_ok = True
    try:
        apply_graph_customizations(knowledge)
    except Exception as e:
        _customizations_ok = False
        log.warning("graph customizations failed (continuing): %s", e)
    # Always resync canonical seed edges (safe — only touches deterministic IDs)
    # Skip if customizations failed, to avoid deleting edges for missing nodes
    if _customizations_ok:
        try:
            resync_seed_edges(knowledge)
        except Exception as e:
            log.warning("seed edge resync failed (continuing): %s", e)
    else:
        log.warning("skipping seed edge resync because graph customizations failed")

    # Image indexing — caption any new *.png/jpg/webp in memory/ with OpenAI Vision.
    # No-op if OPENAI_API_KEY is unset or no images found.
    try:
        n_images = index_images_from_memory(knowledge, settings.memory_path, settings.openai_api_key)
        if n_images:
            log.info("image indexer: %d image node(s) created or updated", n_images)
    except Exception as e:
        log.warning("image indexing failed (continuing): %s", e)

    # Translation system — seed all translatable keys, auto-translate stale ones
    try:
        ensure_translations_table(knowledge)
        n_seed = seed_translations(knowledge)
        if n_seed:
            log.info("translations: %d key(s) seeded or marked stale", n_seed)
        n_translated = translate_stale(knowledge, settings.openai_api_key)
        if n_translated:
            log.info("translations: %d entry/entries auto-translated to Dutch", n_translated)
    except Exception as e:
        log.warning("translation sync failed (continuing): %s", e)

    embedder = build_embedder(settings)
    retriever = RAGRetriever(settings=settings, knowledge=knowledge, embedder=embedder)
    try:
        retriever.reindex_all()
    except Exception as e:
        log.warning("reindex skipped (using existing index): %s", e)

    provider = _build_provider(settings)

    app.state.knowledge = knowledge
    app.state.retriever = retriever
    app.state.provider = provider

    # Owner Telegram bot
    bot = TelegramBot(
        bot_token=settings.telegram_bot_token,
        owner_chat_id=settings.telegram_chat_id,
        retriever=retriever,
        provider=provider,
        log_path=settings.log_path,
        knowledge=knowledge,
        settings=settings,
    )
    bot_task = asyncio.create_task(bot.run())

    # Public Telegram bot (second token, open to anyone)
    public_bot = PublicTelegramBot(
        bot_token=settings.telegram_public_bot_token,
        owner_chat_id=settings.telegram_chat_id,
        retriever=retriever,
        provider=provider,
        log_path=settings.log_path,
        knowledge=knowledge,
        settings=settings,
    )
    public_bot_task = asyncio.create_task(public_bot.run())

    try:
        yield
    finally:
        bot.stop()
        public_bot.stop()
        try:
            await asyncio.wait_for(bot_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        try:
            await asyncio.wait_for(public_bot_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        knowledge.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Ask my agent", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Session-Id"],
    )

    app.include_router(chat_router)
    app.include_router(audio_router)
    app.include_router(admin_router)
    app.include_router(teams_router)

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "provider": settings.llm_provider,
            "model": settings.model_name,
            "embedding_provider": settings.embedding_provider,
        }

    return app


app = create_app()
