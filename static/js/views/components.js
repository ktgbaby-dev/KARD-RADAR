// Shared view components: prospect card (Today's 20) and its actions.
import { post } from "../api.js";
import { esc, ring, pill, safeUrl, contactLink, copyText, toast, modal, addDays, ICON, statusBadge, ago } from "../ui.js";

const CHANNEL_ORDER = ["instagram", "whatsapp", "tiktok", "email"];

export function bestMessage(l) {
  const o = l.outreach || {};
  const pref = l.instagram_handle ? "instagram" : (l.whatsapp || l.phone) ? "whatsapp" : l.tiktok_handle ? "tiktok" : "email";
  const m = o[pref] || CHANNEL_ORDER.map((c) => o[c]).find(Boolean);
  if (!m) return null;
  return { channel: m.channel, text: m.subject ? `Subject: ${m.subject}\n\n${m.body}` : m.body, generator: m.generator };
}

export function prospectCard(l, i, meta) {
  const ig = safeUrl(l.instagram_url), tt = safeUrl(l.tiktok_url), web = safeUrl(l.website_url);
  const c = contactLink(l);
  const msg = bestMessage(l);
  const loc = [l.city, l.state].filter(Boolean).join(", ");
  const due = l.priority_reasons?.some((r) => r.startsWith("Follow-up"));
  return `<article class="card pcard" data-lead="${l.id}">
    <span class="rank">#${i + 1}</span>
    <div class="pcard-head">
      ${ring(l.opportunity_score, { size: 58, meta })}
      <div style="min-width:0">
        <h3><a href="#/lead/${l.id}">${esc(l.business_name)}</a></h3>
        <div class="small muted">${esc(l.industry || "Industry unknown")}${loc ? " · " + esc(loc) : ""}</div>
        <div class="row" style="margin-top:6px;gap:6px">${statusBadge(l.status)}${due ? `<span class="chip bronze">Follow-up due</span>` : ""}${l.below_threshold ? `<span class="chip" title="Below the minimum opportunity score">Below min</span>` : ""}</div>
      </div>
    </div>
    <div class="scores">${pill(l.kard_fit, "Kard Fit", meta)}${pill(l.business_quality, "Quality", meta)}<span class="chip">${esc(l.confidence || "Low")} confidence</span></div>
    <div class="kv">
      <div><span class="k">Top reason</span><span class="v">${esc(l.top_reason || "—")}</span></div>
      <div><span class="k">Main Kard pain point</span><span class="v">${esc(l.top_pain || "None observed yet")}</span></div>
      <div><span class="k">Latest buying signal</span><span class="v">${l.latest_buying_signal ? esc(l.latest_buying_signal) + (l.latest_buying_signal_at ? ` <span class="faint">· ${esc(ago(l.latest_buying_signal_at))}</span>` : ` <span class="faint">· date unknown</span>`) : "None found"}</span></div>
    </div>
    <div class="pitch kv"><div><span class="k">Recommended pitch</span><span class="v">${esc(l.pitch_angle || "—")}</span></div></div>
    <div class="pcard-actions">
      ${ig ? `<a class="btn" href="${esc(ig)}" target="_blank" rel="noopener noreferrer" aria-label="Open Instagram">${ICON.ig}IG</a>` : `<button class="btn" disabled>${ICON.ig}IG</button>`}
      ${tt ? `<a class="btn" href="${esc(tt)}" target="_blank" rel="noopener noreferrer" aria-label="Open TikTok">${ICON.tt}TikTok</a>` : `<button class="btn" disabled>${ICON.tt}TikTok</button>`}
      ${web ? `<a class="btn" href="${esc(web)}" target="_blank" rel="noopener noreferrer" aria-label="Open website">${ICON.web}Site</a>` : `<button class="btn" disabled title="No website">${ICON.web}Site</button>`}
      ${c ? `<a class="btn" href="${esc(c.href)}" target="_blank" rel="noopener noreferrer">${ICON.chat}${esc(c.label === "WhatsApp" ? "WA" : c.label)}</a>` : `<button class="btn" disabled>${ICON.chat}Contact</button>`}
      <button class="btn primary wide" data-act="copy" ${msg ? "" : "disabled"}>${ICON.copy}Copy ${msg ? esc(msg.channel === "instagram" ? "IG DM" : msg.channel) : "outreach"}</button>
      <button class="btn wide" data-act="contacted">${ICON.check}Mark contacted</button>
      <button class="btn wide" data-act="followup" style="grid-column:1/-1">${ICON.clock}Set follow-up</button>
    </div>
  </article>`;
}

