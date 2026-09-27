import { get, post, patch, put, del } from "../api.js";
import { esc, ring, meterHtml, confBadge, statusBadge, detBadge, safeUrl, fmtDate, ago, compact, toast, busy, copyText,
  modal, confirmModal, waLink, formData, addDays, ICON, today } from "../ui.js";
import { contactedModal, followupModal } from "./components.js";

const FIELD_LABEL = {
  website_status: "Website status", website_url: "Website", website_quality: "Website checks", link_in_bio_url: "Bio link",
  instagram_url: "Instagram", tiktok_url: "TikTok", industry: "Industry", city: "City", country: "Country", phone: "Phone",
  whatsapp: "WhatsApp", email: "Email", founder_name: "Founder", profile_bio: "Bio", followers_instagram: "IG followers",
};
const KIND_LABEL = { website: "Website", link_in_bio: "Bio link page", bio: "Profile bio", post: "Post", search_snippet: "Search result",
  places: "Google Maps", manual_note: "Note", social_stats: "Profile stats", engagement: "Engagement", website_check: "Website check" };
const WEBSITE_STATUS = { has_website: "Has website", none_found: "No website found", parked: "Parked / placeholder", unreachable: "Did not load", unknown: "Unknown — not checked" };
const LIB_TYPE = { own_website: "Own website", generic_link_page: "Generic link page", whatsapp: "Direct WhatsApp link", storefront: "Online storefront",
  shortener: "Short link", social: "Another social profile", none: "No link in bio", unknown: "Unknown" };

function refs(evidence) {
  return (evidence || []).map((r) => {
    if (r.startsWith("obs:")) return `<a class="ev-ref" href="#obs-${esc(r.slice(4))}" data-jump="${esc(r.slice(4))}">${esc(r)}</a>`;
    if (r.startsWith("field:")) return `<span class="ev-ref" title="Value on the lead record">${esc(FIELD_LABEL[r.slice(6)] || r.slice(6))}</span>`;
    return `<span class="ev-ref">${esc(r)}</span>`;
  }).join(" ");
}

function linksHtml(l) {
  const out = [];
  const a = (href, label, icon) => { const u = safeUrl(href); if (u) out.push(`<a class="btn small" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${icon || ""}${esc(label)}</a>`); };
  a(l.instagram_url, "@" + l.instagram_handle, ICON.ig);
  a(l.tiktok_url, "@" + l.tiktok_handle, ICON.tt);
  a(l.website_url, l.website_domain || "Website", ICON.web);
  a(l.link_in_bio_url, "Bio link", ICON.ext);
  Object.entries(l.other_socials || {}).forEach(([k, v]) => a(v, k, ICON.ext));
  if (l.whatsapp) out.push(`<a class="btn small" href="${esc(waLink(l.whatsapp))}" target="_blank" rel="noopener noreferrer">${ICON.chat}${esc(l.whatsapp)}</a>`);
  else if (l.phone) out.push(`<a class="btn small" href="tel:${esc(l.phone)}">${ICON.chat}${esc(l.phone)}</a>`);
  if (l.email) out.push(`<a class="btn small" href="mailto:${esc(l.email)}">@ ${esc(l.email)}</a>`);
  return out.join("") || `<span class="small faint">No channels on record yet</span>`;
}

function notices(l, st) {
  const out = [];
  const bd = l.score_breakdown || {};
  if (!l.last_scored_at) out.push(`<div class="notice warn"><div><b>Not analysed yet.</b> Run Kard analysis to collect evidence and score this lead.</div></div>`);
  if (l.website_suggestion) out.push(`<div class="notice info"><div style="flex:1"><b>Possible website found:</b> <a href="${esc(safeUrl(l.website_suggestion))}" target="_blank" rel="noopener noreferrer">${esc(l.website_suggestion)}</a>. Is this the business's site?</div>
    <div class="row"><button class="btn small primary" data-web="accept_suggestion">Yes, use it</button><button class="btn small" data-web="reject_suggestion">Not theirs</button></div></div>`);
  if (l.website_status === "unknown" && !l.website_url && l.last_scored_at) out.push(`<div class="notice"><div style="flex:1"><b>Website: Unknown.</b> It hasn't been checked, so no points are given either way.</div>
    <div class="row"><button class="btn small" data-act="edit">Add website</button><button class="btn small" data-web="confirm_none">I checked — no website</button></div></div>`);
  if (bd.needs_evidence) out.push(`<div class="notice warn"><div><b>Outreach needs evidence.</b> No buying signal or pain point has been observed yet, so drafts can't reference anything specific. Add a social snapshot or evidence below.</div></div>`);
  if (l.ai_status === "stale") out.push(`<div class="notice"><div style="flex:1"><b>AI analysis is out of date</b> — new evidence was added since ${esc(ago(l.last_analyzed_at))}.</div>${st.ai?.configured ? `<button class="btn small" data-act="ai">Update AI analysis</button>` : ""}</div>`);
  return out.join("");
}

