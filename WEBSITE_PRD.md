# sebastiaandenboer.org — Website Design PRD

**Owner:** Sebastiaan den Boer  
**Domain:** sebastiaandenboer.org  
**Status:** Ready for UX/UI design  
**Created:** 2026-04-25

---

## 1. What This Is

A personal website for Sebastiaan den Boer — Director of Data Science & AI, cognitive neuroscientist, executive MBA, woodworker, game designer, community organiser, and self-described "nerd with MBA."

The site serves a dual purpose: it's a **professional landing page** (career, CV, projects) and a **creative outlet** (microblog, opinions, side projects). The tone is informal, enthusiastic, and genuine — more like talking to the person than reading a corporate bio.

The headline feature is an **AI digital twin**: a conversational agent trained on Sebastiaan's career, projects, opinions, and personality. Visitors can literally talk to a version of him that speaks in first person and draws on a private knowledge graph. This isn't a chatbot widget — it's a genuinely useful way to learn about someone without scheduling a call.

### Design Goal

A visitor should land and feel: *"This guy is sharp, approachable, and doing interesting things — I want to know more."* The ideal outcome of every visit is that someone reaches out. The next best thing is they remember the name.

---

## 2. Who Visits & Why

### Visitor Personas

| Persona | Arrives via | Looking for | Time budget |
|---|---|---|---|
| **Recruiter / Hiring manager** | LinkedIn, email signature, CV referral | Quick career overview, downloadable CV, personality signal | 2–5 min |
| **Collaborator / client** | Referral, conference, LinkedIn | What he's built, how he thinks, whether to reach out | 5–10 min |
| **AI / data community peer** | aiGrunn, conference talk, X/Twitter | Technical opinions, project deep-dives, the microblog | 5–15 min |
| **Friend / acquaintance** | Direct share | What Sebastiaan is up to, passion projects | 1–3 min |
| **Curious stranger** | Google, forwarded digital twin link | "Who is this person?" — needs to orient in <10 seconds | <1 min |

### What They Need to Do

| # | As a… | I want to… | So that… |
|---|---|---|---|
| UC1 | Recruiter | See current role, career arc, and skills at a glance | I decide in 60 seconds if he's worth reaching out to |
| UC2 | Recruiter | Download a PDF CV | I can forward it internally |
| UC3 | Any visitor | Talk to the digital twin | I get real answers without waiting for a reply |
| UC4 | Community peer | Read opinions on AI, tech, and whatever else | I understand how he thinks, not just what he's done |
| UC5 | Anyone | Explore passion projects | I see the person beyond the job title |
| UC6 | Returning visitor | Check what's new on the microblog | I stay in the loop without subscribing |
| UC7 | Anyone on mobile | Navigate the full site comfortably | Phone experience is as good as desktop |

---

## 3. Site Identity & Personality

### Brand Essence

Sebastiaan is a **creative explorer** who happens to work in AI leadership. The site should reflect that: minimalist and clean, but with warmth and curiosity underneath. Not corporate. Not "developer portfolio dark mode with neon accent." Think: the personal site of someone who builds AI systems during the week and a reading nook for his daughter on the weekend.

### Design Principles

1. **Clean but alive** — Minimal layout, no decorative clutter, but the content itself should have energy. Enthusiastic, optimistic, direct. The Dutch "zeg wat je bedoelt" (say what you mean) attitude.

2. **The twin is the magic trick** — The digital twin should feel like the most interesting thing on the page. Not buried, not a gimmick — a genuine "wait, I can actually *talk* to this person's AI?" moment. The designer should be creative here: how do you make a conversational AI feel inviting to click on?

3. **Content over chrome** — Every element on the page earns its place. No hero banners, no parallax, no filler sections. If it doesn't help a visitor understand Sebastiaan or take an action, cut it.

4. **Dark mode is first-class** — Already implemented and user-toggled. Every design must work beautifully in both modes.

