"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.responses import RedirectResponse

from . import __version__
from .admin import router as admin_router
from .auth import cf_access_dep
from .audio import router as audio_router
from .chat import router as chat_router
from .config import get_settings
from .family_tree import export_public_family_tree
from .knowledge import KnowledgeDB
from .logging_ import configure as configure_logging
from .projection import publish_projection
from .providers import AnthropicProvider, LLMProvider, OllamaProvider, OpenAIProvider
from .rag import RAGRetriever, build_embedder
from .teams_webhook import router as teams_router
from .telegram_bot import TelegramBot, PublicTelegramBot
from .translations import seed_translations, translate_stale, ensure_translations_table
from .vault_sync import pull_vault_repo, sync_vault_to_db

log = logging.getLogger("ask-my-agent")


async def _run_startup_warmup(knowledge: KnowledgeDB, settings, retriever: RAGRetriever) -> None:
    try:
        n_translated = await asyncio.to_thread(translate_stale, knowledge, settings.openai_api_key)
        if n_translated:
            log.info("translations: %d entry/entries auto-translated to Dutch", n_translated)
    except Exception as e:
        log.warning("translation sync failed (continuing): %s", e)

    # Keep startup behavior explicit: full reindex runs only when enabled.
    if settings.app_mode != "public" and settings.reindex_on_startup:
        try:
            await asyncio.to_thread(retriever.reindex_all)
        except Exception as e:
            log.warning("reindex skipped (using existing index): %s", e)
    else:
        log.info("startup reindex disabled (app_mode=%s, reindex_on_startup=%s)", settings.app_mode, settings.reindex_on_startup)