function whyHtml(l, bd) {
  const items = (bd.categories || []).flatMap((c) => c.items.filter((i) => i.points > 0).map((i) => ({ ...i, cat: c.label })));
  items.sort((a, b) => b.points - a.points);
  const ai = l.ai_summary ? `<div class="ai-summary"><div class="row" style="margin-bottom:6px">${detBadge("ai")}<span class="small faint">Summary by ${esc(l.ai_model)} · ${esc(ago(l.last_analyzed_at))}</span></div>${esc(l.ai_summary)}</div>` : "";
  const list = items.length ? `<ul class="why-list">${items.map((i) => `<li><span class="pts">+${i.points}</span><div><b>${esc(i.label)}</b>${i.detail ? ` — <span class="muted">${esc(i.detail)}</span>` : ""} ${i.detector !== "rule" ? detBadge(i.detector) : ""} ${refs(i.evidence)}</div></li>`).join("")}</ul>`
    : `<div class="empty">No positive signals observed yet.</div>`;
  const unknowns = (bd.unknowns || []);
  return `${ai}${ai ? '<div class="divider"></div>' : ""}${list}
    ${unknowns.length ? `<details class="fold" style="margin-top:12px"><summary><span class="small">${unknowns.length} check(s) are Unknown — no points given</span></summary><ul class="checks">${unknowns.map((u) => `<li class="bad">${esc(u)}</li>`).join("")}</ul></details>` : ""}`;
}

function painHtml(l, bd) {
  const rule = bd.pain_points || [];
  const ai = (l.ai_pain_points || []).map((p) => ({ problem: p.problem, evidence: p.evidence, detector: "ai" }));
  const all = [...rule, ...ai];
  return `<h3 class="section-title" style="margin-bottom:10px">Detected Kard problems</h3>
    ${all.length ? `<ol class="pain-list">${all.map((p) => `<li><div><b>${esc(p.problem)}</b> ${p.detector === "ai" ? detBadge("ai") : ""}<div class="ev">${p.detail ? esc(p.detail) + " " : ""}${refs(p.evidence)}</div></div></li>`).join("")}</ol>`
      : `<div class="empty">No customer-journey friction observed yet.</div>`}
    <h3 class="section-title" style="margin:18px 0 8px">How Kard could help</h3>
    <p>${esc(l.how_kard_helps || "—")}</p>`;
}

function buyingHtml(bd) {
  const cat = (bd.categories || []).find((c) => c.key === "buying_signals");
  const items = (cat?.items || []).filter((i) => i.code !== "none");
  if (!items.length) return `<div class="empty"><strong>No buying signals found</strong>Add recent posts (with dates) in a social snapshot to detect launches, collections, promos and events.</div>`;
  return `<div class="items">${items.map((i) => `<div class="item ${i.state === "yes" ? "yes" : ""}">
    <span class="p">+${i.points}</span>
    <div><div class="l">${esc(i.label)} ${i.detector !== "rule" ? detBadge(i.detector) : ""}</div>
      <div class="dt">${esc(i.detail)}</div>
      <div class="small faint" style="margin-top:3px">${i.date ? esc(fmtDate(i.date)) + " · " + esc(i.note) : esc(i.note)} ${refs(i.evidence)}</div></div>
    <span></span></div>`).join("")}</div>`;
}