5. **Mobile-native** — Designed for phone first, scales up. The chat is already excellent on mobile; the rest of the site must match.

### Visual Foundation

| Element | Current state |
|---|---|
| Accent color | Teal-700 (`#0F766E`) — from CV |
| Font | System stack: Inter / -apple-system / Segoe UI |
| Layout | Max-width ~896px, centered |
| Dark mode | Fully implemented, localStorage-persisted |
| Language | English primary, NL/EN toggle for chatbot |
| Assets | `/avatar_sebastiaan.png` (headshot), `/avatar_digitaltwin.png` (twin avatar) |

> **For the designer:** The minimalist look is intentional, but it shouldn't feel austere. Sebastiaan is enthusiastic and optimistic — "a creative explorer", "nerd with MBA" — the site should have that energy without being loud. Think "a well-organised workshop" not "an empty room."

---

## 4. Information Architecture

### Site Map

```
sebastiaandenboer.org/
├── /                    Landing page (hero + sections below)
├── /chat                Full-screen digital twin conversation
├── /curiosa             Microblog feed (see §6)
├── /curiosa/:slug       Individual microblog post
└── /?page=admin         Admin panel (hidden, token-gated — not relevant for design)
```

### Landing Page Sections

The landing page is a single scrollable page with these sections, top to bottom:

#### 1. Hero
Photo, name, title, one-line bio. Social links: LinkedIn, GitHub, Email, CV download. No long bio — the digital twin *is* the about section. If people want depth, they talk to it.

> *"I build AI systems that make high-stakes decisions better."*

#### 2. Digital Twin CTA
The centrepiece. A prominent, inviting element that leads to `/chat`. This is the most important design challenge — see §5 for detail.

#### 3. Projects
A proper section — not just a list of links. Cards for each project with enough context to understand what it is and why it matters. The mix of digital and physical projects is intentional — that juxtaposition *is* the brand.

**Projects to feature:**

| Project | Type | Link | Description |
|---|---|---|---|
| **StoryBrew** | Web app | dromenbrouwer.nl | AI-powered interactive story platform. Generative AI meets narrative design — branching, personalised stories. |
| **Digital Twin** | This site | github.com/Zaklamp02/digitaltwin | RAG-powered AI agent with knowledge graph, multi-tier access, Telegram integration. FastAPI + React. |
| **RealLifeRisk** | R/Shiny app | github.com/Zaklamp02/RealLifeRisk | Companion app for a physical strategy board game. Move validation, combat resolution, live state broadcast over local WiFi. |
| **aiGrunn** | Community | aigrunn.org | AI conference in Groningen. Co-organiser of aiGrunn Café — monthly meetups bridging AI research and industry. |
| **Woodworking** | Physical | — | Built a full kitchen from scratch. Currently building a bespoke cabinet with reading nook for his daughter. |

> **For the designer:** Woodworking sits next to AI systems here. That's deliberate. Consider whether project cards should have images/thumbnails or if clean typography with an icon/emoji per card is enough. The projects section should feel alive and personal, not like a portfolio grid.

#### 4. The Curiosa (microblog teaser)
The 2–3 most recent posts from the microblog, with a "See all →" link to `/curiosa`. This section signals that the site is alive and regularly updated. See §6 for detail.

#### 5. Footer
Minimal. © year + something with personality. Maybe a subtle admin link.

---

## 5. The Digital Twin

### What It Is

A full-screen conversational AI agent at `/chat`. It speaks in first person as Sebastiaan. It knows about his career, projects, opinions, and personality. It draws on a private knowledge graph via RAG (retrieval-augmented generation). Visitors can ask anything — "What's your take on LLM agents?", "Walk me through your career", "What did you build at the Dutch tax authority?"

There is no separate "About" page. The digital twin *is* the about page. If you want to know about Sebastiaan, you ask.

### What's Already Built

