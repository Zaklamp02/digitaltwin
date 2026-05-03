# PRD: Obsidian Vault as Knowledge Source of Truth

**Status**: Draft  
**Date**: 2026-05-03  
**Author**: Sebastiaan den Boer  

---

## 1. Problem

The current admin UI for editing knowledge (node CRUD, edge management, document uploads, memory chat) is functional but clunky. Content editing happens through web forms that don't match the experience of a proper writing tool. Meanwhile, the underlying data is already markdown with graph relationships — a structure that maps 1:1 to an Obsidian vault.

## 2. Vision

Replace the content-editing surface with a local Obsidian vault that syncs to the NAS. A one-way sync pipeline reads the vault and builds the SQLite + ChromaDB stores that power the website and API. The admin dashboard retains all website-management features (stats, config, roles, sessions, eval) but loses its content-editing capabilities.

Inspired by Karpathy's "LLM Wiki" pattern: the vault can also serve as a surface for LLM-assisted knowledge management — ingesting sources, compiling summaries, cross-referencing, and linting for quality.

## 3. Architecture

```
┌──────────────────────────────────┐
│         Obsidian Vault           │  ← Source of truth. You edit here.
│  ~/ObsidianVault/digital-twin/  │
│                                  │
│  _system.md                      │  → System prompt
│  _config.md                      │  → Welcome msg, chips, translation prompt
│  work/                           │  → Career, projects, skills, community
│  personal/                       │  → Personality, family, opinions
│  education/                      │  → Certifications, training
│  hobbies/                        │  → Side projects
│  documents/                      │  → PDFs, uploaded files
│  inbox/                          │  → Quick notes (Karpathy pattern)
│  sources/                        │  → Raw clipped articles, references
└─────────────┬────────────────────┘
              │
              │  Obsidian Sync / Syncthing / rsync cron
              ▼
┌──────────────────────────────────┐
│         NAS / Server             │
│  /volume1/docker/digital_twin/   │
│  vault/  (synced copy)           │
└─────────────┬────────────────────┘
              │
              │  Sync pipeline (Python, triggered by cron or file watcher)
              ▼
┌──────────────────────────────────┐
│  SQLite (knowledge.db)           │  ← Derived. Rebuilt from vault.
│  ChromaDB (memory_palace)        │  ← Derived. Rebuilt from SQLite.
└─────────────┬────────────────────┘
              │
              ▼
┌──────────────────────────────────┐
│  FastAPI + Website               │  ← Read-only consumers of the DB
│  Admin dashboard (stripped)      │
└──────────────────────────────────┘
```

## 4. Vault Structure

### 4.1 File ↔ Node mapping

Each `.md` file in the vault becomes one node in SQLite. The node ID is derived from the relative path (e.g. `work/youwe.md` → `work--youwe`).

### 4.2 Frontmatter schema

Every `.md` file uses YAML frontmatter to declare its metadata:

```yaml
---
type: job                           # node type (required)
roles: [public, work]               # access tiers (default: [public])
featured: true                      # optional, default: false
icon: "💼"                          # optional, for notebook roots
order: 1                            # optional, display ordering
tags: [ai, engineering]             # optional, for categorization
---
```

**Safe default**: if `roles` is omitted, the node defaults to `[public]`. This prevents accidental exposure of private content — a missing frontmatter field never grants more access than `public`.

### 4.3 Edges via frontmatter

Relationships between nodes are declared in frontmatter:

```yaml
---
type: project
roles: [public, work]
links:
  built_at: "[[youwe]]"              # single link
  uses: ["[[python]]", "[[react]]"]  # multiple links
  relates_to: ["[[pricing-engine]]"]
---
```

The sync pipeline resolves `[[wikilinks]]` to node IDs by matching filenames. Unresolvable links are logged as warnings.

Containment edges (`has`, `includes`, `nb_page`) are inferred from the folder structure — a file inside `work/` is automatically a child of the `work` notebook node. Explicit frontmatter `links` are for cross-cutting relationships only.

### 4.4 Special files

| File | Purpose |
|---|---|
| `_system.md` | System prompt (body text, no frontmatter needed) |
| `_config.md` | Website runtime config in frontmatter: `welcome_message`, `suggestion_chips[]`, `translation_prompt` |
| `inbox/*.md` | Quick capture notes, processed by LLM or manually filed into proper folders |