function presenceHtml(l, bd) {
  const notes = l.website_quality_notes || [];
  const sig = {};
  (bd.categories || []).forEach((c) => c.items.forEach((i) => { sig[i.code] = i; }));
  const friction = (bd.pain_points || []);
  return `<div class="presence">
    <div class="box"><div class="k">Website</div><div><b>${esc(WEBSITE_STATUS[l.website_status] || l.website_status)}</b>${l.website_quality !== null && l.website_quality !== undefined ? ` · quality <span class="num">${l.website_quality}/100</span>` : ""}</div>
      ${l.website_evidence ? `<div class="small muted" style="margin-top:4px">${esc(l.website_evidence)}</div>` : ""}
      ${notes.length ? `<ul class="checks">${notes.map((n) => `<li class="${n.ok ? "" : "bad"}">${esc(n.text)}</li>`).join("")}</ul>` : ""}</div>
    <div class="box"><div class="k">Socials</div>
      <div>${l.instagram_handle ? `Instagram @${esc(l.instagram_handle)}${l.followers_instagram !== null ? ` · ${compact(l.followers_instagram)} followers` : " · followers unknown"}` : "No Instagram on record"}</div>
      <div>${l.tiktok_handle ? `TikTok @${esc(l.tiktok_handle)}${l.followers_tiktok !== null ? ` · ${compact(l.followers_tiktok)} followers` : " · followers unknown"}` : "No TikTok on record"}</div>
      ${l.followers_source ? `<div class="small faint">Follower source: ${esc(l.followers_source)} (supporting signal only)</div>` : ""}
      ${Object.keys(l.other_socials || {}).length ? `<div class="small muted">Also: ${esc(Object.keys(l.other_socials).join(", "))}</div>` : ""}</div>
    <div class="box"><div class="k">Link in bio</div><div><b>${esc(LIB_TYPE[l.link_in_bio_type] || "Unknown")}</b></div>
      ${l.link_in_bio_url ? `<div class="small muted" style="word-break:break-all">${esc(l.link_in_bio_url)}</div>` : ""}
      ${sig.weak_link_in_bio ? `<div class="small" style="margin-top:4px">${esc(sig.weak_link_in_bio.detail)}</div>` : ""}</div>
    <div class="box"><div class="k">Customer journey</div>
      ${friction.length ? `<ul class="checks">${friction.map((p) => `<li class="bad">${esc(p.problem)}</li>`).join("")}</ul>` : `<div class="muted small">No friction observed yet.</div>`}</div>
  </div>`;
}

function breakdownHtml(bd, weights) {
  if (!bd.categories) return `<div class="empty">Not scored yet.</div>`;
  const opt = (i) => {
    if (i.code === "none") return "";
    const v = i.detector === "manual" ? i.state : "";
    return `<select data-override="${esc(i.code)}" aria-label="Override ${esc(i.label)}">
      <option value="auto" ${!v ? "selected" : ""}>Auto</option><option value="yes" ${v === "yes" ? "selected" : ""}>Yes</option>
      <option value="no" ${v === "no" ? "selected" : ""}>No</option><option value="unknown" ${v === "unknown" ? "selected" : ""}>Unknown</option></select>`;
  };
  return bd.categories.map((c) => `<div class="cat">
    <div class="cat-head"><h3>${esc(c.label)}</h3><span class="num small">${c.raw}/${c.cap} raw → <b>${c.points}</b>/${c.weight}</span>
      <div class="bar ${c.raw / c.cap >= 0.75 ? "high" : c.raw / c.cap >= 0.45 ? "mid" : ""}"><i style="width:${(c.raw / c.cap) * 100}%"></i></div></div>
    ${c.capped ? `<div class="small faint" style="margin-bottom:6px">Category capped at ${c.cap} raw points.</div>` : ""}
    <div class="items">${c.items.map((i) => `<div class="item ${i.state}">
      <span class="p">${i.points ? "+" + i.points : "0"}</span>
      <div><div class="l">${esc(i.label)} ${i.detector !== "rule" ? detBadge(i.detector) : ""}</div>
        ${i.detail ? `<div class="dt">${esc(i.detail)}</div>` : ""}${i.evidence?.length ? `<div style="margin-top:3px">${refs(i.evidence)}</div>` : ""}</div>
      <div class="tools">${opt(i)}</div></div>`).join("")}</div></div>`).join("") +
    `<div class="cat"><div class="cat-head"><h3>Kard Fit</h3><span class="num small"><b>${bd.kard_fit}</b>/100</span></div>
      <div class="grid" style="gap:10px">${bd.kard_fit_components.map((x) => meterHtml(x.label, x.points, x.max, { detail: x.detail })).join("")}</div></div>
    <div class="cat"><div class="cat-head"><h3>Business Quality</h3><span class="num small"><b>${bd.business_quality}</b>/100</span></div>
      <div class="grid" style="gap:10px">${bd.quality_components.map((x) => meterHtml(x.label, x.points, x.max, { detail: x.detail })).join("")}</div></div>
    <p class="small faint">Weights: ${Object.entries(weights || {}).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")}. Scores are computed by rules from the signals above — AI can only propose signals with cited evidence.</p>`;
}

