"""Direct Hindsight Cloud integration: no local memory substitute."""

from typing import Any

from app.config import get_settings


def configured() -> bool:
    settings = get_settings()
    return bool(settings.hindsight_api_key and settings.hindsight_bank_id)


def _client():
    from hindsight_client import Hindsight

    settings = get_settings()
    return Hindsight(
        base_url=settings.hindsight_base_url or "https://api.hindsight.vectorize.io",
        api_key=settings.hindsight_api_key,
        timeout=20.0,
    )


def _ensure_bank(client: Any, bank_id: str) -> None:
    try:
        client.create_bank(bank_id=bank_id, name="SEO & Citation Agent demo")
    except Exception as exc:
        # Existing banks are normal. Other errors will be surfaced by the next operation.
        if "already exists" not in str(exc).lower() and "409" not in str(exc):
            raise


def recall(site_key: str, url: str, keyword: str, query_context: str = "") -> list[dict[str, str]]:
    if not configured():
        return []
    client = _client()
    try:
        settings = get_settings()
        _ensure_bank(client, settings.hindsight_bank_id)
        response = client.recall(
            bank_id=settings.hindsight_bank_id,
            query=(
                f"SEO history for website {site_key}, page {url}, topic {keyword}. "
                f"Find prior audits, recommendations, user decisions, confirmed changes, "
                f"measured outcomes, competitor observations, and relevant source history. "
                f"Current context: {query_context[:1200]}"
            ),
        )
        results = getattr(response, "results", []) or []
        memories = []
        for item in results[:8]:
            memories.append({
                "text": str(getattr(item, "text", item)),
                "type": str(getattr(item, "type", "memory")),
            })
        return memories
    finally:
        close = getattr(client, "close", None)
        if close:
            close()


def retain(content: str, context: str, document_id: str | None = None) -> bool:
    if not configured():
        return False
    client = _client()
    try:
        settings = get_settings()
        _ensure_bank(client, settings.hindsight_bank_id)
        kwargs = {
            "bank_id": settings.hindsight_bank_id,
            "content": content,
            "context": context,
            "metadata": {"application": "seo-citation-agent", "site": context.split("|")[0].strip()},
        }
        if document_id:
            kwargs["document_id"] = document_id
        client.retain(**kwargs)
        return True
    finally:
        close = getattr(client, "close", None)
        if close:
            close()
