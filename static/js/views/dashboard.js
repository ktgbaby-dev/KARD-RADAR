import { get } from "../api.js";
import { esc, pill, ago, fmtDate, statusBadge } from "../ui.js";
import { prospectCard, bindProspectActions } from "./components.js";

function kpi(label, value, detail, href, hero = false) {
  return `<a class="kpi ${hero ? "hero" : ""}" href="${href}"><div class="label">${esc(label)}</div><div class="v">${Number(value).toLocaleString()}</div>${detail ? `<div class="d">${esc(detail)}</div>` : ""}</a>`;
}

function leadRow(l, meta, extra = "") {
  return `<a class="list-item" href="#/lead/${l.id}">
    ${pill(l.opportunity_score, "", meta)}
    <div class="grow"><div class="title">${esc(l.business_name)}</div><div class="meta">${esc([l.industry, l.city].filter(Boolean).join(" · "))}${extra ? " · " + extra : ""}</div></div>
    ${statusBadge(l.status)}</a>`;
}

export async function render(el, _params, { state, navigate }) {
  el.dataset.title = "Dashboard";
  const meta = state.meta;
  const d = await get("/api/dashboard");
  const c = d.counts;
  const funnel = [["Contacted", c.contacted], ["Replied", c.replies], ["Interested", c.interested], ["Meeting", c.meetings], ["Proposal", c.proposals], ["Won", c.won]];
  const fmax = Math.max(1, ...funnel.map((f) => f[1]));
  const aiOff = !state.status?.ai?.configured;
  const noSearch = !(state.status?.search || []).some((s) => s.configured);
  el.innerHTML = `
    <div class="page-head">
      <div><div class="eyebrow">Kard Radar</div><h1>Where Kard can create value right now</h1>
      <p class="sub">Leads ranked by evidence of digital friction and current growth activity, not follower count.</p></div>
      <div class="actions"><a class="btn" href="#/discover">Find leads</a><a class="btn primary" href="#/today">Open Today's 20</a></div>
    </div>
    ${aiOff || noSearch ? `<div class="notice info" style="margin-bottom:18px"><div>
      ${noSearch ? "<b>No search provider is configured,</b> so discovery works from pasted URLs and manual leads. " : ""}
      ${aiOff ? "<b>AI analysis is off</b> (no ANTHROPIC_API_KEY): scoring and template outreach still run from rules. " : ""}
      See <a href="#/settings">Strategy → Integrations</a>.</div></div>` : ""}
    <section class="kpis" aria-label="Pipeline totals">
      ${kpi("Total leads", c.total, `${c.discovered_7d} discovered this week`, "#/leads", true)}
      ${kpi("Qualified", c.qualified, `score ≥ ${meta.min_opportunity_score}`, `#/leads?min_score=${meta.min_opportunity_score}`)}
      ${kpi("High opportunity", c.high_opportunity, `score ≥ ${meta.high_opportunity_score}`, `#/leads?min_score=${meta.high_opportunity_score}`)}
      ${kpi("Contacted", c.contacted, "", "#/leads?contacted=1")}
      ${kpi("Replies", c.replies, "", "#/leads?status=Replied,Interested,Call/Meeting,Proposal,Won")}
      ${kpi("Interested", c.interested, "", "#/leads?status=Interested,Call/Meeting,Proposal")}
      ${kpi("Won", c.won, c.revenue ? `₦${Number(c.revenue).toLocaleString()} revenue` : "", "#/leads?status=Won")}
    </section>

    <section class="card" style="margin-bottom:18px">
      <div class="card-head"><h2>Today's 20 <span class="faint small">top ${d.today.length} shown</span></h2><a class="btn small" href="#/today">See all</a></div>
      ${d.today.length ? `<div class="queue" id="dash-queue">${d.today.map((l, i) => prospectCard(l, i, meta)).join("")}</div>`
        : `<div class="empty"><strong>No leads ready for outreach yet</strong>Add a lead or run discovery, then analyse it to fill the queue.</div>`}
    </section>

    <div class="grid cols-3">
      <section class="card"><div class="card-head"><h2>High opportunity</h2><a class="btn-ghost small" href="#/leads?min_score=${meta.high_opportunity_score}&contacted=0">All</a></div>
        <div class="list">${d.high_opportunity.map((l) => leadRow(l, meta, esc(l.top_pain || ""))).join("") || `<div class="empty">No uncontacted leads at ${meta.high_opportunity_score}+ yet.</div>`}</div></section>
      <section class="card"><div class="card-head"><h2>Recent buying signals</h2><a class="btn-ghost small" href="#/leads?sort=buying&has_buying=1">All</a></div>
        <div class="list">${d.recent_buying.map((l) => leadRow(l, meta, `${esc(l.latest_buying_signal)} · ${esc(ago(l.latest_buying_signal_at))}`)).join("") || `<div class="empty">No dated buying signals inside the window.</div>`}</div></section>
      <section class="card"><div class="card-head"><h2>Follow-ups</h2><a class="btn-ghost small" href="#/leads?followup_due=1&sort=followup">All</a></div>
        <div class="list">${d.follow_ups.map((l) => leadRow(l, meta, `due ${esc(fmtDate(l.follow_up_at))}`)).join("") || `<div class="empty">Nothing due in the next 2 days.</div>`}</div></section>
    </div>

    <div class="grid cols-2" style="margin-top:16px">
      <section class="card"><div class="card-head"><h2>Outreach funnel</h2><span class="faint small">all time</span></div>
        <div class="funnel">${funnel.map(([k, v]) => `<div class="funnel-row"><span>${k}</span><div class="bar" title="${k}: ${v}"><i style="width:${(v / fmax) * 100}%"></i></div><span class="num">${v}</span></div>`).join("")}</div>
        <p class="small faint" style="margin-top:12px">AI this month: ${d.ai_month.runs} run(s), ≈$${d.ai_month.cost_usd.toFixed(2)}</p>
      </section>
      <section class="card"><div class="card-head"><h2>Outcomes by score band</h2><span class="faint small">learning data</span></div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Score</th><th class="num">Leads</th><th class="num">Contacted</th><th class="num">Replied</th><th class="num">Interested</th><th class="num">Won</th></tr></thead>
        <tbody>${d.score_bands.map((b) => `<tr><td>${b.band}</td><td class="num">${b.leads}</td><td class="num">${b.contacted}</td><td class="num">${b.replied}</td><td class="num">${b.interested}</td><td class="num">${b.won}</td></tr>`).join("")}</tbody></table></div>
        <p class="small faint" style="margin-top:10px">As outcomes accumulate, this shows whether higher scores really convert. Export the full dataset from Import / export.</p>
      </section>
    </div>`;
  const q = el.querySelector("#dash-queue");
  if (q) bindProspectActions(q, new Map(d.today.map((l) => [l.id, l])), () => navigate("#/"));
}