function evidenceHtml(l) {
  const obs = l.observations || [];
  return `<div class="evidence">${obs.length ? obs.map((o) => `<div class="ev-item" id="obs-${o.id}">
      <div class="h"><b>obs:${o.id}</b><span>${esc(KIND_LABEL[o.kind] || o.kind)}</span>${o.meta?.platform ? `<span>${esc(o.meta.platform)}</span>` : ""}<span>· ${esc(o.source)}</span>
        ${o.observed_at ? `<span>· dated ${esc(fmtDate(o.observed_at))}</span>` : `<span>· collected ${esc(ago(o.collected_at))}</span>`}
        ${safeUrl(o.source_url) ? `<a href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener noreferrer">source ↗</a>` : ""}
        <span class="spacer"></span>${["manual", "manual snapshot"].includes(o.source) ? `<button class="btn-ghost small" data-delobs="${o.id}" aria-label="Remove evidence">Remove</button>` : ""}</div>
      <div class="c ${o.content.length > 400 ? "clamp" : ""}">${esc(o.content)}</div></div>`).join("")
    : `<div class="empty">No evidence collected yet.</div>`}</div>`;
}

function outreachHtml(l, channel, prefer) {
  const msgs = l.outreach || [];
  const pick = (gen) => msgs.find((m) => m.channel === channel && m.generator === gen);
  const ai = pick("ai"), tpl = pick("template");
  const m = (prefer === "template" ? tpl || ai : ai || tpl);
  const tabs = ["instagram", "tiktok", "whatsapp", "email"].map((c) => `<button type="button" class="${c === channel ? "on" : ""}" data-ch="${c}">${{ instagram: "Instagram", tiktok: "TikTok", whatsapp: "WhatsApp", email: "Email" }[c]}</button>`).join("");
  let open = "";
  if (m) {
    if (channel === "instagram" && safeUrl(l.instagram_url)) open = `<a class="btn" href="${esc(l.instagram_url)}" target="_blank" rel="noopener noreferrer">${ICON.ig}Open profile</a>`;
    if (channel === "tiktok" && safeUrl(l.tiktok_url)) open = `<a class="btn" href="${esc(l.tiktok_url)}" target="_blank" rel="noopener noreferrer">${ICON.tt}Open profile</a>`;
    if (channel === "whatsapp" && (l.whatsapp || l.phone)) open = `<a class="btn" href="${esc(waLink(l.whatsapp || l.phone, m.body))}" target="_blank" rel="noopener noreferrer">${ICON.chat}Open in WhatsApp</a>`;
    if (channel === "email" && l.email) open = `<a class="btn" href="mailto:${esc(l.email)}?subject=${encodeURIComponent(m.subject || "")}&body=${encodeURIComponent(m.body)}">@ Open email</a>`;
  }
  return `<div class="seg" role="tablist">${tabs}</div>
    ${m ? `<div class="row small faint">${detBadge(m.generator === "ai" ? "ai" : "rule")}<span>${m.generator === "ai" ? "AI draft" : "Template from observed signals"}</span>
        ${ai && tpl ? `<span class="spacer"></span><button class="btn-ghost small" data-prefer="${m.generator === "ai" ? "template" : "ai"}">Show ${m.generator === "ai" ? "template" : "AI"} version</button>` : ""}</div>
      <div class="msg">${m.subject ? `<div class="msg-subject">${esc(m.subject)}</div>` : ""}${esc(m.body)}</div>
      <div class="row"><button class="btn primary" data-copy>${ICON.copy}Copy</button>${open}</div>`
    : `<div class="empty">No draft yet — run Kard analysis.</div>`}`;
}