- Streaming responses (tokens appear one by one, like ChatGPT)
- Voice input (speech-to-text) and voice output (text-to-speech)
- Multi-tier access: public (limited turns), recruiter (deeper), personal (full) — via URL token `?t=...`
- Language toggle: NL/EN, forces response language regardless of English source material
- Session management with turn limits per tier
- Full dark mode support
- Back button to return to landing page

### The Design Challenge: Making People Click

The twin is the most novel feature, but visitors don't know it exists until they land. The CTA on the landing page has to:

1. **Explain what it is** in one glance — "You can talk to an AI version of this person"
2. **Feel inviting, not intimidating** — not a developer demo, not a tech toy
3. **Lower the barrier** — reduce the mental cost of clicking. First-time visitors don't know what they're getting into.

**Creative directions to explore:**

- A card with the twin's avatar and a speech bubble greeting: *"Hey, I'm Sebastiaan's digital twin. Ask me anything about his career, projects, or opinions."* with 2–3 clickable starter questions beneath
- A persistent but unobtrusive floating element on every page (not just the landing page) so the twin is always accessible — like a quiet invitation
- A subtle animation that signals "this is interactive" without being cheesy — the twin avatar looking alive, a typing indicator, a gentle pulse
- The CTA could feel like the *start* of a conversation: as if the twin is already speaking to you, and clicking just continues it
- A mini-preview that shows one example exchange to demonstrate the experience before committing

