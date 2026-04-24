"""
One-shot migration: reshape the knowledge graph.

Run from the project root (outside Docker):
    python backend/migrate_graph.py

Or inside the container:
    python /app/migrate_graph.py

The script is idempotent — safe to re-run (uses INSERT OR IGNORE for new nodes/edges,
UPDATE for renames, and skips deletes that don't exist).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Path resolution ───────────────────────────────────────────────────────────
# Works both on host (relative to project root) and inside container (/app/data/knowledge.db)
_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "knowledge.db",   # host: backend/../data/
    Path("/app/data/knowledge.db"),                            # container
]
DB_PATH = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

NOW = datetime.now(timezone.utc).isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    print(f"Connected to {db_path}")

    # ── 1. Rename nodes to shorter titles ─────────────────────────────────────
    renames = {
        "identity":               "Sebastiaan",
        "career":                 "Career",
        "personality":            "Personality",
        "education":              "Education",
        "community":              "Community",
        "faq":                    "FAQ",
        "opinions":               "Opinions",
        "stack":                  "Tech Stack",
        "hobbies":                "Hobbies",
        "images":                 "Images",
        "cv":                     "CV",
        "experience--youwe":      "Youwe",
        "experience--fiod":       "FIOD",
        "experience--philips":    "Philips",
        "experience--earlier":    "Neuroscience",
        "personal--anecdotes":    "Anecdotes",
        "personal--childhood":    "Childhood",
        "personal--philips_years":"Philips Years",
        "personal--context":      "Personal Life",
        "projects--product-platform": "Product Platform",
        "projects--travel-bot":       "Travel Bot",
        "projects--pricing-engine":   "Pricing Engine",
        "projects--dromenbrouwer":    "DromenBrouwer",
        "projects--houtenjong":       "HoutenJong",
    }

    with conn:
        for node_id, short_title in renames.items():
            conn.execute(
                "UPDATE nodes SET title = ?, updated_at = ? WHERE id = ?",
                (short_title, _now(), node_id),
            )
            print(f"  renamed: {node_id!r} → {short_title!r}")

    # ── 2. Fix hobbies type (was document, should be personal) ────────────────
    with conn:
        conn.execute(
            "UPDATE nodes SET type = 'personal', updated_at = ? WHERE id = 'hobbies'",
            (_now(),),
        )
        print("  hobbies type: document → personal")

    # ── 3. Clean up orphaned duplicate Youwe nodes ────────────────────────────
    orphaned = [
        "f12f43d5-8bd9-4061-885a-e902a6401416",
        "e711fc3a-c81f-4b0b-a6e3-b3435c2aa159",
    ]
    with conn:
        for oid in orphaned:
            cur = conn.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (oid, oid))
            rows = conn.execute("DELETE FROM nodes WHERE id = ?", (oid,)).rowcount
            if rows:
                print(f"  deleted orphaned node: {oid}")

    # ── 4. Remove wrong edges ─────────────────────────────────────────────────
    bad_edges = [
        ("experience--earlier", "projects--dromenbrouwer"),  # DromenBrouwer is a hobby/personal project
        ("experience--youwe",   "projects--houtenjong"),      # HoutenJong is a hobby project
    ]
    with conn:
        for src, tgt in bad_edges:
            cur = conn.execute(
                "DELETE FROM edges WHERE source_id = ? AND target_id = ?", (src, tgt)
            )
            if cur.rowcount:
                print(f"  removed edge: {src!r} → {tgt!r}")

    # ── 5. Split Education: create Certifications and Leadership Training nodes ─
    CERTS_BODY = """\
# Certifications

## SAFe — Scaled Agile Framework
Certified during Philips era. The Value Stream Owner title is a SAFe concept.

## Lean Six Sigma Green Belt
Certified during Philips era. Certificate status uncertain (long time ago), but the methodology is embedded in how he works.

## DAMA-DMBOK
Data management certification.

## O365 Forensics / eDiscovery
Microsoft certification, directly relevant to digital forensics work at FIOD.

## ISO 13485 — Quality Management System for Medical Devices
One-day training, Philips Eindhoven, 19 May 2017. Trainer: Peter Reijntjes (QServe Group). Certificate no. 17-1348.
"""

    TRAINING_BODY = """\