function activityHtml(l, meta) {
  const o = l.outcome || {};
  return `<div class="stack">
    <div class="row"><label class="field" style="flex:1"><span>Status</span><select id="status">${meta.statuses.map((s) => `<option ${s === l.status ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label></div>
    <div class="grid cols-2" style="gap:8px">
      <button class="btn" data-act="contacted">${ICON.check}Contacted</button>
      <button class="btn" data-act="replied">${ICON.chat}Replied</button>
      <button class="btn" data-act="followup" style="grid-column:1/-1">${ICON.clock}${l.follow_up_at ? "Follow-up " + esc(fmtDate(l.follow_up_at)) : "Set follow-up"}</button>
    </div>
    <div class="small muted">${l.contacted_at ? `Contacted ${esc(fmtDate(l.contacted_at))}${l.last_contact_channel ? " via " + esc(l.last_contact_channel) : ""}` : "Not contacted yet"}</div>
    <form id="noteform" class="stack" style="gap:8px"><label class="field"><span>Add a note</span><textarea name="text" rows="2" placeholder="Call notes, objections, next steps…"></textarea></label><button class="btn small" type="submit">Save note</button></form>
    <details class="fold"><summary>Outcome &amp; revenue</summary>
      <form id="outcomeform" class="stack" style="margin-top:8px;gap:10px">
        <div class="chips">${["contacted", "responded", "interested", "meeting", "proposal", "purchased", "lost"].map((k) => `<span class="chip ${o[k] ? "yes" : "no"}">${k}</span>`).join("")}</div>
        <div class="grid cols-2" style="gap:8px"><label class="field"><span>Revenue (₦)</span><input type="number" name="revenue" min="0" step="1000" value="${esc(o.revenue ?? "")}"></label>
        <label class="field"><span>Package</span><input type="text" name="package" value="${esc(o.package || "")}" placeholder="e.g. Kard Pro"></label></div>
        <button class="btn small" type="submit">Save outcome</button>
        <p class="small faint">Funnel flags update from status changes. Scores at first contact are frozen for learning.</p>
      </form></details>
    <div><div class="label" style="margin-bottom:6px">Timeline</div><ul class="timeline">${(l.activities || []).map((a) => `<li class="${esc(a.type)}"><div>
      <div>${a.type === "status" ? `Status: ${esc(a.from_status)} → <b>${esc(a.to_status)}</b>${a.detail ? " — " + esc(a.detail) : ""}` : esc(a.detail || a.type)}</div>
      <div class="when">${esc(a.type.replace("_", " "))} · ${esc(fmtDate(a.created_at))} ${esc(new Date(a.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }))}</div></div></li>`).join("")}</ul></div>
  </div>`;
}

function editModal(l, meta, onSaved) {
  modal(`<h2>Edit ${esc(l.business_name)}</h2>
    <form id="editform" class="form-grid">
      <label class="field full"><span>Business name</span><input type="text" name="business_name" value="${esc(l.business_name)}" required></label>
      <label class="field"><span>Industry</span><input type="text" name="industry" list="ind-list" value="${esc(l.industry)}"></label>
      <label class="field"><span>Subcategory</span><input type="text" name="subcategory" value="${esc(l.subcategory)}"></label>
      <label class="field"><span>City</span><input type="text" name="city" list="city-list" value="${esc(l.city)}"></label>
      <label class="field"><span>State</span><input type="text" name="state" value="${esc(l.state)}"></label>
      <label class="field"><span>Country</span><input type="text" name="country" value="${esc(l.country)}"></label>
      <label class="field"><span>Founder / owner</span><input type="text" name="founder_name" value="${esc(l.founder_name)}"></label>
      <label class="field"><span>Instagram</span><input type="text" name="instagram_url" value="${esc(l.instagram_url)}" placeholder="@handle or URL"></label>
      <label class="field"><span>TikTok</span><input type="text" name="tiktok_url" value="${esc(l.tiktok_url)}" placeholder="@handle or URL"></label>
      <label class="field"><span>Website</span><input type="url" name="website_url" value="${esc(l.website_url)}" placeholder="https://"></label>
      <label class="field"><span>Link in bio</span><input type="url" name="link_in_bio_url" value="${esc(l.link_in_bio_url)}" placeholder="https://"></label>
      <label class="field"><span>WhatsApp</span><input type="tel" name="whatsapp" value="${esc(l.whatsapp)}"></label>
      <label class="field"><span>Phone</span><input type="tel" name="phone" value="${esc(l.phone)}"></label>
      <label class="field"><span>Email</span><input type="email" name="email" value="${esc(l.email)}"></label>
      <label class="field"><span>Address</span><input type="text" name="address" value="${esc(l.address)}"></label>
      <label class="field full"><span>Notes</span><textarea name="notes" rows="3">${esc(l.notes)}</textarea></label>
      <datalist id="ind-list">${meta.industries.map((i) => `<option value="${esc(i)}">`).join("")}</datalist>
      <datalist id="city-list">${meta.cities.map((i) => `<option value="${esc(i)}">`).join("")}</datalist>
      <div class="actions full"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">Save &amp; rescore</button></div>
    </form>`, { onMount: (m, close) => {
    m.querySelector("#editform").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = e.target.querySelector('button[type="submit"]');
      await busy(btn, async () => {
        try {
          const lead = await patch(`/api/leads/${l.id}`, formData(e.target));
          close(); toast("Saved and rescored", "good"); onSaved(lead);
        } catch (err) {
          toast(err.status === 409 ? `That matches an existing lead: ${err.data.matches.map((x) => x.business_name).join(", ")}` : err.message, "bad");
        }
      });
    });
  } });
}

function snapshotForm(l) {
  const plat = l.instagram_handle || !l.tiktok_handle ? "instagram" : "tiktok";
  return `<form id="snapform" class="form-grid">
    <label class="field"><span>Platform</span><select name="platform"><option value="instagram" ${plat === "instagram" ? "selected" : ""}>Instagram</option><option value="tiktok" ${plat === "tiktok" ? "selected" : ""}>TikTok</option></select></label>
    <label class="field"><span>Followers</span><input type="text" name="followers" placeholder="e.g. 5.2k"></label>
    <label class="field"><span>Total posts</span><input type="number" name="posts_count" min="0"></label>
    <label class="field"><span>Posts per week <span class="hint">(approx.)</span></span><input type="number" name="posts_per_week" min="0" step="0.5"></label>
    <label class="field full"><span>Bio</span><textarea name="bio" rows="2" placeholder="Paste the profile bio exactly as shown"></textarea></label>
    <label class="field"><span>Link in bio</span><input type="url" name="link_in_bio_url" placeholder="https://linktr.ee/…"></label>
    <label class="check" style="align-self:end"><input type="checkbox" name="no_link_in_bio"> No link in bio</label>
    <label class="field full"><span>Recent posts <span class="hint">one per line: date | caption — e.g. ${esc(today())} | New collection drops Friday, DM to order</span></span><textarea name="posts" rows="5"></textarea></label>
    <label class="field"><span>Avg likes per post</span><input type="number" name="avg_likes" min="0"></label>
    <label class="field"><span>Avg comments per post</span><input type="number" name="avg_comments" min="0"></label>
    <label class="check full"><input type="checkbox" name="strong_visual_branding"> Strong, consistent visual branding (your judgement)</label>
    <div class="actions full"><button class="btn primary" type="submit">Add snapshot &amp; rescore</button></div>
    <p class="small faint full">Snapshots are entered by you from the public profile. Kard Radar does not scrape Instagram or TikTok.</p>
  </form>`;
}

export async function render(el, params, { state, navigate }) {
  const meta = state.meta, st = state.status || {};
  let lead = await get(`/api/leads/${encodeURIComponent(params.id)}`);
  let channel = lead.instagram_handle ? "instagram" : (lead.whatsapp || lead.phone) ? "whatsapp" : lead.tiktok_handle ? "tiktok" : "email";
  let prefer = "ai";

  const draw = () => {
    const l = lead, bd = l.score_breakdown || {};
    const conf = bd.confidence || {};
    el.dataset.title = l.business_name;
    document.title = l.business_name + " · Kard Radar";
    el.innerHTML = `
      <div class="lead-hero">
        <div style="min-width:0">
          <a class="btn-ghost small" href="#/leads" style="margin-left:-12px">← Leads</a>
          <h1>${esc(l.business_name)}</h1>
          <div class="meta">${statusBadge(l.status)}<span>${esc([l.industry, l.subcategory].filter(Boolean).join(" · ") || "Industry unknown")}</span>
            <span>${esc([l.city, l.state, l.country].filter(Boolean).join(", ") || "Location unknown")}</span>
            ${l.founder_name ? `<span>Founder: ${esc(l.founder_name)}</span>` : ""}
            <span class="faint">Discovered ${esc(fmtDate(l.discovered_at))} · ${esc(l.source)}</span></div>
          <div class="links">${linksHtml(l)}</div>
        </div>
        <div class="actions">
          <button class="btn primary" data-act="analyze">${ICON.bolt}Run Kard analysis</button>
          <button class="btn" data-act="refresh" title="Re-fetch the website and bio link, ignoring the cache">Refresh research</button>
          ${st.ai?.configured ? `<button class="btn" data-act="ai-force" title="Re-run AI even if evidence is unchanged">Force AI refresh</button>` : ""}
          <button class="btn" data-act="edit">Edit</button>
          <button class="btn-ghost" data-act="archive">Archive</button>
        </div>
      </div>
      <div class="stack" style="margin-bottom:16px">${notices(l, st)}</div>

      <section class="card score-band" style="margin-bottom:18px" aria-label="Scores">
        <div class="big">${ring(l.opportunity_score, { size: 92, meta })}<div><div class="t">Kard opportunity</div><div class="num" style="font-size:22px;font-weight:600">${l.opportunity_score ?? "—"}<span class="faint" style="font-size:14px">/100</span></div>
          <div class="small faint">${l.last_scored_at ? "Scored " + esc(ago(l.last_scored_at)) : "Not scored"}</div></div></div>
        ${meterHtml("Business Quality", l.business_quality ?? 0, 100, { detail: "How established & active" })}
        ${meterHtml("Kard Fit", l.kard_fit ?? 0, 100, { detail: "How much they need Kard" })}
        <div class="meter"><div class="meter-top"><span>Confidence</span>${confBadge(l.confidence)}</div>
          <div class="small faint">${conf.sources ? `Based on: ${esc(conf.sources.join(", ") || "very little")}.` : ""} ${conf.missing?.length ? `Missing: ${esc(conf.missing.join(", "))}.` : ""}</div></div>
      </section>

      <div class="split">
        <div class="stack">
          <section class="card"><div class="card-head"><h2>Why this business?</h2></div>${whyHtml(l, bd)}</section>
          <section class="card"><div class="card-head"><h2>Kard pain points</h2></div>${painHtml(l, bd)}</section>
          <section class="card"><div class="card-head"><h2>Buying signals</h2><span class="small faint">${esc(meta.buying_signal_window_days)}-day window</span></div>${buyingHtml(bd)}</section>
          <section class="card"><div class="card-head"><h2>Digital presence</h2></div>${presenceHtml(l, bd)}</section>
          <section class="card"><details class="fold" ${location.hash.includes("breakdown") ? "open" : ""}><summary><h2>Score breakdown &amp; overrides</h2></summary><div style="margin-top:12px">${breakdownHtml(bd, bd.weights)}</div></details></section>
          <section class="card" id="evidence"><div class="card-head"><h2>Evidence <span class="faint small">${(l.observations || []).length} item(s)</span></h2></div>
            ${evidenceHtml(l)}
            <details class="fold" style="margin-top:14px"><summary>Add social snapshot (Instagram / TikTok)</summary><div style="margin-top:12px">${snapshotForm(l)}</div></details>
            <details class="fold"><summary>Add evidence manually</summary>
              <form id="obsform" class="form-grid" style="margin-top:12px">
                <label class="field"><span>Type</span><select name="kind"><option value="post">Post / caption</option><option value="bio">Profile bio</option><option value="manual_note">Observation note</option></select></label>
                <label class="field"><span>Date seen / posted <span class="hint">(if known)</span></span><input type="date" name="observed_at"></label>
                <label class="field full"><span>What you observed</span><textarea name="content" rows="3" required placeholder="Paste the caption or describe what you saw, e.g. 'Story: now open in Wuse 2, Abuja'"></textarea></label>
                <label class="field full"><span>Source URL <span class="hint">(optional)</span></span><input type="url" name="source_url" placeholder="https://"></label>
                <div class="actions full"><button class="btn" type="submit">Add evidence &amp; rescore</button></div>
              </form></details>
          </section>
        </div>
        <aside class="side">
          <section class="card"><div class="card-head"><h2>Recommended approach</h2></div>
            <div class="label">Pitch angle</div><p style="font-size:16px;font-weight:600;margin:4px 0 12px">${esc(l.pitch_angle || "—")}</p>
            <div class="label">Why Kard is relevant</div><p class="muted" style="margin-top:4px">${esc(l.how_kard_helps || "—")}</p></section>
          <section class="card"><div class="card-head"><h2>Outreach</h2></div><div class="outreach-box" id="outreach">${outreachHtml(l, channel, prefer)}</div></section>
          <section class="card"><div class="card-head"><h2>Activity</h2></div>${activityHtml(l, meta)}</section>
          ${(l.ai_runs || []).length ? `<section class="card flat"><div class="label" style="margin-bottom:6px">AI runs</div>${l.ai_runs.map((r) => `<div class="small ${r.status === "ok" ? "muted" : ""}">${esc(fmtDate(r.created_at))} · ${esc(r.model)} · ${r.status === "ok" ? `${r.input_tokens + r.output_tokens} tokens · ≈$${Number(r.est_cost_usd).toFixed(4)}` : `<span style="color:var(--bad)">${esc(r.error)}</span>`}</div>`).join("")}</section>` : ""}
        </aside>
      </div>`;
  };

  const run = async (btn, fn, okMsg) => busy(btn, async () => {
    try {
      const r = await fn();
      lead = r.lead || r;
      draw();
      if (r.steps?.length) toast(r.steps.slice(0, 3).join(" · "));
      if (r.ai_error) toast(r.ai_error, r.ai_error.startsWith("AI skipped") ? "" : "bad");
      else if (r.ai?.skipped || r.result?.skipped) toast((r.ai || r.result).message);
      else if (okMsg) toast(okMsg, "good");
    } catch (err) { toast(err.message, "bad"); }
  });

  draw();

  el.addEventListener("click", async (e) => {
    const t = e.target;
    const jump = t.closest("[data-jump]");
    if (jump) {
      e.preventDefault();
      const target = el.querySelector(`#obs-${CSS.escape(jump.dataset.jump)}`);
      if (target) {
        el.querySelectorAll(".ev-item.target").forEach((x) => x.classList.remove("target"));
        target.classList.add("target");
        target.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return;
    }
    const ch = t.closest("[data-ch]");
    if (ch) { channel = ch.dataset.ch; el.querySelector("#outreach").innerHTML = outreachHtml(lead, channel, prefer); return; }
    const pr = t.closest("[data-prefer]");
    if (pr) { prefer = pr.dataset.prefer; el.querySelector("#outreach").innerHTML = outreachHtml(lead, channel, prefer); return; }
    if (t.closest("[data-copy]")) {
      const box = el.querySelector("#outreach .msg");
      const subj = box.querySelector(".msg-subject");
      const body = box.textContent.slice(subj ? subj.textContent.length : 0);
      copyText(subj ? `Subject: ${subj.textContent}\n\n${body}` : body);
      return;
    }
    const web = t.closest("[data-web]");
    if (web) return run(web, () => post(`/api/leads/${lead.id}/website`, { action: web.dataset.web }), "Website updated");
    const del_ = t.closest("[data-delobs]");
    if (del_) {
      if (await confirmModal("Remove this evidence?", "The lead will be rescored without it.", "Remove"))
        run(del_, () => del(`/api/leads/${lead.id}/observations/${del_.dataset.delobs}`), "Evidence removed");
      return;
    }
    const a = t.closest("[data-act]");
    if (!a) return;
    const act = a.dataset.act;
    if (act === "analyze") run(a, () => post(`/api/leads/${lead.id}/analyze`, { ai: !!st.ai?.configured }), "Analysis complete");
    else if (act === "refresh") run(a, () => post(`/api/leads/${lead.id}/research`, { refresh: true }), "Research refreshed");
    else if (act === "ai") run(a, () => post(`/api/leads/${lead.id}/ai`, {}), "AI analysis updated");
    else if (act === "ai-force") run(a, () => post(`/api/leads/${lead.id}/ai`, { force: true }), "AI analysis refreshed");
    else if (act === "edit") editModal(lead, meta, (l) => { lead = l; draw(); });
    else if (act === "archive") {
      if (await confirmModal("Archive this lead?", "It disappears from lists and the queue but its outcome history is kept.", "Archive")) {
        try { await del(`/api/leads/${lead.id}`); toast("Lead archived"); navigate("#/leads"); } catch (err) { toast(err.message, "bad"); }
      }
    } else if (act === "contacted") contactedModal(lead, async () => { lead = await get(`/api/leads/${lead.id}`); draw(); });
    else if (act === "followup") followupModal(lead, async () => { lead = await get(`/api/leads/${lead.id}`); draw(); });
    else if (act === "replied") run(a, () => post(`/api/leads/${lead.id}/replied`, { channel: lead.last_contact_channel }), "Marked as replied");
  });

  el.addEventListener("change", async (e) => {
    const t = e.target;
    if (t.id === "status") run(t, () => post(`/api/leads/${lead.id}/status`, { status: t.value }), `Status: ${t.value}`);
    if (t.dataset.override) {
      const v = t.value;
      run(t, () => post(`/api/leads/${lead.id}/signals`, { code: t.dataset.override, state: v === "auto" ? "clear" : v, note: "Set on lead page" }), "Signal updated and rescored");
    }
  });

  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, btn = f.querySelector('button[type="submit"]');
    if (f.id === "noteform") {
      if (!f.text.value.trim()) return;
      run(btn, () => post(`/api/leads/${lead.id}/notes`, { text: f.text.value }), "Note saved");
    } else if (f.id === "outcomeform") {
      run(btn, () => put(`/api/leads/${lead.id}/outcome`, { revenue: f.revenue.value, package: f.package.value }), "Outcome saved");
    } else if (f.id === "obsform") {
      run(btn, () => post(`/api/leads/${lead.id}/observations`, formData(f)), "Evidence added and rescored");
    } else if (f.id === "snapform") {
      const d = formData(f);
      if (!f.strong_visual_branding.checked) delete d.strong_visual_branding;
      run(btn, () => post(`/api/leads/${lead.id}/social`, d), "Snapshot added and rescored");
    }
  });
}
