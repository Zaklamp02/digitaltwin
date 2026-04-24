"""
Migration: add OneDrive / SharePoint client nodes and expand experience--youwe.

Idempotent — safe to re-run.

Run from project root:
    python backend/migrate_onedrive.py
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "knowledge.db",
    Path("/app/data/knowledge.db"),
]
DB_PATH = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

SP = "https://youweopensource.sharepoint.com/sites/AIGuildTeam/Gedeelde%20documenten/General"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Node bodies
# ─────────────────────────────────────────────────────────────────────────────

YOUWE_EXTRA_SECTIONS = """

## Propositions portfolio

*Sourced: 2026-04-24. Review: 2026-10-24.*

| Product | What it is | Reference |
|---|---|---|
| **Youwe Intelligence** | White-label AI assistant platform (RAG + agentic) for e-commerce and B2B clients | [Deck]({sp}/Propositions/Youwe%20Intelligence/Youwe_Intelligence_Deck.pptx) · [Business model]({sp}/Propositions/Youwe%20Intelligence/Youwe%20Intelligence%20-%20Business%20Model.docx) |
| **SPIDER / ACI Weave** | AI-powered product data enrichment, classification, syndication on top of PIM systems — see also `weave` node | [Preso]({sp}/Propositions/501%20Spider/Youwe%20Intelligence%20-%20SPIDER%20preso.pdf) |
| **AutoAnalyst / Co-CFO** | Agentic AI analyst for financial and operational data. "A co-CFO that works 24/7." | [Deck]({sp}/Propositions/AutoAnalyst/Proposition%20-%20AutoAnalyst.pptx) · [Co-CFO variant]({sp}/Propositions/AutoAnalyst/Proposition%20-%20Co%20CFO.pptx) |
| **Expert Systems** | AI encoding domain expertise for explainable, auditable B2B decision support | [Deck]({sp}/Propositions/ExpertSystems/Proposition%20-%20Expert%20Systems.pptx) |
| **AI Value Discovery Workshop** | Structured 1-day workshop to identify and prioritize AI use cases, with a maturity scan | [Deck]({sp}/Propositions/Workshop%20AI%20Value%20Discovery/) |
| **RealView AI** | AI interior visualization — upload a photo, get realistic renovation renders in real time. Born from the Bruynzeel engagement. | [Explainer]({sp}/Propositions/RealView%20AI/AI%20Kitchen%20Reno%20-%20Explainer.pdf) |

## Team and commercial targets

*Sourced: 2026-04-24. Review: 2026-10-24 — verify team size and targets are still current.*

- **Team size**: ~15 FTE (data scientists, ML engineers, AI consultants)
- **Revenue target 2026**: €3M projected — see `AI Yearplan 2026` knowledge node
- **Structure**: Youwe's Value Creation Division; operates as an internal "guild" balancing client delivery with proposition R&D
- **Internal AI policy**: Youwe has a formal AI usage policy → [AI Policy.docx]({sp}/Documents/AI%20Policy.docx)

→ [AI Yearplan 2026.pdf]({sp}/Documents/Yearplan%202026/) — full plan with targets and pipeline
→ [AI Strategy Q3 2025]({sp}/Documents/New%20Youwe%20Strategy%202025/Youwe%20AI%20-%20Strategy%20Q32025.pptx)
→ [Goals 2024]({sp}/Documents/Goals%20and%20Targets/Goals%202024.docx)

## External talks and lectures

*Sourced: 2026-04-24. Review: 2026-10-24 — add new events as they occur.*

Confirmed events (slide files dated in folder):

| Date | Event | Topic |
|---|---|---|
| Jun 2025 | Product Experience AI | AI for product/e-commerce |
| Jun 2025 | AIPA Groningen | AI policy and practice |
| Sep 2025 | EcomExpo London | AI in e-commerce |
| Oct 2025 | PXM event | Product Experience Management + AI |
| Oct 2025 | Farmakeur | AI for the agricultural sector |
| Nov 2025 | BunzlOne — Digitaal Brein | AI in distribution |
| Mar 2026 | Kingspan event | AI pricing and CPQ |

