import { get, post, qs } from "../api.js";
import { esc, pill, statusBadge, confBadge, channels, ago, toast, busy, fmtDate } from "../ui.js";

const TRI = [["", "Any"], ["1", "Yes"], ["0", "No"]];
const FILTER_KEYS = ["q", "city", "industry", "status", "confidence", "min_score", "max_score", "min_fit", "min_quality",
  "min_social_pct", "min_gap_pct", "min_buying_pct", "has_buying", "buying_recent_days", "has_website", "website_unknown",
  "has_instagram", "has_tiktok", "has_whatsapp", "has_email", "contacted", "followup_due", "recent_days", "scored", "sort", "page"];

function sel(name, options, value) {
  return `<select name="${name}">${options.map(([v, l]) => `<option value="${esc(v)}" ${String(value ?? "") === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
}

export async function render(el, params, { state, navigate }) {
  el.dataset.title = "Leads";
  const meta = state.meta;
  const f = Object.fromEntries(FILTER_KEYS.filter((k) => params[k] !== undefined).map((k) => [k, params[k]]));
  const data = await get("/api/leads" + qs({ ...f, per_page: 50 }));
  const active = Object.keys(f).filter((k) => !["sort", "page"].includes(k)).length;
  const pct = [["", "Any"], ["50", "≥ 50%"], ["75", "≥ 75%"], ["100", "Full marks"]];
  el.innerHTML = `
    <div class="page-head">
      <div><div class="eyebrow">Lead database</div><h1>Leads <span class="faint num" style="font-size:20px">${data.total.toLocaleString()}</span></h1></div>
      <div class="actions">
        <button class="btn filter-toggle" id="ftoggle" type="button">Filters${active ? ` (${active})` : ""}</button>
        <a class="btn" href="/api/export.csv${esc(qs(f))}" download>Export CSV</a>
        <a class="btn primary" href="#/new">+ Add lead</a>
      </div>
    </div>
    <div class="leads-layout">
      <form class="card filters" id="filters" aria-label="Filters">
        <div class="row"><h2 style="flex:1">Filters</h2>${active ? `<a class="btn-ghost small" href="#/leads">Reset</a>` : ""}</div>
        <label class="field"><span>Search</span><input type="search" name="q" value="${esc(f.q || "")}" placeholder="Name, @handle, domain, notes"></label>
        <label class="field"><span>Sort by</span>${sel("sort", [["opportunity", "Opportunity score"], ["fit", "Kard Fit"], ["quality", "Business Quality"], ["buying", "Latest buying signal"], ["discovered", "Recently discovered"], ["followup", "Follow-up date"], ["name", "Name"]], f.sort || "opportunity")}</label>
        <label class="field"><span>Location</span>${sel("city", [["", "Any city"], ...meta.cities.map((c) => [c, c])], f.city)}</label>
        <label class="field"><span>Industry</span>${sel("industry", [["", "Any industry"], ...meta.industries.map((c) => [c, c])], f.industry)}</label>
        <label class="field"><span>Status</span>${sel("status", [["", "Any status"], ...meta.statuses.map((s) => [s, s])], f.status && !f.status.includes(",") ? f.status : (f.status ? f.status : ""))}</label>
        <div class="field"><span>Opportunity score</span><div class="pair"><input type="number" name="min_score" min="0" max="100" placeholder="Min" value="${esc(f.min_score || "")}"><input type="number" name="max_score" min="0" max="100" placeholder="Max" value="${esc(f.max_score || "")}"></div></div>
        <div class="pair"><label class="field"><span>Min Kard Fit</span><input type="number" name="min_fit" min="0" max="100" value="${esc(f.min_fit || "")}"></label>
        <label class="field"><span>Min Quality</span><input type="number" name="min_quality" min="0" max="100" value="${esc(f.min_quality || "")}"></label></div>
        <label class="field"><span>Social activity</span>${sel("min_social_pct", pct, f.min_social_pct)}</label>
        <label class="field"><span>Digital gap</span>${sel("min_gap_pct", pct, f.min_gap_pct)}</label>
        <label class="field"><span>Buying signals</span>${sel("buying_recent_days", [["", "Any"], ["7", "Signal in last 7 days"], ["30", "Signal in last 30 days"]], f.buying_recent_days)}</label>
        <label class="field"><span>Has any buying signal</span>${sel("has_buying", TRI, f.has_buying)}</label>
        <label class="field"><span>Website</span>${sel("has_website", [["", "Any"], ["1", "Has website"], ["0", "No website (confirmed)"]], f.has_website)}</label>
        <div class="pair"><label class="field"><span>Instagram</span>${sel("has_instagram", TRI, f.has_instagram)}</label><label class="field"><span>TikTok</span>${sel("has_tiktok", TRI, f.has_tiktok)}</label></div>
        <div class="pair"><label class="field"><span>WhatsApp</span>${sel("has_whatsapp", TRI, f.has_whatsapp)}</label><label class="field"><span>Email</span>${sel("has_email", TRI, f.has_email)}</label></div>
        <label class="field"><span>Contacted</span>${sel("contacted", [["", "Any"], ["1", "Contacted"], ["0", "Not contacted"]], f.contacted)}</label>
        <label class="field"><span>Confidence</span>${sel("confidence", [["", "Any"], ["High", "High"], ["Medium", "Medium"], ["Low", "Low"]], f.confidence)}</label>
        <label class="field"><span>Discovered</span>${sel("recent_days", [["", "Any time"], ["1", "Today"], ["7", "Last 7 days"], ["30", "Last 30 days"]], f.recent_days)}</label>
        <label class="check"><input type="checkbox" name="followup_due" ${f.followup_due ? "checked" : ""}> Follow-up due</label>
        <label class="check"><input type="checkbox" name="unscored" ${f.scored === "0" ? "checked" : ""}> Only unscored leads</label>
        <button class="btn primary" type="submit">Apply filters</button>
      </form>
      <section style="min-width:0">
        ${data.leads.length ? `<div class="card" style="padding:0;overflow:hidden"><table class="lead-table">
          <thead><tr><th><input type="checkbox" id="selall" aria-label="Select all"></th><th>Business</th><th>Scores</th><th>Why</th><th>Channels</th><th>Status</th></tr></thead>
          <tbody>${data.leads.map((l) => `<tr>
            <td class="sel"><input type="checkbox" class="rowsel" value="${l.id}" aria-label="Select ${esc(l.business_name)}"></td>
            <td class="biz"><a href="#/lead/${l.id}">${esc(l.business_name)}</a><div class="meta">${esc([l.industry, l.city].filter(Boolean).join(" · ") || "—")} · ${esc(ago(l.discovered_at))}</div></td>
            <td class="scores-cell"><div class="row" style="gap:6px">${pill(l.opportunity_score, "Opp", meta)}${pill(l.kard_fit, "Fit", meta)}${pill(l.business_quality, "Qual", meta)}</div><div style="margin-top:6px">${l.opportunity_score === null ? `<span class="small faint">Not analysed</span>` : confBadge(l.confidence)}</div></td>
            <td><div class="reason">${esc(l.top_reason || l.top_pain || "—")}</div>${l.latest_buying_signal ? `<div class="small" style="margin-top:4px"><span class="chip buy">${esc(l.latest_buying_signal)}${l.latest_buying_signal_at ? " · " + esc(ago(l.latest_buying_signal_at)) : ""}</span></div>` : ""}</td>
            <td>${channels(l)}</td>
            <td>${statusBadge(l.status)}${l.follow_up_at ? `<div class="small faint" style="margin-top:4px">Follow-up ${esc(fmtDate(l.follow_up_at))}</div>` : ""}</td>
          </tr>`).join("")}</tbody></table></div>
          <div class="pager"><span class="small faint">Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.per_page))}</span>
            <div class="row">${data.page > 1 ? `<a class="btn small" href="#/leads${esc(qs({ ...f, page: data.page - 1 }))}">Previous</a>` : ""}${data.page * data.per_page < data.total ? `<a class="btn small" href="#/leads${esc(qs({ ...f, page: data.page + 1 }))}">Next</a>` : ""}</div></div>
          <div class="bulkbar" id="bulk" hidden><b id="bulkn"></b><span class="spacer"></span>
            <button class="btn small" data-bulk="research">Re-research</button>
            <select id="bulkstatus" aria-label="Set status" style="width:auto;min-height:36px">${meta.statuses.map((s) => `<option>${esc(s)}</option>`).join("")}</select>
            <button class="btn small" data-bulk="status">Set status</button>
            <button class="btn small danger" data-bulk="archive">Archive</button></div>`
        : `<div class="empty"><strong>No leads match</strong>${active ? `Try widening the filters or <a href="#/leads">reset them</a>.` : `Start by <a href="#/discover">finding leads</a>, <a href="#/new">adding one</a> or <a href="#/data">importing a CSV</a>.`}</div>`}
      </section>
    </div>`;

  const form = el.querySelector("#filters");
  if (active) form.classList.add("open");
  el.querySelector("#ftoggle").addEventListener("click", () => form.classList.toggle("open"));
  form.addEventListener("change", (e) => { if (e.target.tagName === "SELECT" && window.innerWidth > 1100) form.requestSubmit(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const out = {};
    new FormData(form).forEach((v, k) => { if (v && !["followup_due", "unscored"].includes(k)) out[k] = v; });
    if (form.followup_due.checked) out.followup_due = 1;
    if (form.unscored.checked) out.scored = 0;
    if (out.sort === "opportunity") delete out.sort;
    navigate("#/leads" + qs(out));
  });

  const bulk = el.querySelector("#bulk");
  if (!bulk) return;
  const selected = () => [...el.querySelectorAll(".rowsel:checked")].map((c) => Number(c.value));
  const sync = () => { const n = selected().length; bulk.hidden = !n; el.querySelector("#bulkn").textContent = `${n} selected`; };
  el.querySelector("#selall").addEventListener("change", (e) => { el.querySelectorAll(".rowsel").forEach((c) => { c.checked = e.target.checked; }); sync(); });
  el.querySelectorAll(".rowsel").forEach((c) => c.addEventListener("change", sync));
  bulk.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-bulk]");
    if (!b) return;
    await busy(b, async () => {
      try {
        const r = await post("/api/leads/bulk", { ids: selected(), action: b.dataset.bulk, status: el.querySelector("#bulkstatus").value });
        toast(`${r.done} lead(s) updated${r.errors.length ? `, ${r.errors.length} skipped` : ""}`, r.errors.length ? "" : "good");
        navigate(location.hash);
      } catch (err) { toast(err.message, "bad"); }
    });
  });
}
