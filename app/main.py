"""HTTP application and MVP orchestration endpoints."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db, memory
from app.analysis import PageFetchError, analyze_page
from app.recommendations import build_recommendation, enrich_with_groq

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(
    title="SEO & Citation Agent",
    description="Context-aware SEO guidance combining current evidence with Hindsight history.",
    version="0.2.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2048)
    keyword: str = Field(default="", max_length=160)
    competitor_url: str = Field(default="", max_length=2048)


class EventRequest(BaseModel):
    analysis_id: str
    kind: Literal["action", "outcome", "decision"]
    content: str = Field(min_length=4, max_length=2000)
    outcome_date: str = Field(default="", max_length=40)
    source: str = Field(default="", max_length=300)


def _site_key(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _compare(previous: dict | None, current: dict) -> list[dict[str, str]]:
    if not previous:
        return []
    before = previous.get("page_snapshot", {})
    labels = {
        "title": "Title", "description": "Meta description", "canonical": "Canonical",
        "robots": "Robots directive", "h1": "H1", "word_count": "Visible word count",
        "missing_alt_count": "Images without alt attributes",
    }
    changes = []
    for key, label in labels.items():
        old, new = before.get(key), current.get(key)
        if old != new:
            changes.append({"field": label, "before": str(old or "—"), "after": str(new or "—")})
    return changes


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health", tags=["foundation"])
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "mvp"}


@app.get("/api/status")
def status() -> dict:
    from app.config import get_settings

    settings = get_settings()
    return {
        "hindsight_configured": memory.configured(),
        "hindsight_bank_id": settings.hindsight_bank_id if memory.configured() else "",
        "groq_configured": bool(settings.groq_api_key),
    }


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest) -> dict:
    try:
        result = analyze_page(request.url, request.keyword)
    except PageFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Page analysis failed ({exc.__class__.__name__}).") from exc

    site_key = _site_key(result["url"])
    previous = db.latest_analysis(site_key, result["url"])
    context = "; ".join(f"{item['title']}: {item['evidence']}" for item in result["findings"][:8])
    memories = []
    memory_error = ""
    if memory.configured():
        try:
            memories = memory.recall(site_key, result["url"], request.keyword, context)
        except Exception as exc:
            memory_error = f"Hindsight recall failed ({exc.__class__.__name__}); this recommendation used no recalled memory."

    recommendation = build_recommendation(result["findings"], memories, previous)
    recommendation = enrich_with_groq(recommendation, result["findings"], memories, request.keyword)
    now = datetime.now(timezone.utc).isoformat()
    analysis_id = str(uuid.uuid4())
    record = {
        "id": analysis_id,
        "site_key": site_key,
        "url": result["url"],
        "keyword": request.keyword.strip(),
        "created_at": now,
        "page_snapshot": result["snapshot"],
        "findings": result["findings"],
        "recommendation": recommendation,
    }
    db.save_analysis(record)

    retained = False
    retention_error = ""
    if memory.configured():
        memory_text = (
            f"SEO analysis for website {site_key}, page {result['url']}, topic {request.keyword or 'unspecified'} "
            f"on {now}. Current observed page snapshot: {result['snapshot']}. "
            f"Findings: {result['findings']}. Recommendation: {recommendation}."
        )
        try:
            retained = memory.retain(
                memory_text,
                context=f"{site_key} | dated SEO analysis",
                document_id=f"analysis-{analysis_id}",
            )
        except Exception as exc:
            retention_error = f"Hindsight retain failed ({exc.__class__.__name__}); the analysis was saved locally only."

    competitor = None
    competitor_error = ""
    if request.competitor_url.strip():
        try:
            competitor_page = analyze_page(request.competitor_url, request.keyword)
            competitor = {
                "url": competitor_page["url"],
                "observed_at": now,
                "title": competitor_page["snapshot"]["title"],
                "h1": competitor_page["snapshot"]["h1"],
                "word_count": competitor_page["snapshot"]["word_count"],
                "headings": competitor_page["snapshot"]["headings"][:8],
            }
            observation = (
                f"Manual, user-triggered competitor page observation on {now}: {competitor}. "
                "This is a visible page snapshot only; it is not evidence of competitor rankings or causation."
            )
            competitor_event = {
                "id": str(uuid.uuid4()), "analysis_id": analysis_id,
                "site_key": site_key, "url": competitor["url"],
                "kind": "competitor", "content": observation, "created_at": now,
            }
            db.save_event(competitor_event)
            if memory.configured():
                try:
                    memory.retain(
                        observation,
                        context=f"{site_key} | user-requested competitor observation",
                        document_id=f"competitor-{competitor_event['id']}",
                    )
                except Exception as exc:
                    competitor_error = f"Competitor observation saved locally, but Hindsight retain failed ({exc.__class__.__name__})."
        except PageFetchError as exc:
            competitor_error = f"Competitor page was not analyzed: {exc}"
        except Exception as exc:
            competitor_error = f"Competitor page analysis failed ({exc.__class__.__name__})."

    return {
        "analysis_id": analysis_id,
        "site_key": site_key,
        "url": result["url"],
        "keyword": request.keyword,
        "created_at": now,
        "snapshot": result["snapshot"],
        "findings": result["findings"],
        "comparison": _compare(previous, result["snapshot"]),
        "previous_analysis_at": previous.get("created_at") if previous else None,
        "recommendation": recommendation,
        "memories": memories,
        "memory_status": {
            "configured": memory.configured(),
            "recalled": len(memories),
            "retained": retained,
            "message": memory_error or retention_error,
        },
        "competitor": competitor,
        "competitor_message": competitor_error,
    }


@app.post("/api/events")
def record_event(request: EventRequest) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (request.analysis_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    timestamp = datetime.now(timezone.utc).isoformat()
    site_key, url = row["site_key"], row["url"]
    detail = request.content.strip()
    if request.kind == "outcome":
        detail = (
            f"Outcome observed {request.outcome_date or timestamp}: {detail}. "
            f"Source/measurement notes: {request.source or 'user-reported; no source specified'}. "
            "This observation does not by itself establish causation."
        )
    elif request.kind == "action":
        detail = f"User confirmed optimization action on {timestamp}: {detail}"
    else:
        detail = f"User decision recorded on {timestamp}: {detail}"

    event = {
        "id": str(uuid.uuid4()), "analysis_id": request.analysis_id,
        "site_key": site_key, "url": url, "kind": request.kind,
        "content": detail, "created_at": timestamp,
    }
    db.save_event(event)
    retained = False
    message = ""
    if memory.configured():
        try:
            retained = memory.retain(
                detail,
                context=f"{site_key} | confirmed SEO {request.kind} for {url}",
                document_id=f"event-{event['id']}",
            )
        except Exception as exc:
            message = f"Hindsight retain failed ({exc.__class__.__name__}); event saved locally only."
    else:
        message = "Hindsight is not configured; event saved as app state only, not retained as memory."
    return {"event": event, "retained_in_hindsight": retained, "message": message}


@app.get("/api/history")
def history(site: str) -> dict:
    site_key = site.lower().removeprefix("www.")
    memories = []
    memory_error = ""
    if memory.configured():
        try:
            # A broad site query makes the Hindsight view inspectable in the demo.
            memories = memory.recall(site_key, f"https://{site_key}", "", "Recent site decisions, SEO actions, and outcomes")
        except Exception as exc:
            memory_error = f"Hindsight recall failed ({exc.__class__.__name__})."
    return {
        "site_key": site_key,
        "analyses": db.list_history(site_key),
        "events": db.list_events(site_key),
        "memories": memories,
        "hindsight_configured": memory.configured(),
        "message": memory_error,
    }