**Recurring lectures:** *Make.com: Manual to Massive* — AI workflow automation. Given at Hogeschool Utrecht (HU) 4+ times since Apr 2025 and at HR departments. HU keynote on AI (Jun 2025).

→ [Event slides]({sp}/Pitchdeck%20and%20Sales%20Material/Event%20slides/)
→ [Lectures folder]({sp}/Lectures/)
""".format(sp=SP)

CLIENTS_BODY = """\
# Clients

Overview of Youwe AI practice client engagements.

*Sourced: 2026-04-24. Review: 2026-07-24 — verify ⚠️ statuses.*

## Client Overview

| Client | Project | Sector | Status |
|---|---|---|---|
| Booking.com | Travel Bot / Conversational AI | Travel / OTA | Live — global production |
| Global agri-sciences (confidential) | Pricing Engine | Agriculture | Live — production |
| Illumae / IntraconnectGroup | Wellbeing Chatbot | Health & wellbeing | Pilot — internal testing (Apr 2026) |
| Chadwicks | Product Enrichment (SPIDER) | Building materials / retail | Live |
| Bruynzeel Keukens | RealView AI — kitchen visualization | Kitchen retail | ⚠️ Delivered — v2.4 shipped Jan 2025 |
| De Heus | FarmCoach — agronomic AI coaching | Agri-sciences (animal feed) | ⚠️ Active — Track 2 running (Jan 2025 kickoff) |
| Kingspan | Order Intake + AI Roadmap + CPQ | Insulation / construction | ⚠️ Active — order intake delivered; roadmap + CPQ ongoing |
| Quooker | AI Image Generation + Design Sprint | Consumer appliances | ⚠️ Active — image pipeline delivered; design sprint Feb 2026 |
| Alphatron Marine | AI Quotation Platform (CPQ) | Maritime electronics | ⚠️ POC — multiple iterations Jan–Feb 2026 |
| Symson | AutoAnalyst integration + SPIDER | Pricing SaaS | ⚠️ Delivered — first AutoAnalyst client |
| Vink Holding | AI Order Intake Agent | Building materials distribution | ⚠️ Proposed — proposal delivered, not yet started |
| Southern Housing | AI Maintenance Planning Reports | Housing association (UK) | ⚠️ Delivered — reports generated Jan 2025 |
| BAM | AI document processing (BBT division) | Construction | ⚠️ Proposal stage — not started |
| Donaldson | Product cross-reference matching AI | Industrial filtration | ⚠️ POC / data validation phase |
| Zehnder | SPIDER + data quality workstream | HVAC / climate systems | ⚠️ Active exploration / proposal |
| Kees Smit | AI sfeerbeelden + virtual try-on | Garden furniture | ⚠️ Estimation / pilot stage |
| Wilmink Group | AI strategy workshop + SPIDER | Fashion / auto parts | ⚠️ Workshop delivered; SPIDER in exploration |
| EuroImmo | AI property search UI | Real estate | ⚠️ UI POC (Aug 2025) |
| TTL | Contract parsing AI | — | ⚠️ POC delivered |
| InsingerGilissen | Churn rate prediction | Private banking | ⚠️ Estimation only — not started |
| PostNL BE | Workflow automation | Logistics | ⚠️ Early exploration — not started |
| NNZ | Youwe Intelligence pitch | Packaging distribution | ⚠️ Pitch — not started |
| CookingLife | Youwe Intelligence pitch | E-commerce | ⚠️ Pitch — not started |
| Bejo Zaden | Youwe Intelligence pitch | Seeds / agri | ⚠️ Pitch — not started |
| TerStal | AI pitch | Fashion retail | ⚠️ Pitch — not started |
| Wickey | SPIDER (product data + pricing) | Outdoor play equipment | ⚠️ Pitch — not started |
| Haier | AI product content | Consumer electronics OEM | ⚠️ Business case / proposal |
| Sunweb | AI / SPIDER estimation | Travel | ⚠️ Estimation — not started |
| Advania | AI pitch | IT services | ⚠️ Pitch — not started |
| Auping | GenAI pilot | Mattresses / beds | ⚠️ Early-stage pilot (2024) — status unclear |
| Nutricia | AI for social media content | Baby nutrition (Danone) | ⚠️ Pitch — not started |
| Howden | Contract/document AI exploration | Insurance | ⚠️ Early exploration — not started |

