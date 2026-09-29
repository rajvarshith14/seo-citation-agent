"""Bounded page fetching and deterministic on-page SEO observations."""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


class PageFetchError(ValueError):
    pass


def _validate_public_url(url: str) -> str:
    candidate = url.strip()
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PageFetchError("Enter a valid public http or https URL.")
    if parsed.username or parsed.password:
        raise PageFetchError("URLs containing username or password are not accepted.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise PageFetchError("Local and private network addresses cannot be analyzed.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(entry[4][0])
                for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise PageFetchError("The site hostname could not be resolved.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise PageFetchError("Local and private network addresses cannot be analyzed.")
    return candidate


def _finding(code: str, severity: str, title: str, detail: str, evidence: str, url: str) -> dict:
    return {
        "id": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "evidence": evidence,
        "source_url": url,
    }


def analyze_page(raw_url: str, keyword: str = "") -> dict:
    url = _validate_public_url(raw_url)
    headers = {"User-Agent": "SEO-Citation-Agent/0.1 (+local hackathon analysis)"}
    try:
        with httpx.Client(
            timeout=httpx.Timeout(12.0), follow_redirects=False,
            max_redirects=0, headers=headers,
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise PageFetchError(f"Could not fetch the page: {exc.__class__.__name__}.") from exc
    if 300 <= response.status_code < 400:
        raise PageFetchError("The page redirected. Enter its final destination URL directly.")
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        raise PageFetchError(f"The URL returned {content_type or 'an unknown content type'}, not HTML.")
    if len(response.content) > 2_000_000:
        raise PageFetchError("The page is larger than the 2 MB analysis limit.")

    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
    description = (description_tag.get("content") or "").strip() if description_tag else ""
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in [part.lower() for part in (value if isinstance(value, list) else value.split())])
    canonical = urljoin(url, canonical_tag.get("href", "")) if canonical_tag and canonical_tag.get("href") else ""
    robots_tag = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "robots"})
    robots = (robots_tag.get("content") or "").lower() if robots_tag else ""
    headings = [node.get_text(" ", strip=True) for node in soup.find_all(["h1", "h2", "h3"])]
    h1s = [node.get_text(" ", strip=True) for node in soup.find_all("h1")]
    text = " ".join(soup.stripped_strings)
    images = soup.find_all("img")
    missing_alt = [img.get("src", "image") for img in images if img.get("alt") is None]
    links = [urljoin(url, a.get("href", "")) for a in soup.find_all("a", href=True) if a.get("href", "").strip()]
    viewport = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "viewport"})

    findings = []
    x_robots = response.headers.get("x-robots-tag", "").lower()
    if response.status_code >= 400:
        findings.append(_finding("http_error", "high", f"Page returned HTTP {response.status_code}", "The requested URL did not return a successful response. Confirm the URL and whether this page should be publicly accessible.", f"HTTP status {response.status_code}", url))
    if not title:
        findings.append(_finding("title_missing", "high", "Page title is missing", "No HTML title element was found.", "<title> not present", url))
    elif len(title) > 65:
        findings.append(_finding("title_long", "medium", "Page title is long", f"The title has {len(title)} characters; review how it reads in search results.", title, url))
    elif len(title) < 20:
        findings.append(_finding("title_short", "low", "Page title is brief", f"The title has {len(title)} characters. Check that it clearly identifies this page.", title, url))
    else:
        findings.append(_finding("title_present", "good", "Page title found", f"The title has {len(title)} characters.", title, url))
    if not description:
        findings.append(_finding("description_missing", "medium", "Meta description is missing", "No meta description was found. Search engines may construct snippets from page content.", "<meta name=description> not present", url))
    else:
        findings.append(_finding("description_present", "good", "Meta description found", f"The description has {len(description)} characters.", description, url))
    if not h1s:
        findings.append(_finding("h1_missing", "medium", "No H1 heading found", "The page has no H1 element in the fetched HTML.", "H1 count: 0", url))
    elif len(h1s) > 1:
        findings.append(_finding("multiple_h1", "low", "Multiple H1 headings found", f"Found {len(h1s)} H1 headings; review whether the hierarchy is intentional.", " | ".join(h1s[:4]), url))
    else:
        findings.append(_finding("h1_present", "good", "H1 heading found", "One H1 was found in the fetched HTML.", h1s[0], url))
    if "noindex" in robots or "noindex" in x_robots:
        findings.append(_finding("noindex", "high", "Page declares noindex", "A robots meta tag or X-Robots-Tag header contains noindex. Confirm this is intentional for a page meant to appear in search.", f"robots={robots or 'not present'}; x-robots-tag={x_robots or 'not present'}", url))
    else:
        findings.append(_finding("indexable_meta", "good", "No noindex directive observed", "This check inspected the robots meta tag and X-Robots-Tag response header; other indexing controls are outside this check.", f"robots={robots or 'not present'}; x-robots-tag={x_robots or 'not present'}", url))
    if canonical and urlparse(canonical).netloc != urlparse(url).netloc:
        findings.append(_finding("external_canonical", "high", "Canonical points to another host", "Verify that this cross-host canonical is intentional.", canonical, url))
    elif canonical:
        findings.append(_finding("canonical_present", "good", "Canonical URL found", "A canonical link is present.", canonical, url))
    else:
        findings.append(_finding("canonical_missing", "low", "Canonical URL not found", "No canonical link was present in the fetched HTML.", "<link rel=canonical> not present", url))
    if missing_alt:
        findings.append(_finding("image_alt_missing", "low", "Images missing alt attributes", f"{len(missing_alt)} of {len(images)} images have no alt attribute.", ", ".join(missing_alt[:5]), url))
    if len(text.split()) < 120:
        findings.append(_finding("sparse_content", "medium", "Little visible text was extracted", f"About {len(text.split())} words were found in the fetched HTML. This may be normal for some page types or indicate client-rendered content.", text[:300] or "No visible text extracted", url))
    if keyword.strip():
        terms = [word.lower() for word in keyword.split() if len(word) > 2]
        content_lower = (title + " " + " ".join(h1s) + " " + text[:5000]).lower()
        missing = [term for term in terms if term not in content_lower]
        if missing:
            findings.append(_finding("topic_not_observed", "medium", "Target topic not observed in key page text", "The supplied phrase was not fully found in title, headings, or the first 5,000 characters of extracted text. This is a text check, not an assessment of search intent.", ", ".join(missing), url))
        else:
            findings.append(_finding("topic_observed", "good", "Target topic terms found", "All supplied terms appear in title, headings, or the extracted page text.", keyword, url))

    snapshot = {
        "status_code": response.status_code,
        "final_url": str(response.url),
        "title": title,
        "description": description,
        "canonical": canonical,
        "robots": robots,
        "x_robots": x_robots,
        "h1": h1s,
        "headings": headings[:30],
        "word_count": len(text.split()),
        "image_count": len(images),
        "missing_alt_count": len(missing_alt),
        "link_count": len(links),
        "mobile_viewport_present": viewport is not None,
        "text_excerpt": text[:1200],
    }
    guidance = {
        "title_missing": {"label": "Google Search Central: title links", "url": "https://developers.google.com/search/docs/appearance/title-link"},
        "title_long": {"label": "Google Search Central: title links", "url": "https://developers.google.com/search/docs/appearance/title-link"},
        "title_short": {"label": "Google Search Central: title links", "url": "https://developers.google.com/search/docs/appearance/title-link"},
        "description_missing": {"label": "Google Search Central: snippets", "url": "https://developers.google.com/search/docs/appearance/snippet"},
        "noindex": {"label": "Google Search Central: block indexing", "url": "https://developers.google.com/search/docs/crawling-indexing/block-indexing"},
        "external_canonical": {"label": "Google Search Central: canonical URLs", "url": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls"},
        "canonical_present": {"label": "Google Search Central: canonical URLs", "url": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls"},
    }
    for item in findings:
        if item["id"] in guidance:
            item["guidance"] = guidance[item["id"]]
    return {"url": url, "snapshot": snapshot, "findings": findings}
