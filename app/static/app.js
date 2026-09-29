const $ = (selector) => document.querySelector(selector);
const state = { current: null, site: "" };

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}
function dateLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, {dateStyle:"medium", timeStyle:"short"});
}
function showToast(message, error = false) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.toggle("error", error); toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 4200);
}
async function api(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json", ...(options.headers || {})}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
async function loadStatus() {
  try {
    const status = await api("/api/status");
    const pill = $("#connection-pill");
    if (status.hindsight_configured) {
      pill.textContent = `Hindsight connected · ${status.hindsight_bank_id}`; pill.classList.add("ready");
    } else {
      pill.textContent = "Hindsight needs setup"; pill.classList.add("offline");
    }
  } catch { $("#connection-pill").textContent = "Backend unavailable"; }
}
function renderFinding(item) {
  const severity = escapeHtml(item.severity);
  const guidance = item.guidance ? ` · <a href="${escapeHtml(item.guidance.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.guidance.label)} ↗</a>` : "";
  return `<div class="finding"><span class="severity ${severity}"></span><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)} <b>Observed:</b> ${escapeHtml(item.evidence)}</p><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">Analyzed page ↗</a>${guidance}</div><span class="finding-tag">${severity}</span></div>`;
}
function renderMemory(memory) {
  return `<div class="memory-item"><span class="memory-type">${escapeHtml(memory.type || "HINDSIGHT MEMORY")}</span><p>${escapeHtml(memory.text)}</p></div>`;
}
function renderResults(data) {
  state.current = data;
  const findings = data.findings.map(renderFinding).join("");
  const recommendation = data.recommendation;
  const recommendationSources = (recommendation.sources || []).map(source => `<a class="source-link" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.label)} ↗</a>`).join(" · ");
  const memories = data.memories || [];
  const memoryMessage = data.memory_status.message
    ? `<div class="notice">${escapeHtml(data.memory_status.message)}</div>`
    : (!data.memory_status.configured ? `<div class="notice">Hindsight is not connected. Configure the Cloud API key and bank ID in <code>.env</code>. Local snapshots do not replace Hindsight memory.</div>` : "");
  const recallLabel = data.memory_status.configured
    ? `${data.memory_status.recalled} memories recalled · ${data.memory_status.retained ? "analysis retained" : "retain pending"}`
    : "Memory not connected";
  const comparison = data.comparison?.length
    ? data.comparison.map(change => `<div class="comparison-row"><strong>${escapeHtml(change.field)} changed</strong><span>${escapeHtml(change.before)} <b>→ ${escapeHtml(change.after)}</b></span></div>`).join("")
    : (data.previous_analysis_at ? `<p class="form-hint">No tracked fields changed since the previous local snapshot.</p>` : `<p class="form-hint">This is the first saved page snapshot.</p>`);
  $("#welcome-panel").classList.add("hidden");
  const results = $("#results"); results.classList.remove("hidden");
  results.innerHTML = `
    <div class="result-head"><div><span class="step-label">02 / CURRENT ANALYSIS</span><h2>${escapeHtml(data.snapshot.title || data.url)}</h2><p><a class="source-link" href="${escapeHtml(data.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(data.url)} ↗</a>${data.keyword ? ` · Focus: ${escapeHtml(data.keyword)}` : ""}</p></div><span class="result-meta">${escapeHtml(dateLabel(data.created_at))} · HTTP ${escapeHtml(data.snapshot.status_code)}</span></div>
    <div class="result-grid"><div class="result-column">
      <article class="card recommend-card"><span class="card-label">03 / NEXT BEST ACTION</span><h3>${escapeHtml(recommendation.title)}</h3><p>${escapeHtml(recommendation.rationale)}</p>${recommendationSources ? `<p>${recommendationSources}</p>` : ""}<p class="next-step"><strong>Try this:</strong> ${escapeHtml(recommendation.next_step)}</p><span class="memory-chip ${recommendation.memory_influenced ? "" : "memory-empty"}">✳ ${escapeHtml(recallLabel)}</span><p class="caveat">${escapeHtml(recommendation.caveat)} ${recommendation.llm ? `· Synthesis: ${escapeHtml(recommendation.llm)}` : ""}</p></article>
      <article class="card"><span class="card-label">PAGE CHECKS</span><h3>What we found</h3>${findings}</article>
      <article class="card"><span class="card-label">HISTORICAL COMPARISON</span><h3>${data.previous_analysis_at ? "Since the last analysis" : "Starting baseline"}</h3>${comparison}</article>
    </div><div class="result-column">
      <article class="card"><span class="card-label">04 / HINDSIGHT RECALL</span><h3>History behind this advice</h3>${memoryMessage}${memories.length ? memories.map(renderMemory).join("") : `<p class="form-hint">${data.memory_status.configured ? "No relevant memories came back for this page yet. Record a confirmed action or outcome below, then analyze again." : "Connect Hindsight Cloud to retain and recall persistent SEO experience."}</p>`}</article>
      <article class="card"><span class="card-label">SOURCE NOTES</span><h3>Evidence you can inspect</h3><div class="memory-item"><span class="memory-type">LIVE PAGE · ${escapeHtml(dateLabel(data.created_at))}</span><p>Findings above come from the fetched HTML and are linked to the analyzed page. Search metrics and rankings are not connected in this MVP.</p></div>${(data.competitor ? `<div class="memory-item"><span class="memory-type">COMPETITOR OBSERVATION · ${escapeHtml(dateLabel(data.competitor.observed_at))}</span><p><a class="source-link" href="${escapeHtml(data.competitor.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(data.competitor.url)} ↗</a><br>Title: ${escapeHtml(data.competitor.title || "Not found")} · H1: ${escapeHtml((data.competitor.h1 || []).join(" / ") || "Not found")} · about ${escapeHtml(data.competitor.word_count)} visible words. This is a page snapshot, not ranking evidence.</p></div>` : "")}${data.competitor_message ? `<div class="notice">${escapeHtml(data.competitor_message)}</div>` : ""}<div class="memory-item"><span class="memory-type">LIMITS</span><p>Page signals are observations, not promises about ranking effects. Add a real measurement and its source as an outcome below.</p></div></article>
    </div></div>
    <article class="card event-card"><span class="card-label">05 / CLOSE THE LOOP</span><h3>Record what happened next</h3><p class="form-hint">Confirm a real change or record a later measurement. The app will send it to Hindsight when Cloud is configured.</p><div class="event-forms">
      <form data-kind="action"><label>Optimization you implemented</label><textarea name="content" placeholder="What did you change on this page?" required></textarea><button class="button-quiet" type="submit">Record implemented action</button></form>
      <form data-kind="outcome"><label>Outcome you measured</label><textarea name="content" placeholder="e.g. clicks changed from 9 to 13" required></textarea><input name="outcome_date" placeholder="Measurement date or period"><input name="source" placeholder="Source, e.g. Search Console · page · dates"><button class="button-quiet" type="submit">Record outcome</button></form>
      <form data-kind="decision"><label>Decision or constraint</label><textarea name="content" placeholder="What did you decide or defer, and why?" required></textarea><button class="button-quiet" type="submit">Record decision</button></form>
    </div></article>`;
  $("#history-section").classList.remove("hidden");
  state.site = data.site_key;
  loadHistory(data.site_key);
  results.scrollIntoView({behavior:"smooth", block:"start"});
}
async function loadHistory(site) {
  if (!site) return;
  try {
    const data = await api(`/api/history?site=${encodeURIComponent(site)}`);
    const entries = [...data.analyses.map(item => ({kind:"Analysis", content:`${item.recommendation?.title || "SEO analysis"} · ${item.findings.length} findings`, created_at:item.created_at})), ...data.events.map(item => ({kind:item.kind, content:item.content, created_at:item.created_at}))]
      .sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
    const memoryBlock = data.memories?.length
      ? `<article class="card"><span class="card-label">ACTUAL HINDSIGHT RECALL</span><h3>Memories Hindsight returned</h3>${data.memories.map(renderMemory).join("")}</article>`
      : `<article class="card"><span class="card-label">ACTUAL HINDSIGHT RECALL</span><h3>Memories Hindsight returned</h3><p class="form-hint">${data.hindsight_configured ? "No site memories returned yet." : "Hindsight Cloud is not configured. No substitute memory store is being used."}</p>${data.message ? `<div class="notice">${escapeHtml(data.message)}</div>` : ""}</article>`;
    $("#history-content").innerHTML = `<div class="history-grid"><article class="card"><span class="card-label">APP SNAPSHOTS & EVENTS</span><h3>Recent site activity</h3>${entries.length ? entries.map(item => `<div class="history-entry"><strong>${escapeHtml(item.kind)}</strong><p>${escapeHtml(item.content)}</p><time>${escapeHtml(dateLabel(item.created_at))}</time></div>`).join("") : `<p class="form-hint">No analysis or events recorded yet.</p>`}</article>${memoryBlock}</div>`;
  } catch (error) { showToast(error.message, true); }
}
$("#analyze-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const button = $("#analyze-button"); button.disabled = true; button.querySelector("span").textContent = "Analyzing page…";
  try {
    const form = new FormData(event.currentTarget);
    const result = await api("/api/analyze", {method:"POST", body:JSON.stringify({url:form.get("url"), keyword:form.get("keyword"), competitor_url:form.get("competitor")})});
    renderResults(result); loadStatus();
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.querySelector("span").textContent = "Analyze page"; }
});
$("#results").addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-kind]"); if (!form) return;
  event.preventDefault(); if (!state.current) return;
  const data = new FormData(form);
  try {
    const result = await api("/api/events", {method:"POST", body:JSON.stringify({analysis_id:state.current.analysis_id, kind:form.dataset.kind, content:data.get("content"), outcome_date:data.get("outcome_date") || "", source:data.get("source") || ""})});
    form.reset(); showToast(result.retained_in_hindsight ? "Saved and retained in Hindsight." : result.message || "Saved.");
    loadHistory(state.site);
  } catch (error) { showToast(error.message, true); }
});
$("#refresh-history").addEventListener("click", () => loadHistory(state.site));
loadStatus();
