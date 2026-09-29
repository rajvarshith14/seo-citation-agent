"""Evidence-first prioritization and optional Groq wording."""

import json
from typing import Any

from app.config import get_settings


def build_recommendation(findings: list[dict], memories: list[dict], previous: dict | None) -> dict:
    actionable = [item for item in findings if item["severity"] in {"high", "medium", "low"}]
    priority = {"high": 0, "medium": 1, "low": 2}
    actionable.sort(key=lambda item: priority[item["severity"]])
    lead = actionable[0] if actionable else None
    memory_text = " ".join(memory.get("text", "").lower() for memory in memories)

    if lead:
        title = lead["title"]
        rationale = f"Current page evidence: {lead['evidence']}"
        next_step = f"Review the {lead['title'].lower()} finding on this page and make a deliberate change if it matches the page's purpose."
        sources = [{"label": "Analyzed page evidence", "url": lead["source_url"], "detail": lead["evidence"]}]
    else:
        title = "Review the page against its search goal"
        rationale = "No high or medium severity checks were identified by this limited HTML analysis."
        next_step = "Confirm that the page serves the intended query and that the supplied topic is appropriate."
        sources = []

    history_notes = []
    memory_influenced = False
    if memories:
        for memory in memories:
            history_notes.append(memory["text"])
        has_action = any(term in memory_text for term in ("implemented", "optimization action", "changed", "updated", "rewrote"))
        has_outcome = any(term in memory_text for term in ("outcome", "clicks", "impressions", "position", "traffic"))
        has_decision = any(term in memory_text for term in ("defer", "deferred", "rejected", "decision", "constraint"))
        if any(term in memory_text for term in ("defer", "rejected", "do not", "not change", "review")):
            rationale += " Relevant Hindsight history includes a prior user decision or constraint; check the recalled memory before repeating a similar action."
            memory_influenced = True
        elif any(term in memory_text for term in ("click", "impression", "position", "outcome", "after")):
            rationale += " Hindsight recalled prior outcome observations. Treat them as historical context, not proof that a change caused a ranking result."
            memory_influenced = True
        else:
            rationale += " This recommendation was prepared with relevant Hindsight history in context."
        # Avoid repeating a change immediately when memory explicitly reports it.
        issue_terms = {
            "title": ("title",), "description": ("description", "snippet"),
            "h1": ("h1", "heading"), "canonical": ("canonical",),
            "noindex": ("noindex", "indexing"), "image": ("image", "alt"),
            "topic": ("topic", "keyword", "content"),
        }
        category = next((name for name, terms in issue_terms.items() if any(term in title.lower() for term in terms)), "")
        prior_same_issue = bool(category and any(term in memory_text for term in issue_terms[category]))
        if category == "title" and prior_same_issue and has_action:
            next_step = "Hindsight recalls a previous title change. Verify the live title first, then compare a consistent measurement window before making another title edit."
            memory_influenced = True
        elif category == "description" and prior_same_issue and has_action:
            next_step = "Hindsight recalls a previous description change. Verify what is live and review the same page and measurement window before rewriting it again."
            memory_influenced = True
        elif has_decision:
            next_step = "Review the recalled decision and its reason. If the constraint still applies, address the next independent finding instead of repeating the deferred action."
            memory_influenced = True
        elif has_outcome and has_action:
            next_step = "Hindsight recalls a prior change and a later outcome. Check that the measurement covers the same page, metric, and comparable date window before deciding whether to repeat or extend that change."
            memory_influenced = True
    elif previous:
        # SQLite comparison is strictly factual snapshot comparison, not a memory substitute.
        history_notes.append(f"Previous local snapshot from {previous.get('created_at')}; exact page fields are available for comparison.")
        rationale += " A previous page snapshot exists locally, but no relevant Hindsight memory was returned."

    return {
        "title": title,
        "priority": lead["severity"] if lead else "review",
        "rationale": rationale,
        "next_step": next_step,
        "sources": sources,
        "memory_influenced": memory_influenced,
        "memory_count": len(memories),
        "history_notes": history_notes[:5],
        "caveat": "This is a bounded check of fetched HTML, not a full SEO audit or a ranking guarantee.",
    }


def enrich_with_groq(recommendation: dict, findings: list[dict], memories: list[dict], keyword: str) -> dict:
    settings = get_settings()
    if not settings.groq_api_key:
        recommendation["llm"] = "deterministic-fallback"
        return recommendation
    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write a concise SEO recommendation using only supplied facts. "
                        "Do not invent ranking effects or sources. Treat memory as historical evidence, "
                        "and distinguish user reports from verified measurements. Return JSON with "
                        "title, rationale, next_step, and caveat."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "keyword": keyword,
                        "current_findings": findings,
                        "hindsight_memories": memories,
                        "candidate": recommendation,
                    }, ensure_ascii=False),
                },
            ],
        )
        generated = json.loads(response.choices[0].message.content or "{}")
        for key in ("title", "rationale", "next_step", "caveat"):
            if isinstance(generated.get(key), str) and generated[key].strip():
                recommendation[key] = generated[key].strip()
        recommendation["llm"] = settings.groq_model
    except Exception as exc:
        recommendation["llm"] = "deterministic-fallback"
        recommendation["llm_note"] = f"Groq synthesis was unavailable ({exc.__class__.__name__}); deterministic recommendation shown."
    return recommendation