# Leadership Training

## De Baak — "Leidinggeven aan eigenwijze professionals"
Prestigious Dutch executive education institute. Focused on leading specialist and autonomous professionals.
Directly shaped leadership approach with expert teams and the broader hiring philosophy.

*De Baak is one of the Netherlands' most respected executive education providers.*
"""

    PUBLICATION_BODY = """\
# Publications

Peer-reviewed research publications by Sebastiaan den Boer.

## Journal of Cognitive Neuroscience (MSc era, Donders Institute)
**"Occipital Alpha and Gamma Oscillations Support Complementary Mechanisms for Processing Stimulus Value Associations"**
Tom R. Marshall, **Sebastiaan den Boer**, Roshan Cools, Ole Jensen, Sean James Fallon, Johanna M. Zumer.

## BMC Pregnancy and Childbirth (Philips era, 2018)
**"Evaluation of an activity monitor for use in pregnancy to help reduce excessive gestational weight gain"**
Paul M. C. Lemmens, Francesco Sartor, Lieke G. E. Cox, **Sebastiaan V. den Boer**, Joyce H. D. M. Westerink.

Context: validated whether standard consumer activity monitors accurately estimate energy expenditure in pregnant women; 40 participants, indirect calorimetry as reference.
"""

    DISC_BODY = """\
# DISC Profile

DISC personality assessment results for Sebastiaan den Boer.

*Attach the DISC report PDF via the Knowledge admin interface (node → "Attached file").*

**Overview**: Dominant / Influential primary profile. High D + I scores indicate a results-oriented leader who is also persuasive and people-motivated. Combines drive with the ability to engage and inspire.
"""

    PLDJ_BODY = """\
# PLDJ — Personal Leadership Document

Personal leadership reflection document.

*Attach the PLDJ PDF via the Knowledge admin interface (node → "Attached file").*
"""

    ISO_CERT_BODY = """\
# ISO 13485 Certificate

**ISO 13485: Quality Management System Requirements for Medical Devices**

- **Date**: 19 May 2017
- **Location**: Philips, Eindhoven
- **Trainer**: Peter Reijntjes (QServe Group)
- **Certificate no.**: 17-1348

Covers quality management systems in the context of medical device development. Relevant to Sebastiaan's work at Philips Research building validated clinical tools.
"""

    FAMILY_PUBLIC_BODY = """\
# Family

Married to **Agnes**. Together since secondary school. Three kids:
**Else**, **Roos** (nicknamed "Roos Raket"), and **Tijmen**.

Based in De Bilt, Netherlands (Utrecht area).
"""

    FAMILY_PRIVATE_BODY = """\
# Family (Private)

Married to **Agnes den Boer** (b. 4 February 1990). Together since secondary school; married **20 September 2016**.

## Children
- **Else** (b. 30 August 2017)
- **Roos** (b. 19 February 2019, nicknamed "Roos Raket")
- **Tijmen** (b. 15 April 2022)

Home: De Bilt, Emmalaan 7, 3732 GM.

Sebastiaan runs with his daughter, makes up bedtime stories for the kids (DromenBrouwer grew directly from this).
"""

    ENGAGEMENTS_BODY = """\
# Public Engagements

Structured overview of speaking engagements, conferences, and teaching.

## Conferences

