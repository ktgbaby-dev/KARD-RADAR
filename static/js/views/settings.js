import { get, put } from "../api.js";
import { esc, toast, busy } from "../ui.js";

const LABELS = { business_fit: "Business fit", social_activity: "Social activity", digital_gap: "Digital presence gap",
  buying_signals: "Buying signals", accessibility: "Accessibility" };

export async function render(el, _p, { loadMeta }) {
  el.dataset.title = "Strategy";
  const d = await get("/api/settings");
  const s = d.settings;
  let industries = s.target_industries.map((i) => ({ ...i }));

  const indRows = () => industries.map((i, n) => `<div class="ind-row" data-i="${n}">
      <input type="text" class="iname" value="${esc(i.name)}" aria-label="Industry name">
      <input type="text" class="kw" value="${esc((i.keywords || []).join(", "))}" placeholder="matching keywords" aria-label="Keywords for ${esc(i.name)}">
      <label class="check" title="Customer-facing businesses earn the customer-facing fit point"><input type="checkbox" class="icf" ${i.customer_facing ? "checked" : ""}> Customer-facing</label>
      <button type="button" class="btn-ghost small" data-rm="${n}" aria-label="Remove ${esc(i.name)}">Remove</button></div>`).join("");

  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Kard strategy</div><h1>Scoring &amp; targeting</h1>
      <p class="sub">Change what Kard Radar looks for. Saving rescores every analysed lead instantly — no AI calls, no web requests.</p></div></div>
    <form id="sform" class="split">
      <div class="stack">
        <section class="card"><div class="card-head"><h2>Scoring weights</h2><span class="small faint">must total 100</span></div>
          <div class="weights">${d.category_keys.map((k) => `<div class="weight-row"><label for="w_${k}"><b>${esc(LABELS[k])}</b></label>
            <input type="range" min="0" max="60" step="1" value="${s.weights[k]}" data-w="${k}" aria-label="${esc(LABELS[k])} weight">
            <input type="number" id="w_${k}" min="0" max="100" value="${s.weights[k]}" data-wn="${k}"></div>`).join("")}</div>
          <div class="total" id="total" style="margin-top:14px"></div>
          <p class="small faint" style="margin-top:10px">Each category keeps its internal signal points (e.g. "No website found" is 10 of the gap's 30 raw points); the weight rescales the category's share of the 100-point opportunity score.</p>
        </section>
        <section class="card"><div class="card-head"><h2>Target market</h2></div>
          <div class="form-grid">
            <label class="field"><span>Country</span><input type="text" name="target_country" value="${esc(s.target_country)}"></label>
            <div></div>
            <label class="field full"><span>Target cities <span class="hint">comma-separated</span></span><textarea name="target_cities" rows="3">${esc(s.target_cities.join(", "))}</textarea></label>
          </div>
        </section>
        <section class="card"><div class="card-head"><h2>Target industries</h2><button type="button" class="btn small" id="addind">+ Add industry</button></div>
          <div class="stack" id="inds" style="gap:8px">${indRows()}</div>
          <p class="small faint" style="margin-top:10px">Keywords map free-text industries (from CSV or discovery) onto these names.</p>
        </section>
      </div>
      <aside class="side">
        <section class="card"><div class="card-head"><h2>Thresholds &amp; windows</h2></div>
          <div class="stack">
            <label class="field"><span>Minimum opportunity score <span class="hint">qualifies a lead</span></span><input type="number" name="min_opportunity_score" min="0" max="100" value="${s.min_opportunity_score}"></label>
            <label class="field"><span>High-opportunity score</span><input type="number" name="high_opportunity_score" min="1" max="100" value="${s.high_opportunity_score}"></label>
            <label class="field"><span>Buying-signal recency window (days)</span><input type="number" name="buying_signal_window_days" min="1" max="365" value="${s.buying_signal_window_days}"></label>
            <label class="field"><span>Social activity window (days)</span><input type="number" name="social_activity_window_days" min="1" max="365" value="${s.social_activity_window_days}"></label>
            <label class="field"><span>"Posted recently" means within (days)</span><input type="number" name="recent_post_days" min="1" max="90" value="${s.recent_post_days}"></label>
            <label class="field"><span>Queue size (Today's N)</span><input type="number" name="today_count" min="5" max="100" value="${s.today_count}"></label>
            <label class="field"><span>Research cache (days)</span><input type="number" name="research_cache_days" min="0" max="90" value="${s.research_cache_days}"></label>
            <label class="check"><input type="checkbox" name="auto_qualify" ${s.auto_qualify ? "checked" : ""}> Auto-mark leads as Qualified when they reach the minimum score</label>
            <button class="btn primary" type="submit" id="save">Save &amp; rescore</button>
          </div>
        </section>
        <section class="card"><div class="card-head"><h2>Integrations</h2></div>
          <div class="list">
            <div class="list-item"><div class="grow"><div class="title">Claude AI analysis</div><div class="meta">${d.status.ai.configured ? `${esc(d.status.ai.model)} · effort ${esc(d.status.ai.effort)}` : "Set ANTHROPIC_API_KEY"}</div></div><span class="chip ${d.status.ai.configured ? "yes" : "no"}">${d.status.ai.configured ? "On" : "Off"}</span></div>
            ${d.status.search.map((p) => `<div class="list-item"><div class="grow"><div class="title">${esc(p.label)}</div><div class="meta">${esc(p.env)}</div></div><span class="chip ${p.configured ? "yes" : "no"}">${p.configured ? "On" : "Off"}</span></div>`).join("")}
            <div class="list-item"><div class="grow"><div class="title">Database</div><div class="meta">${esc(d.status.database)}</div></div></div>
          </div>
          <p class="small faint" style="margin-top:8px">Keys are read on the server from .env and never sent to the browser. Restart the server after changing them.</p>
        </section>
        <section class="card"><div class="card-head"><h2>AI usage</h2></div>
          ${d.ai_usage.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Model</th><th class="num">Runs</th><th class="num">Tokens</th><th class="num">≈ Cost</th></tr></thead><tbody>
            ${d.ai_usage.map((u) => `<tr><td>${esc(u.model)}</td><td class="num">${u.runs}</td><td class="num">${(u.input_tokens + u.output_tokens).toLocaleString()}</td><td class="num">$${Number(u.cost).toFixed(3)}</td></tr>`).join("")}</tbody></table></div>`
            : `<p class="muted small">No AI calls yet.</p>`}
          ${d.ai_errors ? `<p class="small faint" style="margin-top:6px">${d.ai_errors} failed call(s) logged.</p>` : ""}
        </section>
      </aside>
    </form>`;

  const total = () => {
    const sum = d.category_keys.reduce((a, k) => a + Number(el.querySelector(`[data-wn="${k}"]`).value || 0), 0);
    const box = el.querySelector("#total");
    box.className = "total " + (sum === 100 ? "ok" : "bad");
    box.innerHTML = `<span>Total</span><span class="num">${sum} / 100${sum === 100 ? "" : ` — ${sum > 100 ? "remove" : "add"} ${Math.abs(100 - sum)}`}</span>`;
    el.querySelector("#save").disabled = sum !== 100;
    return sum;
  };
  total();
  el.addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.w) { el.querySelector(`[data-wn="${t.dataset.w}"]`).value = t.value; total(); }
    if (t.dataset.wn) { el.querySelector(`[data-w="${t.dataset.wn}"]`).value = t.value; total(); }
  });
  const readInds = () => [...el.querySelectorAll(".ind-row")].map((r) => ({
    name: r.querySelector(".iname").value.trim(), customer_facing: r.querySelector(".icf").checked,
    keywords: r.querySelector(".kw").value.split(",").map((x) => x.trim()).filter(Boolean) })).filter((i) => i.name);
  el.querySelector("#addind").addEventListener("click", () => { industries = [...readInds(), { name: "", keywords: [], customer_facing: true }]; el.querySelector("#inds").innerHTML = indRows(); el.querySelector("#inds .ind-row:last-child .iname").focus(); });
  el.querySelector("#inds").addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (!b) return; industries = readInds().filter((_, i) => i !== Number(b.dataset.rm)); el.querySelector("#inds").innerHTML = indRows(); });

  el.querySelector("#sform").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (total() !== 100) return;
    const f = e.target;
    const body = {
      weights: Object.fromEntries(d.category_keys.map((k) => [k, Number(el.querySelector(`[data-wn="${k}"]`).value)])),
      target_country: f.target_country.value, target_cities: f.target_cities.value.split(",").map((x) => x.trim()).filter(Boolean),
      target_industries: readInds(),
      ...Object.fromEntries(["min_opportunity_score", "high_opportunity_score", "buying_signal_window_days", "social_activity_window_days", "recent_post_days", "today_count", "research_cache_days"].map((k) => [k, Number(f[k].value)])),
      auto_qualify: f.auto_qualify.checked,
    };
    await busy(el.querySelector("#save"), async () => {
      try {
        const r = await put("/api/settings", body);
        await loadMeta(true);
        toast(`Saved — ${r.rescored} lead(s) rescored`, "good");
      } catch (err) { toast(err.message, "bad"); }
    });
  });
}
