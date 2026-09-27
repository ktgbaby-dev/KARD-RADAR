import { get } from "../api.js";
import { esc } from "../ui.js";
import { prospectCard, bindProspectActions } from "./components.js";

export async function render(el, _params, { state }) {
  el.dataset.title = "Today's 20";
  const load = async () => {
    const d = await get("/api/today");
    el.innerHTML = `
      <div class="page-head">
        <div><div class="eyebrow">Outreach queue</div><h1>Today's ${esc(d.count)}</h1>
        <p class="sub">Ranked by opportunity score, how recent the buying signals are, evidence confidence, accessibility and due follow-ups. Leads already contacted drop out until a follow-up is due.</p></div>
        <div class="actions"><a class="btn" href="#/leads?status=Contacted&sort=followup">Awaiting replies</a></div>
      </div>
      ${d.leads.length ? `<div class="queue" id="queue">${d.leads.map((l, i) => prospectCard(l, i, state.meta)).join("")}</div>
        <details class="card flat fold" style="margin-top:18px"><summary>How is priority calculated?</summary>
          <div class="small muted" style="margin-top:8px">Priority = opportunity × 0.55 + buying-signal recency (≤7 days +20, inside window +12, undated +4) + confidence (High +10, Medium +5) + accessibility (up to +10) + follow-up due (+15).</div>
          <div class="table-wrap"><table class="data" style="margin-top:10px"><thead><tr><th>#</th><th>Business</th><th class="num">Priority</th><th>Breakdown</th></tr></thead><tbody>
          ${d.leads.map((l, i) => `<tr><td>${i + 1}</td><td><a href="#/lead/${l.id}">${esc(l.business_name)}</a></td><td class="num">${l.priority}</td><td class="small muted">${esc(l.priority_reasons.join(" · "))}</td></tr>`).join("")}
          </tbody></table></div></details>`
      : `<div class="empty"><strong>The queue is empty</strong>Leads appear here once they're scored, reachable and not already in a conversation. <a href="#/discover">Find leads</a> or <a href="#/new">add one</a>.</div>`}`;
    const q = el.querySelector("#queue");
    if (q) bindProspectActions(q, new Map(d.leads.map((l) => [l.id, l])), load);
  };
  await load();
}
