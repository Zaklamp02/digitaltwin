"""Translation system — managed UI/node translations with LLM auto-fill.

Provides a translations table in the knowledge DB, admin CRUD,
and a background task that auto-translates stale entries via OpenAI.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from .knowledge import KnowledgeDB

log = logging.getLogger("ask-my-agent.translations")

# ── static UI strings (English ground truth) ──────────────────────────────────
# Keys prefixed with "ui." are static interface elements.
# Keys prefixed with "chat." are welcome/chip/template strings.
# Keys prefixed with "about." are about-section strings.
# Keys prefixed with "node." are auto-generated from the knowledge graph.

UI_STRINGS: dict[str, str] = {
    # Navigation / menu
    "ui.blog": "Blog",
    "ui.projects": "Projects",
    "ui.about": "About",
    "ui.linkedin": "LinkedIn",
    "ui.github": "GitHub",
    "ui.email": "Email",
    "ui.about_arrow": "About ↓",

    # Settings
    "ui.light_mode": "Light mode",
    "ui.dark_mode": "Dark mode",
    "ui.switch_to_english": "Switch to English",
    "ui.switch_to_dutch": "Switch to Dutch",
    "ui.speak_replies": "Speak replies",
    "ui.voice": "Voice",
    "ui.clear_conversation": "Clear conversation",

    # Chat
    "ui.ask_placeholder": "Ask about Sebastiaan…",
    "ui.ask_anything": "Ask me anything!",
    "ui.conversation_ended": "Conversation ended.",
    "ui.new_conversation": "New conversation",
    "ui.session_end_message": "That's the end of this session. Start a new one to keep chatting.",
    "ui.thinking": "Thinking…",
    "ui.transcribing": "Transcribing…",
    "ui.stop_recording": "Stop recording",
    "ui.speak_question": "Speak your question",
    "ui.recording": "recording",
    "ui.scroll_for_more": "scroll for more",
    "ui.play": "▶︎ play",
    "ui.copy": "⎘ copy",
    "ui.copied": "✓ copied",
    "ui.send": "Send",
    "ui.back_to_home": "Back to home",
    "ui.settings": "Settings",
    "ui.tell_me_about": "Tell me about",

    # Hero / about
    "ui.subtitle": "Creative adventurer. Nerd with MBA.",

    # About section
    "about.heading": "About",
    "about.hi": "Hi, I'm Sebastiaan",
    "about.p1": "Director of Data Science & AI by day, compulsive builder by night. I lead teams that turn messy data into decisions that actually matter — from fraud detection to supply chain optimisation.",
    "about.p2": "When I'm not wrangling models, I'm building furniture from scratch (full kitchen, done), running (slowly), or hosting overly competitive board game nights.",
    "about.p3_prefix": "This site is my digital twin — an AI agent trained on my professional and personal knowledge. Ask",
    "about.p3_suffix": "anything, or explore the mind map above.",
    "about.footer": "Built with too many Docker containers",

    # Blog/Projects section headers
    "ui.the_curiosa": "The Curiosa",
    "ui.projects_heading": "Projects",
    "ui.more_posts_coming": "More posts coming soon",

    # Chat welcome + chips (backend-configured but we provide fallback translations)
    "chat.welcome": "Hey! I'm Sebastiaan's digital twin. Ask me about my experience, projects, or how I think about AI.",
    "chat.chip.career_arc": "Career arc",
    "chat.chip.career_arc_text": "Give me a quick summary of your career arc.",
    "chat.chip.side_projects": "Side projects",
    "chat.chip.side_projects_text": "What are your most interesting side projects?",
    "chat.chip.ai_perspective": "AI perspective",
    "chat.chip.ai_perspective_text": "How do you think about AI and its role?",
    "chat.chip.tech_stack": "Tech stack",
    "chat.chip.tech_stack_text": "What's your preferred tech stack and why?",
}

_DEFAULT_TRANSLATION_PROMPT = """You are a professional translator for a personal portfolio/digital-twin website.
The site belongs to Sebastiaan den Boer, a Director of Data Science & AI based in the Netherlands.
The site features:
- A knowledge graph / mind map of his career, projects, skills, education, hobbies
- An AI chatbot (his "digital twin") that visitors can ask questions
- Blog posts, project showcases, and an about section