See individual project nodes for full details on substantive engagements.
"""

DEHEUS_BODY = f"""\
# De Heus
Global animal feed company (HQ: Netherlands, 40+ countries). Youwe's longest AI
engagement, running 2023–present across three phases.

## Background
De Heus needed to make deep agronomic knowledge accessible to farmers and field
staff through AI. Started with a POC and grew into a multi-year product.

## What was built
**2023 — RAG chatbot POC**: RAG-based chatbot on De Heus's agronomic content library.

**2024 — Interactive AI POC**: Expanded scope, richer conversational interface,
deeper integration with De Heus content systems.

**2025 — FarmCoach**: Flagship product. AI coaching platform for farmers advising
on feed optimization, crop decisions, and animal health using De Heus's proprietary
knowledge base. Track 2 kicked off January 2025.

**Parallel (2025)**: Data management strategy assessment; generative AI exploration
for product imagery.

## References
→ [FarmCoach presentation]({SP}/Clients/DeHeus/DeHeus%20-%20Farmcoach%20-%20170225.pptx)
→ [FarmCoach PVA]({SP}/Clients/DeHeus/DeHeus%20-%20Farmcoach%20PVA%20v01.docx)
→ [Track 2 kickoff]({SP}/Clients/DeHeus/DeHeus%20Farmcoach%20Track2%20-%20Kickoff%20250122.docx)
→ [Data management deck]({SP}/Clients/DeHeus/DeHeus%20-%20Datamanagement%20-%20090725.pptx)
→ [Full folder]({SP}/Clients/DeHeus/)
"""

BRUYNZEEL_BODY = f"""\
# Bruynzeel Keukens
Dutch kitchen brand. Youwe built RealView AI here — the origin of what is now a
standalone Youwe proposition.

## Background
Bruynzeel needed consumers to visualize kitchen renovations before committing.
Traditional renders were too slow and expensive. AI image generation was the approach.

## What was built
**POC (2024)**: Proved SAM 2 image segmentation + generative AI could produce
realistic kitchen renders from a single consumer photo.

**Full product — BRUSH**: Production application with front-end, backend, and a
dedicated annotation dataset for kitchen element segmentation, plus a full color
accuracy validation suite across Bruynzeel's product catalog.

**RealView AI v2.4 (Jan 2025)**: Latest major release.

The proposition was extracted as a standalone Youwe product (RealView AI) and
subsequently pitched to other kitchen and interior brands.

## References
→ [RealView AI v2.4]({SP}/Clients/Bruynzeel/RealView%20AI%20-%20v2-4%20-%20250110.pdf)
→ [Original POC]({SP}/Clients/Bruynzeel/Poc-AI-keukenrenovatie_V2%5B23%5D.pdf)
→ [Color comparison]({SP}/Clients/Bruynzeel/Bruynzeel_realview_v2-4_color_comparison.pdf)
→ [Standalone proposition]({SP}/Propositions/RealView%20AI/AI%20Kitchen%20Reno%20-%20Explainer.pdf)
→ [Full folder]({SP}/Clients/Bruynzeel/)
"""

KINGSPAN_BODY = f"""\
# Kingspan
Global insulation and building envelope company (Ireland HQ, worldwide).
Multiple AI workstreams across 2024–2026.

