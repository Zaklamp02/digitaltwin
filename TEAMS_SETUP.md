# Setting up the Teams Outgoing Webhook

This guide walks through connecting the digital twin to a Microsoft Teams channel
so colleagues can `@mention` it and get answers from the work-tier knowledge base.

## How it works

```
Colleague types:  @AskSeb What's Sebastiaan's take on MLOps?
                         │
                         ▼
              Teams POSTs JSON to your backend
              POST https://<your-domain>/api/teams/webhook
                         │
                         ▼
              Backend verifies HMAC signature,
              strips the @mention, runs the question
              through RAG (public + work content only),
              generates a concise LLM response
                         │
                         ▼
              Response appears in the channel thread
```

- Only **public** and **work** content is accessible — personal/friends content is never returned.
- The bot must respond within **10 seconds** (Teams hard limit). Current average is ~3–4s.
- No IT admin approval needed — outgoing webhooks are a team-level feature any team owner can create.

---

## Prerequisites

1. **Backend reachable over HTTPS from the internet.**
   The backend is already running at `/api/teams/webhook`, but Teams needs to
   reach it from Microsoft's servers. Options:

   | Method | Notes |
   |--------|-------|
   | **Cloudflare Tunnel** (recommended) | Free. Run `cloudflared tunnel` pointed at `localhost:5173`. You likely already have this for the main site. |
   | **ngrok** | `ngrok http 5173` — gives you a temporary public URL. Fine for testing. |
   | **Direct NAS exposure** | If port 5173 is already forwarded with a domain + TLS cert, it just works. |

2. **You must be an owner of the Teams team** where you want to add the webhook
   (or ask an owner to do it — it takes 2 minutes).

---

## Step-by-step: create the webhook in Teams

### 1. Open the team settings

- In Teams, go to the **team** (not just a channel) where you want the bot.
- Click the **⋯** (three dots) next to the team name → **Manage team**.

### 2. Go to the Apps tab

- In the Manage team view, click the **Apps** tab along the top.

### 3. Create the outgoing webhook

- Scroll to the bottom and click **Create an outgoing webhook**.
- Fill in:

  | Field | Value |
  |-------|-------|
  | **Name** | `AskSeb` (this is what people will `@mention`) |
  | **Callback URL** | `https://<your-public-domain>/api/teams/webhook` |
  | **Description** | Ask Sebastiaan's digital twin anything work-related |
  | **Profile picture** | Optional — upload an avatar if you like |

- Click **Create**.

### 4. Copy the HMAC security token

After creation, Teams shows a dialog with an **HMAC token** (a base64-encoded
string). **Copy it immediately** — you can't retrieve it later.

It looks something like:
```
dGhpcyBpcyBhIHNhbXBsZSB0b2tlbg==
```

### 5. Configure the backend

Add the token to your `.env` file on the server:

```env
TEAMS_WEBHOOK_SECRET=dGhpcyBpcyBhIHNhbXBsZSB0b2tlbg==
```

Then restart the backend:

```bash
docker compose up --build -d backend
```

Without this secret, the endpoint will still work but **won't verify** that
requests actually come from Teams (fine for local testing, not for production).

---

## Usage

Once the webhook is active, any member of that team channel can type:

```
@AskSeb What projects has Sebastiaan worked on recently?
```

```
@AskSeb What's the AI team's approach to MLOps?
```

```
@AskSeb Tell me about Sebastiaan's background
```

The bot will respond in the same thread within a few seconds.

### What gets returned

- Content tagged with `public` or `work` roles in the knowledge graph.
- Answers are kept concise (a few paragraphs) to suit the Teams chat format.
- The LLM is instructed to only share professionally appropriate information.

### What does NOT get returned

- Content tagged `friends` or `personal` — these roles are never passed to the
  retriever for Teams webhook requests.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| **"Could not connect to the webhook"** when creating in Teams | Your callback URL is not reachable from the internet. Check your tunnel / DNS / firewall. |
| **Bot responds with "Invalid HMAC signature"** | The `TEAMS_WEBHOOK_SECRET` in `.env` doesn't match the token Teams provided. Re-create the webhook or fix the env var. |
| **Bot responds but the answer is "(response trimmed…)"** | The LLM took too long. This is rare but can happen with complex questions or slow API responses. Try a simpler question. |
| **No response at all** | Check `docker compose logs backend --tail=20` for errors. Common cause: backend crashed or isn't running. |
| **"I didn't catch a question"** | The user only typed `@AskSeb` without a question after it. |

---

## Testing locally (without Teams)

You can simulate a Teams webhook call with curl:

```bash
curl -s -X POST http://localhost:5173/api/teams/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "type": "message",
    "text": "<at>AskSeb</at> What does Sebastiaan do?",
    "from": {"name": "Test User"}
  }'
```

Expected: a JSON response like `{"type": "message", "text": "...answer..."}`.

---

## Technical details

- **Endpoint**: `POST /api/teams/webhook`
- **Source**: `backend/app/teams_webhook.py`
- **Roles used**: `["public", "work"]` (hardcoded — not configurable via token)
- **Max LLM tokens**: 600 (keeps responses concise)
- **Timeout guard**: If LLM generation exceeds 8.5s, the response is truncated
  to stay within Teams' 10-second limit
- **Auth**: HMAC-SHA256 verification via the `Authorization: HMAC <signature>`
  header that Teams sends with every request