Translate the following English UI strings to Dutch (Nederlands).
Keep translations natural, concise, and appropriate for a professional tech portfolio.
Use informal "je/jij" (not "u") for a friendly tone.
Preserve any special characters like ↓, ▶︎, ⎘, ✓ etc.
For tech terms that are commonly kept in English in Dutch contexts (e.g. "AI", "Tech Stack"), keep them in English.
For proper nouns and names, keep them as-is.

Return a JSON object mapping the keys to their Dutch translations.
Only return the JSON, no other text.

Strings to translate:
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── DB schema extension ──────────────────────────────────────────────────────

def ensure_translations_table(db: KnowledgeDB) -> None:
    """Create the translations table if it doesn't exist."""
    with db._lock, db._conn:
        db._conn.executescript("""
            CREATE TABLE IF NOT EXISTS translations (
                key         TEXT PRIMARY KEY,
                source_en   TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                text_nl     TEXT,
                is_manual   INTEGER DEFAULT 0,
                stale       INTEGER DEFAULT 1,
                updated_at  TEXT NOT NULL
            );
        """)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def seed_translations(db: KnowledgeDB) -> int:
    """Seed/sync all translatable keys. Returns count of new or stale-marked rows."""
    ensure_translations_table(db)
    now = datetime.now(timezone.utc).isoformat()
    changed = 0

    # 1. Static UI strings
    for key, en_text in UI_STRINGS.items():
        changed += _upsert_translation(db, key, en_text, now)

    # 2. Node titles from knowledge graph
    nodes = db.list_nodes()
    for node in nodes:
        if node.type == "system":
            continue  # don't translate system prompt title
        key = f"node.{node.id}"
        changed += _upsert_translation(db, key, node.title, now)

    # 3. Clean up orphaned node translations
    _cleanup_orphaned_nodes(db, {n.id for n in nodes if n.type != "system"})

    return changed


def _upsert_translation(db: KnowledgeDB, key: str, en_text: str, now: str) -> int:
    """Insert or update a translation row. Returns 1 if changed, 0 otherwise."""
    h = _sha(en_text)
    with db._lock, db._conn:
        existing = db._conn.execute(
            "SELECT source_hash, is_manual FROM translations WHERE key = ?", (key,)
        ).fetchone()

        if existing is None:
            # New key
            db._conn.execute(
                "INSERT INTO translations (key, source_en, source_hash, text_nl, is_manual, stale, updated_at) "
                "VALUES (?, ?, ?, NULL, 0, 1, ?)",
                (key, en_text, h, now),
            )
            return 1

        if existing["source_hash"] != h:
            # Source changed — mark stale, clear manual flag
            db._conn.execute(
                "UPDATE translations SET source_en = ?, source_hash = ?, stale = 1, is_manual = 0, updated_at = ? "
                "WHERE key = ?",
                (en_text, h, now, key),
            )
            return 1

    return 0


def _cleanup_orphaned_nodes(db: KnowledgeDB, valid_node_ids: set[str]) -> None:
    """Remove translation rows for deleted nodes."""
    with db._lock, db._conn:
        rows = db._conn.execute(
            "SELECT key FROM translations WHERE key LIKE 'node.%'"
        ).fetchall()
        for row in rows:
            node_id = row["key"].removeprefix("node.")
            if node_id not in valid_node_ids:
                db._conn.execute("DELETE FROM translations WHERE key = ?", (row["key"],))


def get_all_translations(db: KnowledgeDB) -> list[dict[str, Any]]:
    """Return all translation rows for the admin UI."""
    ensure_translations_table(db)
    with db._lock:
        rows = db._conn.execute(
            "SELECT key, source_en, text_nl, is_manual, stale, updated_at "
            "FROM translations ORDER BY key"
        ).fetchall()
    return [dict(r) for r in rows]


def get_translations_map(db: KnowledgeDB, lang: str = "nl") -> dict[str, str]:
    """Return a {key: translated_text} map for the frontend. Falls back to English."""
    if lang != "nl":
        return {}
    ensure_translations_table(db)
    with db._lock:
        rows = db._conn.execute(
            "SELECT key, source_en, text_nl FROM translations"
        ).fetchall()
    result = {}
    for r in rows:
        result[r["key"]] = r["text_nl"] if r["text_nl"] else r["source_en"]
    return result