## What was built / proposed

**AI Roadmap**: Structured multi-year AI roadmap for Kingspan.

**Agentic Order Intake**: AI agent reading inbound sales orders (email/PDF/EDI),
extracting structured data, validating against catalog, outputting XML into Boomi
→ SAP. Multi-region (EU + UK). Key stakeholder: Antonis Karnavas (enterprise architect).

**Lead Intelligence Hackathon (Feb 2026)**: Youwe-facilitated internal hackathon
to build AI-powered lead scoring. Kingspan internal teams executing.

**CPQ / Pricing pitch (Mar 2026)**: Configure-Price-Quote AI system — Sebastiaan
presented at a Kingspan-hosted event.

## References
→ [Order Intake proposal]({SP}/Clients/Kingspan/Kingspan%20-%20Sales%20Order%20Intake%20Solution%20Proposal.pdf)
→ [Hackathon deck]({SP}/Clients/Kingspan/Hackathon_260227_AI_Lead_Intelligence_Hackathon.pptx)
→ [CPQ event deck]({SP}/Pitchdeck%20and%20Sales%20Material/Event%20slides/Event%20-%20260325%20-%20Kingspan%20CPQ.pptx)
→ [Full folder]({SP}/Clients/Kingspan/)
"""

QUOOKER_BODY = f"""\
# Quooker
Dutch manufacturer of boiling-water taps. Multi-sprint AI engagement on product
content and innovation. Key stakeholder: Anouk (marketeer).

## What was built

**AI Innovation Sprint (2024)**: Structured sprint to identify and prototype AI
use cases across marketing and product teams.

**AI image generation pipeline**: Generates and refreshes product imagery using
generative AI. Multiple product variants and team members tested.
Delivery note: scope confusion between demo artefacts and production readiness
arose — a lesson in expectation-setting early.

**AI Design Sprint (Feb 2026)**: Follow-up sprint focused on product image
optimization at scale.

**Stonly chatbot integration**: Explored embedding Quooker's knowledge base into
a Stonly-powered AI chatbot for customer support.

## References
→ [AI Innovation Sprint]({SP}/Clients/Quooker/Quooker_AI_Innovation_sprint.pdf)
→ [AI Design Sprint]({SP}/Clients/Quooker/Quooker_x_Youwe_-_AI_Design_Sprint_260225.pptx)
→ [Full folder]({SP}/Clients/Quooker/)
"""

ALPHATRON_BODY = f"""\
# Alphatron Marine
Dutch maritime electronics company (navigation systems, bridge equipment). Youwe
built an AI Quotation Platform (CPQ).

## What was built
AI assistant helping the sales team configure and price complex marine equipment
orders — using catalog data, technical specs, and compatibility rules to generate
accurate quotes faster.

Project arc:
- **Dec 2025**: Initial pitch + data assessment
- **Jan 2026**: POC v1 — proof on sample quote data
- **Jan–Feb 2026**: POC v2–v4 — iteration toward production readiness

Also includes a broader AI roadmap estimation for Alphatron's multi-year AI journey.

## References
→ [Data assessment]({SP}/Clients/Alphatron/Alphatron%20-%20Data%20Assessment.pdf)
→ [CPQ POC (latest)]({SP}/Clients/Alphatron/Alphatron_Marine_-_AI_Quotation_POC_v260206.pptx)
→ [Platform spec]({SP}/Clients/Alphatron/Alphatron%20Quote%20Intelligence%20Platform.docx)
→ [Full folder]({SP}/Clients/Alphatron/)
"""

VINK_BODY = f"""\
# Vink Holding
Dutch distributor of building and construction materials.

## What was proposed
An AI Order Intake Agent: reads inbound sales orders (email, PDF, EDI), extracts
structured order data, validates against the product catalog, and prepares for ERP
entry — eliminating manual data-entry for the sales team. Same pattern as the
Kingspan order intake engagement. Proposal delivered; not yet started.