export function bindProspectActions(root, leadsById, onChange) {
  root.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const card = btn.closest("[data-lead]");
    const id = Number(card.dataset.lead);
    const l = leadsById.get(id);
    if (btn.dataset.act === "copy") {
      const m = bestMessage(l);
      if (m) copyText(m.text);
    } else if (btn.dataset.act === "contacted") {
      contactedModal(l, async () => { card.classList.add("done"); onChange && onChange(); });
    } else if (btn.dataset.act === "followup") {
      followupModal(l, onChange);
    }
  });
}

export function contactedModal(l, done) {
  const def = l.instagram_handle ? "instagram" : (l.whatsapp || l.phone) ? "whatsapp" : l.tiktok_handle ? "tiktok" : "email";
  modal(`<h2>Mark ${esc(l.business_name)} as contacted</h2>
    <form id="cm" class="stack">
      <label class="field"><span>Channel</span><select name="channel">
        ${["instagram", "tiktok", "whatsapp", "email", "phone", "in_person", "other"].map((c) => `<option value="${c}" ${c === def ? "selected" : ""}>${c.replace("_", " ")}</option>`).join("")}
      </select></label>
      <label class="field"><span>Follow up in</span><select name="follow_up_days">
        <option value="">No follow-up</option><option value="2">2 days</option><option value="3" selected>3 days</option><option value="5">5 days</option><option value="7">1 week</option><option value="14">2 weeks</option>
      </select></label>
      <label class="field"><span>Note <span class="hint">(optional)</span></span><input type="text" name="note" placeholder="e.g. Sent IG DM about the new collection"></label>
      <div class="actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">Mark contacted</button></div>
    </form>`, { onMount: (m, close) => {
    m.querySelector("#cm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        await post(`/api/leads/${l.id}/contacted`, { channel: f.channel.value, note: f.note.value, follow_up_days: f.follow_up_days.value ? Number(f.follow_up_days.value) : null });
        close();
        toast(`${l.business_name} marked as contacted`, "good");
        done && done();
      } catch (err) { toast(err.message, "bad"); }
    });
  } });
}

export function followupModal(l, done) {
  modal(`<h2>Follow-up for ${esc(l.business_name)}</h2>
    <form id="fm" class="stack">
      <div class="row">${[1, 3, 7, 14].map((d) => `<button type="button" class="btn small" data-days="${d}">+${d}d</button>`).join("")}</div>
      <label class="field"><span>Date</span><input type="date" name="date" value="${esc(l.follow_up_at || addDays(3))}" required></label>
      <label class="field"><span>Note <span class="hint">(optional)</span></span><input type="text" name="note"></label>
      <div class="actions"><button type="button" class="btn" data-clear>Clear follow-up</button><span class="spacer"></span><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">Save</button></div>
    </form>`, { onMount: (m, close) => {
    const f = m.querySelector("#fm");
    m.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => { f.date.value = addDays(Number(b.dataset.days)); }));
    const save = async (date) => {
      try {
        await post(`/api/leads/${l.id}/followup`, { date, note: f.note.value });
        close();
        toast(date ? `Follow-up set for ${date}` : "Follow-up cleared", "good");
        done && done();
      } catch (err) { toast(err.message, "bad"); }
    };
    m.querySelector("[data-clear]").addEventListener("click", () => save(null));
    f.addEventListener("submit", (e) => { e.preventDefault(); save(f.date.value); });
  } });
}