async def _run_vault_poll_loop(knowledge: KnowledgeDB, settings, retriever: RAGRetriever) -> None:
    """Periodically pull vault git changes and sync to DB/public projection."""
    interval = max(30, int(settings.vault_git_poll_interval_seconds or 300))
    content_path = settings.content_path
    if content_path is None:
        return

    log.info("vault poll loop started (interval=%ss)", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            git_result = await asyncio.to_thread(
                pull_vault_repo,
                content_path,
                settings.vault_git_remote,
                settings.vault_git_branch,
            )
            if not git_result.get("ok"):
                log.warning(
                    "vault poll pull failed: %s",
                    git_result.get("reason") or git_result.get("stderr") or "unknown",
                )
                continue
            if not git_result.get("changed"):
                continue

            result = await asyncio.to_thread(sync_vault_to_db, content_path, knowledge, retriever)
            log.info("vault poll sync result: %s", result.get("status", "unknown"))

            should_publish = (
                settings.app_mode == "internal"
                and settings.public_projection_enabled
                and result.get("status") in {"synced", "no_changes"}
            )
            if should_publish:
                counts = await asyncio.to_thread(
                    publish_projection,
                    settings.knowledge_db_path,
                    settings.public_projection_db_path,
                    settings.public_projection_chroma_path,
                    settings,
                    settings.public_projection_role_list or ["public"],
                    settings.public_projection_reindex_on_sync,
                )
                log.info(
                    "vault poll projection publish: ok (nodes=%d, edges=%d, indexed_nodes=%d)",
                    counts.nodes,
                    counts.edges,
                    counts.indexed_nodes,
                )
                family_result = await asyncio.to_thread(
                    export_public_family_tree,
                    content_path,
                    settings.public_projection_db_path.parent / "familytree",
                )
                if family_result.get("ok"):
                    log.info(
                        "familytree publish: %s (%s)",
                        family_result.get("status"),
                        family_result.get("target"),
                    )
                else:
                    log.warning(
                        "familytree publish skipped: %s (%s)",
                        family_result.get("status"),
                        family_result.get("source"),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("vault poll loop iteration failed: %s", e)


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

    # Knowledge graph (SQLite)
    knowledge = KnowledgeDB(settings.knowledge_db_path)

    content_path = settings.content_path
    if content_path is not None:
        if not content_path.exists():
            raise RuntimeError(f"VAULT_DIR does not exist: {content_path}")

        log.info("vault sync: using %s", content_path)
        try:
            if settings.vault_git_sync_enabled and settings.vault_git_pull_on_startup:
                git_result = pull_vault_repo(
                    content_path,
                    remote=settings.vault_git_remote,
                    branch=settings.vault_git_branch,
                )
                if git_result.get("ok"):
                    log.info(
                        "vault git pull: ok (changed=%s, branch=%s)",
                        git_result.get("changed"),
                        git_result.get("git_branch"),
                    )
                else:
                    log.warning(
                        "vault git pull failed: %s",
                        git_result.get("reason") or git_result.get("stderr") or "unknown",
                    )

            result = sync_vault_to_db(content_path, knowledge)
            log.info("vault sync result: %s", result.get("status", "unknown"))

            # Internal runtime can publish a public projection automatically.
            if (
                settings.app_mode == "internal"
                and settings.public_projection_enabled
                and result.get("status") in {"synced", "no_changes"}
            ):
                try:
                    counts = publish_projection(
                        source_db_path=settings.knowledge_db_path,
                        target_db_path=settings.public_projection_db_path,
                        target_chroma_path=settings.public_projection_chroma_path,
                        settings=settings,
                        allowed_roles=settings.public_projection_role_list or ["public"],
                        reindex_vectors=settings.public_projection_reindex_on_sync,
                    )
                    log.info(
                        "public projection publish: ok (nodes=%d, edges=%d, indexed_nodes=%d, reindex_vectors=%s)",
                        counts.nodes,
                        counts.edges,
                        counts.indexed_nodes,
                        settings.public_projection_reindex_on_sync,
                    )

                    family_result = export_public_family_tree(
                        content_path,
                        settings.public_projection_db_path.parent / "familytree",
                    )
                    if family_result.get("ok"):
                        log.info(
                            "familytree publish: %s (%s)",
                            family_result.get("status"),
                            family_result.get("target"),
                        )
                    else:
                        log.warning(
                            "familytree publish skipped: %s (%s)",
                            family_result.get("status"),
                            family_result.get("source"),
                        )
                except Exception as e:
                    log.warning("public projection publish failed on startup sync: %s", e)
        except Exception as e:
            log.warning("vault sync failed (continuing with existing DB): %s", e)
    else:
        log.info("vault sync disabled: using existing knowledge DB")

    # Seed translation keys during startup, but leave the expensive auto-translate
    # and full vector reindex work for a background warmup task so the API can bind.
    try:
        ensure_translations_table(knowledge)
        n_seed = seed_translations(knowledge)
        if n_seed:
            log.info("translations: %d key(s) seeded or marked stale", n_seed)
    except Exception as e:
        log.warning("translation sync failed (continuing): %s", e)

    embedder = build_embedder(settings)
    retriever = RAGRetriever(settings=settings, knowledge=knowledge, embedder=embedder)

    provider = _build_provider(settings)

    app.state.knowledge = knowledge
    app.state.retriever = retriever
    app.state.provider = provider
    warmup_task = asyncio.create_task(_run_startup_warmup(knowledge, settings, retriever))
    vault_poll_task: asyncio.Task | None = None
    if (
        settings.app_mode == "internal"
        and settings.vault_git_sync_enabled
        and settings.vault_git_poll_enabled
        and settings.content_path is not None
    ):
        vault_poll_task = asyncio.create_task(_run_vault_poll_loop(knowledge, settings, retriever))

    bot: TelegramBot | None = None
    bot_task: asyncio.Task | None = None
    if settings.app_mode != "public":
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
        if bot is not None:
            bot.stop()
        public_bot.stop()
        if bot_task is not None:
            try:
                await asyncio.wait_for(bot_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        try:
            await asyncio.wait_for(public_bot_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        warmup_task.cancel()
        try:
            await asyncio.wait_for(warmup_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        if vault_poll_task is not None:
            vault_poll_task.cancel()
            try:
                await asyncio.wait_for(vault_poll_task, timeout=5)
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
    if settings.admin_enabled:
        if settings.require_cf_access_for_admin:
            app.include_router(admin_router, dependencies=[Depends(cf_access_dep)])
        else:
            app.include_router(admin_router)
    app.include_router(teams_router)

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "app_mode": settings.app_mode,
            "admin_enabled": settings.admin_enabled,
            "provider": settings.llm_provider,
            "model": settings.model_name,
            "embedding_provider": settings.embedding_provider,
        }

    @app.get("/familytree", include_in_schema=False)
    async def familytree():
        return RedirectResponse(url="/familytree/", status_code=307)

    @app.get("/familytree/{asset_path:path}", include_in_schema=False)
    async def familytree_asset(asset_path: str = ""):
        family_tree_root = settings.knowledge_db_path.parent / "familytree"
        if not family_tree_root.exists() or not family_tree_root.is_dir():
            raise HTTPException(status_code=404, detail="family tree not published")

        requested_path = (family_tree_root / (asset_path or "index.html")).resolve()
        root_path = family_tree_root.resolve()
        try:
            requested_path.relative_to(root_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="family tree asset not found") from exc

        if not requested_path.exists() or not requested_path.is_file():
            raise HTTPException(status_code=404, detail="family tree asset not found")

        media_type = "text/html; charset=utf-8" if requested_path.name == "index.html" else None
        return FileResponse(requested_path, media_type=media_type)

    @app.get("/api/curiosa")
    async def get_curiosa(limit: int = 10):
        """Return public microblog posts, newest first.

        Sources posts from the 'microblog' notebook in the knowledge graph:
        - Vault mode: children of the 'microblog' node via 'includes' edges.
        - Legacy mode: nodes whose ID starts with 'microblog--'.
        Posts are sorted by the 'date' metadata field (ISO YYYY-MM-DD), desc.
        """
        knowledge = app.state.knowledge

        # Collect candidates from both modes (union, deduped)
        candidate_ids: set[str] = set()

        # Vault mode: edge-based children of the 'Microblog' notebook root.
        # The vault sync uses filename stem as node ID, so Microblog/Microblog.md → "Microblog".
        # Also try lowercase "microblog" as a fallback for legacy/re-exported vaults.
        for parent_id in ("Microblog", "microblog"):
            edges = knowledge.list_edges(node_id=parent_id)
            for e in edges:
                if e.source_id == parent_id and e.type == "includes":
                    candidate_ids.add(e.target_id)

        # Legacy mode: nodes whose ID starts with 'microblog--'
        for node in knowledge.list_nodes():
            if node.id.startswith("microblog--"):
                candidate_ids.add(node.id)

        posts = []
        for nid in candidate_ids:
            node = knowledge.get_node(nid)
            if node is None:
                continue
            # Only surface publicly visible posts
            if "public" not in node.roles:
                continue
            meta = node.metadata or {}
            # Auto-generate excerpt from body if not set explicitly
            excerpt = meta.get("excerpt") or ""
            if not excerpt and node.body:
                excerpt = node.body[:220].rsplit(" ", 1)[0] + "…"
            raw_tags = meta.get("tags", [])
            tags = raw_tags if isinstance(raw_tags, list) else [raw_tags]
            posts.append({
                "id": node.id,
                "title": node.title,
                "date": meta.get("date", node.created_at[:10] if node.created_at else ""),
                "excerpt": excerpt,
                "tags": tags,
                "url": meta.get("url") or None,
            })

        posts.sort(key=lambda p: p.get("date", ""), reverse=True)
        return posts[:limit]

    return app


app = create_app()
