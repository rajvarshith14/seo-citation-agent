# Recall SEO

A memory-driven SEO assistant for small site owners. It combines current on-page observations, source links, relevant Hindsight history, and measured outcomes to guide the next optimization decision.

## Current MVP

- Fetches one public HTML page and runs bounded on-page checks.
- Cites the analyzed page and links relevant official Google Search Central guidance.
- Stores dated page snapshots and user-entered workflow events in SQLite for exact comparison and the activity view.
- Calls Hindsight Cloud directly for explicit Retain and Recall. SQLite is not used as a substitute memory system.
- Uses Groq GPT-OSS for recommendation wording when a Groq key is configured; otherwise it uses an evidence-led deterministic recommendation.
- Supports optional, user-triggered competitor page snapshots. It does not continuously crawl competitors.
- Lets the user record an implemented action, a later outcome, or a decision/constraint.

The app does not connect to Search Console, track live rankings, publish website changes, or promise ranking improvement.

## Setup

1. Use Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies: `python -m pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`.
5. Add the Hindsight Cloud API key and bank ID. Add a Groq API key for LLM recommendation wording.
6. Start the server: `uvicorn app.main:app --reload`.
7. Open `http://127.0.0.1:8000`.

Hindsight Cloud settings:

- `HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io`
- `HINDSIGHT_API_KEY=...`
- `HINDSIGHT_BANK_ID=seo-citation-agent-demo`

The integration follows the official [Hindsight Cloud getting started guide](https://docs.hindsight.vectorize.io/getting-started/) and [Python client reference](https://hindsight.vectorize.io/sdks/python).

Groq setting:

- `GROQ_API_KEY=...`
- `GROQ_MODEL=openai/gpt-oss-120b`

Keep `.env` private; it is ignored by Git. Without Hindsight credentials, the app reports that Hindsight is disconnected and does not pretend SQLite provides persistent agent memory. Without Groq credentials, recommendation synthesis uses a deterministic fallback.

## Demo loop

1. Analyze a page and review findings, current page evidence, relevant source links, and the first recommendation.
2. Record an action that was actually implemented, a decision, or a later outcome with its measurement source.
3. Analyze the same page again. Review the local snapshot comparison and the memories Hindsight returned.
4. Confirm how the recommendation accounts for the recalled experience.

For the clearest memory demonstration, use the same Hindsight bank and site throughout. A manually entered outcome is labeled as an observation and is not treated as proof of causation.

## Main routes

- `GET /health` — process health.
- `GET /api/status` — Hindsight and Groq configuration status.
- `POST /api/analyze` — fetch, analyze, recall, compare, recommend, and retain.
- `POST /api/events` — record an action, outcome, or decision and retain it in Hindsight.
- `GET /api/history?site=example.com` — local activity plus actual Hindsight recall.

## Security and limits

The fetcher rejects non-public addresses, refuses redirects, accepts HTML only, and caps response size. It analyzes only user-supplied URLs and does not modify sites. This is a hackathon MVP, not an enterprise SEO platform.