## References
→ [Solution proposal]({SP}/Clients/Vink/Vink%20Holding%20-%20Sales%20Order%20Intake%20Solution%20Proposal.pdf)
→ [Full folder]({SP}/Clients/Vink/)
"""

SOUTHERN_HOUSING_BODY = f"""\
# Southern Housing
UK housing association. Youwe built an AI maintenance planning report generator.

## What was built
A system ingesting housing stock data (property age, condition scores, asset types)
and generating structured, prioritized maintenance planning reports automatically —
replacing a manual spreadsheet-to-report process. A working Python script and
output reports were delivered.

## References
→ [Proposal]({SP}/Clients/Southern%20Housing/Proposal%20southern%20housing%20v250128.pdf)
→ [Sample output report]({SP}/Clients/Southern%20Housing/2026%20Maintenance%20Planning%20Report.pdf)
→ [Full folder]({SP}/Clients/Southern%20Housing/)
"""

BAM_BODY = f"""\
# BAM
Royal BAM Group — Dutch construction conglomerate. Youwe explored AI-assisted
document processing for the BBT (Bouw- en Technische diensten) division:
reading and structuring construction and tendering documents at scale.
Multiple proposal versions created; not started as of 2026-04-24.

→ [Proposal]({SP}/Clients/BAM/BAM%20-%20AI%20bij%20BBT%20-%20Voorstel%20Youwe%20-%20svdb.pdf)
→ [Two-pager]({SP}/Clients/BAM/AI%20bij%20BBT%20%28two-pager%29.pdf)
"""

DONALDSON_BODY = f"""\
# Donaldson
American industrial filtration company (filters and exhaust systems). Youwe built
an AI-assisted product cross-reference matching tool: given a competitor part
number, the system identifies the equivalent Donaldson product — automating a
manual catalog lookup process. POC / data validation phase as of 2026-04-24.

→ [Full folder]({SP}/Clients/Donaldson/)
"""

ZEHNDER_BODY = f"""\
# Zehnder
Swiss-headquartered HVAC and climate systems company. Youwe explored SPIDER for
product data enrichment across Zehnder's catalog, combined with a data quality and
AI readiness assessment.

→ [Full folder]({SP}/Clients/Zehnder/)
"""

KEESSMIT_BODY = f"""\
# Kees Smit Tuinmeubelen
Dutch garden furniture retailer. Two AI workstreams explored:

1. **AI sfeerbeelden**: Generating inspirational product-in-context lifestyle images
   using generative AI — replacing expensive photography.
2. **Virtual try-on**: Consumers visualize garden furniture in their own outdoor
   space before buying.

→ [AI & Strategy deck]({SP}/Clients/Kees%20Smit/Version%203701%20Kees%20Smit%20Tuinmeubelen%20-%20AI%20%26%20Strategy.pdf)
→ [Full folder]({SP}/Clients/Kees%20Smit/)
"""

WILMINK_BODY = f"""\
# Wilmink Group
Dutch fashion and automotive/off-highway parts retailer. Two engagements:

1. **AI strategy workshop (Apr 2025)**: Mapped and prioritized AI opportunities.
   Dual-catalogue challenge: separate structures for automotive vs off-highway
   channels require different AI enrichment pipelines.
2. **SPIDER exploration**: Product data enrichment for the multi-category catalog.

→ [Workshop deck]({SP}/Clients/Wilmink%20Group/20250422%20-%20AI%20Strategy%20workshop%20-%20Wilmink.pdf)
"""

TTL_BODY = f"""\
# TTL
Youwe built an AI contract parsing system: extracting structured data (parties,
dates, obligations, key terms) from complex legal and commercial contracts to
accelerate review and reduce manual effort. POC delivered.