### 4.5 Documents & attachments

Binary files (PDFs, images) live in a `documents/` or `assets/` folder. A companion `.md` file can reference them:

```yaml
---
type: document
roles: [work]
file: "documents/cv-2026.pdf"
---
Summary of the document content here (manually written or LLM-extracted).
```

The sync pipeline copies referenced binaries to `data/documents/` on the server.

## 5. Sync Pipeline

### 5.1 Trigger

**Cron job** running every 5 minutes on the NAS. Rationale: you make frequent notes throughout the day, and a short cron interval means changes appear on the website within minutes without the complexity of a file watcher daemon. The cron job skips if no files changed (based on directory mtime or git status).

### 5.2 Pipeline steps

```
1. Detect changes    → compare vault file mtimes vs last sync timestamp
                       (or: git diff --name-only HEAD~1 if vault is git-tracked)

2. Parse vault       → for each .md file:
                       - extract YAML frontmatter (type, roles, links, etc.)
                       - body = everything after frontmatter
                       - resolve [[wikilinks]] in frontmatter links → node IDs
                       - infer containment edges from folder hierarchy

3. Diff against DB   → compare parsed nodes/edges with current SQLite state
                       - new files      → INSERT node + edges
                       - changed files  → UPDATE node body/metadata, re-derive edges
                       - deleted files  → DELETE node + edges (or soft-delete/archive)

4. Apply settings    → read _config.md frontmatter → update settings table
                       read _system.md body → update _system node

5. Sync translations → seed/update translation rows for changed node titles
                       mark changed translations as stale for auto-re-translation

6. Copy binaries     → rsync referenced documents/assets to data/documents/

7. Reindex changed   → for each changed/new node: chunk + embed → ChromaDB upsert
                       for each deleted node: remove chunks from ChromaDB

8. Record sync       → write sync timestamp + summary to sync log
```

### 5.3 Conflict resolution