> **Key context:** The twin is not the *primary* way recruiters find Sebastiaan (that's LinkedIn/CV). It's an additional, more interesting path. But for community peers and curious visitors, it might be the *main* reason they stay. Design accordingly — prominent but not the only thing.

### The Chat Page (`/chat`)

Full-screen, immersive, like a native messaging app. The designer's job here is the **chrome** — header, back button, transitions — not the message bubbles themselves (those already work well).

- Must have a clear back affordance to the landing page
- On mobile: fixed input bar at bottom, messages scroll, keyboard doesn't break layout
- The transition from landing page → chat should feel intentional. The visitor is choosing to engage.

---

## 6. The Curiosa — Microblog

### Concept

**"The Curiosa"** (inspired by *rariteitenkabinet* — the cabinet of curiosities) — a chaotic, tag-driven compendium of everything that interests Sebastiaan. Part glossary, part portfolio, part lab notebook. Not a polished blog with SEO-optimised headlines. A stream of thinking.

> **Alternative names for the designer to consider:** "The Curiosa", "Curiosa", "Cabinet", "The Archive", "Wunderkammer". The name should feel slightly unusual and personal — not generic "Blog."

### Content Character

| Type | Example | Length |
|---|---|---|
| **Opinion / hot take** | "Why I think RAG is still underrated in 2026" | 2–4 paragraphs |
| **Project update** | "Shipped the digital twin to production this week" | 1–3 paragraphs |
| **TIL / discovery** | "Docker DNS aliases can silently hijack other services" | 1–2 paragraphs |
| **Link + commentary** | Sharing an article with a short reaction | 1 paragraph + link |
| **Personal reflection** | Career thoughts, philosophy, life | 2–5 paragraphs |
| **Off-topic** | Running, woodworking, physics, whatever's on his mind | 1–5 paragraphs |

Expected posting frequency: **when inspired**. Could be twice a week, could be once a month. The design should not make an empty or slow feed feel dead.

### Design Requirements

**Feed page (`/curiosa`):**
- Simple reverse-chronological list
- Each post shows: **date**, **title** (optional — some posts are untitled thoughts), **body** (markdown-rendered), **tags**
- Tags are clickable and filter the feed inline. Example tags: `AI`, `projects`, `woodworking`, `opinions`, `running`, `TIL`, `physics`
- No pagination for now — full scrollable list
- No comments, no likes, no share buttons. If people want to discuss, they can use the digital twin or email.

**On the landing page:**
- 2–3 most recent posts as a teaser section
- "See all →" link to the full feed
- Should signal "this site is alive" even if the latest post is a week old

**Language:**
- Posts are written in one language (usually English, occasionally Dutch). The NL/EN toggle does **not** auto-translate posts.

> **For the designer:** The Curiosa should feel like opening someone's notebook. Casual, personal, a bit eclectic. The visual treatment of tags is important — they're the primary way to make sense of a diverse stream of content.

**Technical note (not for designer):**
Posts are stored as tagged knowledge DB nodes in the existing system. Creating a new post is as simple as adding a node in the admin panel — no separate CMS needed.

---

## 7. Language & Internationalisation

- **Primary language:** English. All landing page text, navigation, and UI chrome is in English.
- **NL/EN toggle:** In the top bar. Main effect is on the digital twin — forcing responses in Dutch or English regardless of source material.
- **The toggle does NOT translate** landing page content, microblog posts, or project descriptions.
- **Dutch is ~15% longer:** Layouts must accommodate slightly longer text when Dutch labels are used in UI elements.

---

## 8. Technical Constraints

For the designer's awareness — these affect what's possible.

| Constraint | What it means for design |
|---|---|
| **Single-page React app** (Vite + Tailwind CSS) | All routing is client-side. Page transitions can be instant/animated. |
| **Hosted on a home NAS** via Cloudflare Tunnel | No CDN for large assets. Keep images optimised and small. No SSR. |
| **Dark mode is built** | Every element, every state, every component must work in light and dark. |
| **Chat is SSE-streamed** | Messages appear word-by-word. Design must accommodate progressive text rendering. |
| **No backend CMS** | Blog posts are markdown/DB entries. No WYSIWYG editor in the browser. |
| **Max-width ~896px** | Current layout constraint. Can be widened if the design calls for it. |
| **Tailwind CSS** | Utility-first CSS. Highly flexible — custom CSS is also possible. |

---

## 9. What Exists Today

The site is live at `sebastiaandenboer.org` with a functional but developer-scaffolded layout:

- **Landing page** (`/`): Hero with photo, name, bio, social links. Digital twin CTA button. Project cards for StoryBrew, RealLifeRisk, Digital Twin, and aiGrunn. Footer with admin link.
- **Full-screen chat** (`/chat`): Working conversational interface with back button, language toggle, dark mode, voice I/O. Fully functional.
- **Admin panel** (`/?page=admin`): Token-gated. Not relevant for design.

**What works:** Everything. The chat, language toggle, dark mode, routing, backend APIs, knowledge graph, tier system.

**What needs design:** Visual quality, content hierarchy, the digital twin CTA experience, the microblog, and making the whole thing feel like a person's site instead of a prototype.

---

## 10. Design Deliverables

What we need from the designer:

1. **Landing page layout** — Desktop and mobile. All sections from §4.
2. **Digital twin CTA concept** — The most creative part. How do you invite someone into a conversation with an AI? (§5)
3. **Chat page chrome** — Header, back button, transition from landing page. The message UI itself is already built. (§5)
4. **Curiosa feed** — Feed layout, individual post layout, tag filtering UI. Desktop and mobile. (§6)
5. **Curiosa teaser on landing page** — How the 2–3 latest posts appear on the home page. (§6)
6. **Colour palette & typography** — Starting from the existing teal accent. Refine or extend as needed.
7. **Dark mode** — All of the above in both light and dark.

### Not in Scope

- Admin panel UI
- Chat message bubbles / streaming rendering (already built)
- Backend architecture
- Content writing (Sebastiaan writes his own)

---

## 11. What Makes This Site Different

Most personal sites are either a boring CV page or an over-designed portfolio. This one has a genuine novelty: **you can talk to it**. The digital twin is a real, functional AI agent — not a demo, not a chatbot that says "I'm an AI assistant." It speaks as Sebastiaan, knows his career and opinions, and gives useful answers.

The designer's challenge is to make that obvious, inviting, and delightful — while keeping the rest of the site clean, personal, and true to a "nerd with MBA" who builds AI systems and kitchen cabinets with equal enthusiasm.

---

## 12. Visual Inspiration & Refined Direction

Based on research into existing personal sites, the following themes have crystallised. These supersede the generic "clean and minimal" direction in §3 — they're more specific about *what kind* of minimal.

### Reference Sites

| Site | What resonates | What doesn't |
|---|---|---|
| **pixelswithin.com** | Super short hero description → bold single CTA ("Work With Me"). Immediate clarity. | Rest of the site is generic agency template. |
| **yangeorget.net** | Terminal/hacker aesthetic. Starts ultra-minimal, expands as you engage. Hidden depth, puzzle quality, easter eggs. No explanation needed. | Too extreme/raw for a professional context. |
| **voidvic.github.io** | Full-page hero with just a hello message. Clear "swipe down for more" affordance. Scroll-triggered animations revealing navigation. Mix of work and personal/travel. | — |
| **gervinfungdaxuen.vercel.app** | Main page is *just* a name — nothing else. Ultra-minimal. | Not enough beyond that. |
| **wodniack.dev** | Geometric background animation that responds to cursor. Full-screen presence with name at the bottom. Interactive/alive feel. | Too bold/loud overall. Sections are too heavy. |

### Distilled Design Direction

These are the key principles extracted from the above:

1. **Full-screen intro, almost nothing on it.** Name, a single line, and either a CTA or an input bar. The site starts silent and lets the visitor lean in. Think: wodniack.dev's presence + gervinfungdaxuen's emptiness.

2. **The chat input *is* the CTA.** Instead of a button that says "Talk to my digital twin", the landing page itself has a chat-style input at the bottom — like a terminal prompt or message field. The visitor types, and they're already in a conversation. The boundary between "landing page" and "chat" dissolves.

3. **A living background — subtle, geometric, low-contrast.** Something inspired by fluid dynamics, Voronoi tessellations, or particle systems. Cursor-interactive like wodniack.dev, but much more subdued — almost like looking at frosted glass with shapes moving behind it. Should not distract from text.

4. **The knowledge graph as navigation.** The mind palace / graph visualisation could serve as a semi-abstract way to show "areas of Sebastiaan" — nodes for Career, Projects, AI, Woodworking, etc. As the conversation touches topics, nodes light up or connect. This could live in the background, in a sidebar, or as an explorable overlay. It's both decoration and wayfinding.

5. **Progressive disclosure / hidden depth.** The site appears simple but rewards exploration. Easter eggs, hidden commands, unexpected interactions. Like yangeorget.net — you wonder "is there more?" and there is.

6. **Absolutely no manual needed.** Despite the above, the site must be instantly usable. A recruiter who doesn't care about easter eggs sees: name, title, CTA, CV download. Done. The depth is there for those who look, invisible to those who don't.

### The Tension to Resolve

The core design challenge is: **interactive, alive, novel** vs. **minimal, clear, no-manual-needed**. The site needs to be both. The inspiration sites each solve one side of this — the designer needs to solve both simultaneously.

---

## 13. Concept Explorations

Three distinct design directions have been prototyped as interactive HTML files. Each explores a different way to combine the principles above. They live in `/frontend/concepts/` and can be opened directly in a browser.

| Concept | File | Core idea |
|---|---|---|
| **A — "The Prompt"** | `concept-a-prompt.html` | Full-screen name + a blinking chat prompt at the bottom. You type, you're in the conversation. Minimal to the point of daring. |
| **B — "The Constellation"** | `concept-b-constellation.html` | Particle/node background that loosely represents the knowledge graph. Name centred. CTA card. Nodes drift and connect. Cursor-interactive. |
| **C — "The Terminal"** | `concept-c-terminal.html` | yangeorget-inspired: starts as a minimal greeting, with a terminal-style input. Type `help` to discover commands. Type anything else and it goes to the digital twin. Progressive disclosure with easter eggs. |

See each file for the full interactive prototype and design notes.