def update_translation(db: KnowledgeDB, key: str, text_nl: str, is_manual: bool = True) -> bool:
    """Manually set a translation. Returns True if the key existed."""
    now = datetime.now(timezone.utc).isoformat()
    with db._lock, db._conn:
        cur = db._conn.execute(
            "UPDATE translations SET text_nl = ?, is_manual = ?, stale = 0, updated_at = ? WHERE key = ?",
            (text_nl, int(is_manual), now, key),
        )
    return cur.rowcount > 0


def reset_translation(db: KnowledgeDB, key: str) -> bool:
    """Reset a translation to auto-mode (mark stale, clear manual flag)."""
    now = datetime.now(timezone.utc).isoformat()
    with db._lock, db._conn:
        cur = db._conn.execute(
            "UPDATE translations SET is_manual = 0, stale = 1, text_nl = NULL, updated_at = ? WHERE key = ?",
            (now, key),
        )
    return cur.rowcount > 0


def get_translation_prompt(db: KnowledgeDB) -> str:
    """Return the current translation prompt (from settings or default)."""
    return db.get_setting("translation_prompt", _DEFAULT_TRANSLATION_PROMPT) or _DEFAULT_TRANSLATION_PROMPT


def set_translation_prompt(db: KnowledgeDB, prompt: str) -> None:
    """Save a custom translation prompt."""
    db.set_setting("translation_prompt", prompt)


def delete_translation(db: KnowledgeDB, key: str) -> bool:
    """Delete a translation row."""
    with db._lock, db._conn:
        cur = db._conn.execute("DELETE FROM translations WHERE key = ?", (key,))
    return cur.rowcount > 0


# ── LLM translation ──────────────────────────────────────────────────────────

def translate_stale(db: KnowledgeDB, openai_api_key: str, model: str = "gpt-4.1") -> int:
    """Translate all stale (non-manual) entries using OpenAI. Returns count translated."""
    if not openai_api_key:
        log.warning("No OpenAI API key — skipping auto-translation")
        return 0

    ensure_translations_table(db)

    with db._lock:
        rows = db._conn.execute(
            "SELECT key, source_en FROM translations WHERE stale = 1 AND is_manual = 0"
        ).fetchall()

    if not rows:
        return 0

    stale = {r["key"]: r["source_en"] for r in rows}
    log.info("Translating %d stale entries to Dutch", len(stale))

    prompt = get_translation_prompt(db)

    # Build the prompt with the strings to translate
    strings_block = json.dumps(stale, indent=2, ensure_ascii=False)
    full_prompt = prompt + "\n" + strings_block

    try:
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": full_prompt},
            ],
            temperature=0.3,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        translations = json.loads(content)
    except Exception:
        log.exception("LLM translation failed")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    translated = 0
    with db._lock, db._conn:
        for key, nl_text in translations.items():
            if key in stale and nl_text:
                db._conn.execute(
                    "UPDATE translations SET text_nl = ?, stale = 0, updated_at = ? "
                    "WHERE key = ? AND is_manual = 0",
                    (nl_text, now, key),
                )
                translated += 1

    log.info("Auto-translated %d/%d entries", translated, len(stale))
    return translated


def translate_single(db: KnowledgeDB, key: str, openai_api_key: str, model: str = "gpt-4.1") -> str | None:
    """Translate a single key using OpenAI. Returns the translation or None."""
    if not openai_api_key:
        return None

    ensure_translations_table(db)

    with db._lock:
        row = db._conn.execute(
            "SELECT source_en FROM translations WHERE key = ?", (key,)
        ).fetchone()

    if not row:
        return None

    prompt = get_translation_prompt(db)
    strings_block = json.dumps({key: row["source_en"]}, ensure_ascii=False)
    full_prompt = prompt + "\n" + strings_block

    try:
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.3,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        translations = json.loads(content)
        nl_text = translations.get(key)
        if nl_text:
            now = datetime.now(timezone.utc).isoformat()
            with db._lock, db._conn:
                db._conn.execute(
                    "UPDATE translations SET text_nl = ?, stale = 0, updated_at = ? "
                    "WHERE key = ? AND is_manual = 0",
                    (nl_text, now, key),
                )
            return nl_text
    except Exception:
        log.exception("Single translation failed for key=%s", key)

    return None