→ [Full folder]({SP}/Clients/TTL/ContractParsing/)
"""

SYMSON_BODY = f"""\
# Symson
Dutch pricing SaaS company. First client for the AutoAnalyst proposition.
Youwe built the AutoAnalyst integration — connecting Symson's pricing data to a
natural-language AI analyst layer — and explored SPIDER for product data enrichment.

→ [Solution architecture]({SP}/Clients/Symson/Symson%20AI%20Analyst%20-%20solution%20architecture%20-%20v20240715.pptx)
→ [Full folder]({SP}/Clients/Symson/)
"""

EUROIMMO_BODY = f"""\
# EuroImmo
Real estate company. Youwe explored an AI-powered property search and browsing
interface, including browser-based UI testing of an AI-enhanced property discovery
experience. UI POC (Aug 2025).

→ [Full folder]({SP}/Clients/EuroImmo/)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────────────────────────────────────

def run(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    print(f"Connected to {db_path}")

    # ── 1. Expand experience--youwe body ──────────────────────────────────────
    with conn:
        row = conn.execute("SELECT body FROM nodes WHERE id = 'experience--youwe'").fetchone()
        if row:
            existing_body = row["body"] or ""
            if "## Propositions portfolio" not in existing_body:
                new_body = existing_body.rstrip() + "\n" + YOUWE_EXTRA_SECTIONS
                conn.execute(
                    "UPDATE nodes SET body = ?, updated_at = ? WHERE id = 'experience--youwe'",
                    (new_body, _now()),
                )
                print("  expanded: experience--youwe (added 3 sections)")
            else:
                print("  skipped: experience--youwe already has propositions section")

    # ── 2. Replace clients node body ──────────────────────────────────────────
    with conn:
        conn.execute(
            "UPDATE nodes SET body = ?, roles = ?, updated_at = ? WHERE id = 'clients'",
            (CLIENTS_BODY, json.dumps(["public", "recruiter", "personal"]), _now()),
        )
        print("  updated: clients (full expanded table)")

    # ── 3. New project nodes ──────────────────────────────────────────────────
    new_nodes = [
        # Rich nodes
        {
            "id":    "projects--deheus",
            "type":  "project",
            "title": "De Heus — FarmCoach",
            "body":  DEHEUS_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--bruynzeel",
            "type":  "project",
            "title": "Bruynzeel — RealView AI",
            "body":  BRUYNZEEL_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--kingspan",
            "type":  "project",
            "title": "Kingspan — Order Intake & AI Roadmap",
            "body":  KINGSPAN_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--quooker",
            "type":  "project",
            "title": "Quooker — AI Image Generation",
            "body":  QUOOKER_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--alphatron",
            "type":  "project",
            "title": "Alphatron Marine — AI Quotation (CPQ)",
            "body":  ALPHATRON_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--vink",
            "type":  "project",
            "title": "Vink Holding — AI Order Intake",
            "body":  VINK_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--southern-housing",
            "type":  "project",
            "title": "Southern Housing — Maintenance Reports",
            "body":  SOUTHERN_HOUSING_BODY,
            "roles": ["public", "recruiter"],
        },
        # Medium nodes
        {
            "id":    "projects--bam",
            "type":  "project",
            "title": "BAM — AI Document Processing",
            "body":  BAM_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--donaldson",
            "type":  "project",
            "title": "Donaldson — Product Cross-Reference AI",
            "body":  DONALDSON_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--zehnder",
            "type":  "project",
            "title": "Zehnder — SPIDER & Data Quality",
            "body":  ZEHNDER_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--keessmit",
            "type":  "project",
            "title": "Kees Smit — AI Sfeerbeelden & Try-On",
            "body":  KEESSMIT_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--wilmink",
            "type":  "project",
            "title": "Wilmink Group — AI Workshop & SPIDER",
            "body":  WILMINK_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--ttl",
            "type":  "project",
            "title": "TTL — Contract Parsing AI",
            "body":  TTL_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--symson",
            "type":  "project",
            "title": "Symson — AutoAnalyst Integration",
            "body":  SYMSON_BODY,
            "roles": ["public", "recruiter"],
        },
        {
            "id":    "projects--euroimmo",
            "type":  "project",
            "title": "EuroImmo — AI Property Search",
            "body":  EUROIMMO_BODY,
            "roles": ["public", "recruiter"],
        },
    ]

    with conn:
        for n in new_nodes:
            conn.execute(
                """
                INSERT OR IGNORE INTO nodes (id, type, title, body, roles, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    n["id"], n["type"], n["title"], n["body"],
                    json.dumps(n["roles"]), _now(), _now(),
                ),
            )
            print(f"  upserted node: {n['id']!r}")

    # ── 4. Edges ──────────────────────────────────────────────────────────────
    # (source_id, target_id, type, label)
    edges = [
        # clients → includes (all new project nodes)
        ("clients", "projects--deheus",           "includes", "De Heus"),
        ("clients", "projects--bruynzeel",         "includes", "Bruynzeel"),
        ("clients", "projects--kingspan",          "includes", "Kingspan"),
        ("clients", "projects--quooker",           "includes", "Quooker"),
        ("clients", "projects--alphatron",         "includes", "Alphatron"),
        ("clients", "projects--vink",              "includes", "Vink"),
        ("clients", "projects--southern-housing",  "includes", "Southern Housing"),
        ("clients", "projects--bam",               "includes", "BAM"),
        ("clients", "projects--donaldson",         "includes", "Donaldson"),
        ("clients", "projects--zehnder",           "includes", "Zehnder"),
        ("clients", "projects--keessmit",          "includes", "Kees Smit"),
        ("clients", "projects--wilmink",           "includes", "Wilmink Group"),
        ("clients", "projects--ttl",               "includes", "TTL"),
        ("clients", "projects--symson",            "includes", "Symson"),
        ("clients", "projects--euroimmo",          "includes", "EuroImmo"),
        # experience--youwe → built (delivered projects)
        ("experience--youwe", "projects--deheus",          "built", "FarmCoach"),
        ("experience--youwe", "projects--bruynzeel",       "built", "RealView AI"),
        ("experience--youwe", "projects--kingspan",        "built", "Kingspan Order Intake"),
        ("experience--youwe", "projects--quooker",         "built", "Quooker AI Imagery"),
        ("experience--youwe", "projects--alphatron",       "built", "Alphatron CPQ"),
        ("experience--youwe", "projects--southern-housing","built", "Southern Housing Reports"),
        ("experience--youwe", "projects--symson",          "built", "AutoAnalyst for Symson"),
        # experience--youwe → includes (proposed / exploration)
        ("experience--youwe", "projects--vink",            "includes", "Vink"),
        ("experience--youwe", "projects--bam",             "includes", "BAM"),
        ("experience--youwe", "projects--donaldson",       "includes", "Donaldson"),
        ("experience--youwe", "projects--zehnder",         "includes", "Zehnder"),
        ("experience--youwe", "projects--keessmit",        "includes", "Kees Smit"),
        ("experience--youwe", "projects--wilmink",         "includes", "Wilmink"),
        ("experience--youwe", "projects--ttl",             "includes", "TTL"),
        ("experience--youwe", "projects--euroimmo",        "includes", "EuroImmo"),
    ]

    with conn:
        for src, tgt, etype, label in edges:
            conn.execute(
                """
                INSERT OR IGNORE INTO edges (id, source_id, target_id, type, label, roles, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), src, tgt, etype, label,
                 json.dumps(["public", "recruiter", "personal"]), _now()),
            )
        print(f"  upserted {len(edges)} edges")

    print("\nDone. Re-index the knowledge base to pick up changes.")
    conn.close()


if __name__ == "__main__":
    run()