One-way sync means **the vault always wins**. If someone edits the DB directly (shouldn't happen), those changes are overwritten on next sync. The admin UI becomes read-only for content.

### 5.4 Incremental vs full reindex

- **Normal sync**: only re-embed changed nodes (saves API calls / compute)
- **Full reindex**: CLI flag `--full` to rebuild everything (for schema changes, embedding model changes, etc.)
- **Startup**: no longer does a full reindex by default — only if the sync pipeline hasn't run or if explicitly requested

## 6. Admin Dashboard Changes

### 6.1 Remove (content-editing → Obsidian)

| Feature | Replacement |
|---|---|
| Node CRUD (create, edit, delete) | Edit `.md` files in Obsidian |
| Edge CRUD | Frontmatter `links:` + folder hierarchy |
| Notebook tree/sidebar editor | Obsidian folder structure |
| Document upload/attach/detach | Drop files in vault `documents/` folder |
| Memory chat (AI node management) | LLM tools operating on the vault directly |
| Orphan node detection | Obsidian graph view + lint command |
| Featured toggle | Frontmatter `featured: true` |
| Cross-links panel | Obsidian backlinks pane |

### 6.2 Keep (website-management)

- Overview / stats dashboard
- Request logs viewer
- LLM/RAG/TTS/STT config
- Roles & token management
- Active sessions
- Eval runs & comparison
- Graph visualization (read-only)
- Translation table & auto-translate

### 6.3 Keep with modification

| Feature | Change |
|---|---|
| Welcome message | Read-only display (source: `_config.md`), or editable with "override vault" warning |
| System prompt | Read-only display (source: `_system.md`) |
| Suggestion chips | Read-only display (source: `_config.md`) |
| Sync status | **New**: show last sync time, file count, any warnings/errors from last sync run |

## 7. Karpathy-Inspired Features (Future)

These are not required for the initial migration but are natural extensions once the vault is the source of truth:

### 7.1 Inbox processing

An `inbox/` folder for quick captures. Periodically, an LLM reads inbox notes and either:
- Files them into the correct folder with proper frontmatter
- Merges them into existing nodes
- Creates new nodes

### 7.2 Source ingestion

A `sources/` folder for raw clipped articles (via Obsidian Web Clipper). An LLM command compiles source material into wiki-style summaries, cross-referenced with existing knowledge.

### 7.3 Vault linting

A CLI command that runs LLM health checks:
- Find nodes with missing/inconsistent frontmatter
- Detect broken `[[wikilinks]]`
- Find orphan nodes (not linked from anywhere)
- Suggest missing connections between related nodes
- Flag stale content

### 7.4 Knowledge compilation

For topics with many sources, an LLM can generate synthesized overview pages that summarize and cross-reference multiple nodes — turning raw knowledge into structured understanding.

## 8. Migration Plan

### Phase 1: Export current DB → vault (one-time)

1. Script to export all SQLite nodes as `.md` files with frontmatter
2. Convert edges to frontmatter `links:` entries
3. Reconstruct folder hierarchy from notebook containment tree
4. Copy `data/documents/*` to vault `documents/` folder
5. Export settings to `_config.md`
6. Validate: round-trip test (export → parse → compare with DB)

### Phase 2: Build sync pipeline

1. Vault parser (frontmatter + wikilink resolution + folder hierarchy → nodes + edges)
2. Diff engine (compare parsed vault state vs SQLite)
3. SQLite writer (upsert nodes, reconcile edges, update settings)
4. Incremental ChromaDB indexer (only re-embed changed nodes)
5. Binary file sync
6. CLI entry point with `--full` flag
7. Cron setup on NAS

### Phase 3: Strip admin UI

1. Remove content-editing API endpoints (or make them return 405)
2. Remove content-editing frontend components
3. Add sync status panel to admin dashboard
4. Add "read-only" indicators on content views
5. Update system prompt / welcome message views to show source file path

### Phase 4: Obsidian setup

1. Configure vault with recommended folder structure
2. Set up NAS sync (Syncthing or rsync cron from local machine → NAS)
3. Install useful Obsidian plugins:
   - **Dataview** — query nodes by frontmatter fields
   - **Templater** — templates for new nodes with pre-filled frontmatter
   - **Git** — version control for the vault
   - **Web Clipper** — save articles as sources
4. Create node templates (job, project, skill, document, etc.)

## 9. Vault ↔ SQLite Field Mapping

| Vault (Obsidian) | SQLite (nodes table) | Notes |
|---|---|---|
| Relative path | `id` (with `/` → `--`) | `work/youwe.md` → `work--youwe` |
| Filename (without `.md`) | `title` | Can be overridden with frontmatter `title:` |
| Markdown body | `body` | Everything after frontmatter |
| Frontmatter `type` | `type` | Required; defaults to `document` if missing |
| Frontmatter `roles` | `roles` (JSON array) | Defaults to `["public"]` |
| Frontmatter `featured`, `icon`, `order`, etc. | `metadata` (JSON) | Merged into metadata object |
| Frontmatter `links` | `edges` table | Each key = edge type, values = target node IDs |
| Folder hierarchy | `edges` table (containment) | Parent folder `.md` or folder name → `nb_page` / `has` edge |
| File mtime | `updated_at` | |
| File creation time | `created_at` | Or frontmatter `created:` override |

## 10. Risk & Mitigations

| Risk | Mitigation |
|---|---|
| Accidental exposure of private content | Safe default: missing `roles` = `["public"]` only. Lint command warns on files without explicit roles. |
| Broken wikilinks after rename | Obsidian auto-updates wikilinks on rename. Sync pipeline logs unresolved links. |
| Sync lag (up to 5 min) | Acceptable for a personal knowledge base. CLI manual trigger available for immediate sync. |
| Large binary files bloating vault | `documents/` excluded from git. Synced separately via rsync. |
| Data loss from one-way sync | Vault is git-tracked. DB is derived and reconstructable. Regular NAS backups. |
| Obsidian plugin ecosystem churn | Core system depends only on vanilla markdown + frontmatter. Plugins are nice-to-have. |

## 11. Success Criteria

- [ ] All existing knowledge graph content is editable exclusively through Obsidian
- [ ] Changes in the vault appear on the website within 5 minutes
- [ ] No content-editing capabilities remain in the admin dashboard
- [ ] Full DB can be reconstructed from vault at any time (`sync --full`)
- [ ] Access control (roles/tiers) works correctly with frontmatter defaults
- [ ] Zero data loss during migration (validated by round-trip test)

## 12. Out of Scope (for now)

- Two-way sync (website → vault)
- LLM-assisted inbox processing / source compilation / vault linting
- Obsidian mobile setup
- Multi-user vault editing
- Real-time sync (WebSocket file watcher)