| Year | Event | Role | Link |
|------|-------|------|------|
| 2024 | aiGrunn | Speaker | [Watch](https://www.youtube.com/watch?v=DmnfwWLpadc) |
| 2025 | aiGrunn | Youwe sponsor — team presentations (Erik Poolman: [local-first AI](https://www.youtube.com/watch?v=vVwr7NXBRbE); Jorn de Vreede: [ethics in AI](https://www.youtube.com/watch?v=qptQfIIAASo)) | — |
| 2026 | aiGrunn | Co-organising the business track | — |
| Sep 24, 2025 | Ecom Expo London | Keynote speaker — "Stop selling products. Start selling experiences." (The Optimisation Stage, 15:00–15:25) | — |

## Enterprise Keynotes
- **Nutricia** — enterprise AI event
- **Kingspan** — enterprise AI event

## Guest Lecturing (regular)
- University of Groningen
- Nyenrode Business University
- Hogeschool Utrecht (HU)
- Saxion

## Expert Groups
- **ShoppingTomorrow — AI in Retail** (2024)

## aiGrunn Café (bi-monthly meetup)
Co-initiated with Jeroen Bos + Berco Beute. Venue: Youwe Groningen. First edition: **5 February 2026** — 65 sign-ups + waitlist. Topics: MCP, local models, sovereign AI.
"""

    CLIENTS_BODY = """\
# Clients (Confidential)

Actual client names for Youwe AI practice reference projects.
*Personal-tier only.*

| Project | Client | Status |
|---------|--------|--------|
| Pricing Engine (€80M/year margins) | Global agri-sciences company | Live in production |
| Travel Bot | Booking.com | Live in global production |
| Wellbeing Chatbot | Illumae / Intraconnection Group | Pilot (April 2026) |
| Order Processing | Kingspan | Enterprise (EU + UK) |
| Image Enhancement | Quooker | AI product imagery |

**Note**: Public-facing materials refer to the travel marketplace and agri-sciences company anonymously.
When speaking with Sebastiaan directly, more detail on disclosure status is available.
"""

    # Build node definitions
    new_nodes = [
        {
            "id":       "certifications",
            "type":     "education",
            "title":    "Certifications",
            "body":     CERTS_BODY,
            "roles":    ["public", "recruiter"],
        },
        {
            "id":       "training",
            "type":     "education",
            "title":    "Leadership Training",
            "body":     TRAINING_BODY,
            "roles":    ["public", "recruiter"],
        },
        {
            "id":       "publication",
            "type":     "document",
            "title":    "Publications",
            "body":     PUBLICATION_BODY,
            "roles":    ["public"],
        },
        {
            "id":       "disc",
            "type":     "document",
            "title":    "DISC",
            "body":     DISC_BODY,
            "roles":    ["public", "recruiter", "personal"],
        },
        {
            "id":       "pldj",
            "type":     "document",
            "title":    "PLDJ",
            "body":     PLDJ_BODY,
            "roles":    ["public", "recruiter", "personal"],
        },
        {
            "id":       "iso-cert",
            "type":     "document",
            "title":    "ISO 13485",
            "body":     ISO_CERT_BODY,
            "roles":    ["public", "recruiter"],
        },
        {
            "id":       "family",
            "type":     "personal",
            "title":    "Family",
            "body":     FAMILY_PUBLIC_BODY,
            "roles":    ["public"],
        },
        {
            "id":       "family-personal",
            "type":     "personal",
            "title":    "Family (Private)",
            "body":     FAMILY_PRIVATE_BODY,
            "roles":    ["public", "recruiter", "personal"],
        },
        {
            "id":       "engagements",
            "type":     "community",
            "title":    "Engagements",
            "body":     ENGAGEMENTS_BODY,
            "roles":    ["public"],
        },
        {
            "id":       "clients",
            "type":     "personal",
            "title":    "Clients",
            "body":     CLIENTS_BODY,
            "roles":    ["public", "recruiter", "personal"],
        },
    ]

    with conn:
        for n in new_nodes:
            conn.execute(
                "INSERT OR IGNORE INTO nodes (id, type, title, body, metadata, roles, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    n["id"], n["type"], n["title"], n["body"],
                    "{}", json.dumps(n["roles"]),
                    _now(), _now(),
                ),
            )
            print(f"  node (insert or ignore): {n['id']!r} — {n['title']!r}")

    # ── 6. Update education node body (strip certifications) ─────────────────
    EDUCATION_BODY = """\
# Education

## Degrees
- **Executive MBA — Nyenrode Business University** (2018–2020, grade 8). Thesis: *Artificial Intelligence in Digital Forensics*.
- **MSc Cognitive Neuroscience — Donders Institute, Radboud University** (2011–2013, grade 8).
- **BSc Medical Biology — Radboud University** (2008–2011, grade 7).

Sebastiaan deliberately mixed quantitative-scientific training (neuroscience) with commercial and strategic training (MBA). The combination is what lets him operate comfortably at both executive altitude and hands-on engineering in the same day.

## Why Nyenrode
Prior career (neuroscience → Philips) was deeply academic and technical. Nyenrode was a deliberate move into business leadership, strategy, and networking. Paid for the EMBA himself: Philips declined to fund it, fearing flight risk — a concern that proved correct. **Cohort: EMBA16**, Breukelen campus.

## EMBA thesis
*"Artificial Intelligence in Digital Forensics."* Used FIOD as primary case study. Also interviewed across the Dutch law enforcement chain: Police, NFI, AIVD, NCTV, TNO. Qualitative research methodology.

## Donders Institute — MSc thesis
Thesis topic: **attentional gating** — how value associations (reward/punishment) interact with selective spatial attention in posterior neural oscillations.
MSc was hosted within the **F.C. Donders Institute**, an independent affiliated research organisation. Application was competitive and not guaranteed.
"""

    with conn:
        conn.execute(
            "UPDATE nodes SET body = ?, updated_at = ? WHERE id = 'education'",
            (EDUCATION_BODY, _now()),
        )
        print("  updated education body (stripped certifications section)")

    # ── 7. New edges ──────────────────────────────────────────────────────────
    new_edges = [
        # Identity → new hub nodes
        ("identity",        "family",               "has",         "Family",                ["public"]),
        ("identity",        "certifications",       "studied_at",  "Certifications",        ["public", "recruiter"]),
        ("identity",        "engagements",          "member_of",   "Public engagements",    ["public"]),
        ("identity",        "publication",          "authored",    "Publications",          ["public"]),

        # Family hierarchy
        ("family",          "family-personal",      "has",         "Private details",       ["public", "recruiter", "personal"]),

        # Education → certifications / training
        ("education",       "certifications",       "includes",    "Certifications",        ["public", "recruiter"]),
        ("education",       "training",             "includes",    "Leadership training",   ["public", "recruiter"]),

        # Certifications → specific cert docs
        ("certifications",  "iso-cert",             "includes",    "ISO 13485",             ["public", "recruiter"]),

        # Personality hub → FAQ / Anecdotes / DISC
        ("personality",     "faq",                  "includes",    "FAQ",                   ["public"]),
        ("personality",     "personal--anecdotes",  "includes",    "Anecdotes",             ["public", "recruiter", "personal"]),
        ("personality",     "disc",                 "describes",   "DISC profile",          ["public", "recruiter", "personal"]),
        ("personality",     "pldj",                 "describes",   "PLDJ",                  ["public", "recruiter", "personal"]),

        # Hobbies → DromenBrouwer / HoutenJong
        ("hobbies",         "projects--dromenbrouwer", "includes", "DromenBrouwer",         ["public", "recruiter"]),
        ("hobbies",         "projects--houtenjong",    "includes", "HoutenJong",            ["public", "recruiter"]),

        # Community → Engagements
        ("community",       "engagements",          "includes",    "Engagements",           ["public"]),

        # Youwe (job) → Clients (personal)
        ("experience--youwe", "clients",            "has",         "Client projects",       ["public", "recruiter", "personal"]),

        # Clients → anonymised project nodes
        ("clients",         "projects--pricing-engine",  "relates_to", "Pricing Engine",   ["public", "recruiter", "personal"]),
        ("clients",         "projects--travel-bot",      "relates_to", "Travel Bot",       ["public", "recruiter", "personal"]),
        ("clients",         "projects--product-platform","relates_to", "Product Platform", ["public", "recruiter", "personal"]),

        # Publication → identity (also from neuroscience era)
        ("experience--earlier", "publication",      "authored",    "Academic publications", ["public"]),
    ]

    with conn:
        for src, tgt, etype, label, roles in new_edges:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (id, source_id, target_id, type, label, roles, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), src, tgt, etype, label, json.dumps(roles), _now()),
                )
                print(f"  edge (insert or ignore): {src!r} → {tgt!r} [{etype}]")
            except Exception as e:
                print(f"  WARN: could not insert edge {src!r} → {tgt!r}: {e}")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    run()
