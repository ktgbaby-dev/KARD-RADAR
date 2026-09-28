import { get, post } from "../api.js";
import { esc, toast, busy, pill, fmtDate, ago, safeUrl } from "../ui.js";

const KW_SUGGEST = ["new collection", "DM to order", "WhatsApp to order", "bookings open", "new location", "launch", "pre-order", "pop-up"];
const PLAT = { instagram: "Instagram", instagram_post: "IG post", tiktok: "TikTok", website: "Website", places: "Google Maps", link_page: "Link page",
  storefront: "Storefront", facebook: "Facebook", x: "X", youtube: "YouTube", linkedin: "LinkedIn", article: "Article", directory: "Directory" };

function playbook(loc, ind, kws) {
  const k = kws.length ? kws : ["DM to order", "WhatsApp to order", "new collection"];
  const g = (q) => `https://www.google.com/search?q=${encodeURIComponent(q)}`;
  const items = [];
  k.slice(0, 4).forEach((kw) => {
    items.push([`site:instagram.com ${ind} ${loc} "${kw}"`, g(`site:instagram.com ${ind} ${loc} "${kw}"`)]);
    items.push([`site:tiktok.com ${ind} ${loc} "${kw}"`, g(`site:tiktok.com ${ind} ${loc} "${kw}"`)]);
  });
  items.push([`${ind} ${loc} "linktr.ee"`, g(`${ind} ${loc} "linktr.ee" OR "wa.me"`)]);
  items.push([`Instagram hashtag #${(ind + loc).replace(/[^a-z0-9]/gi, "").toLowerCase()}`, `https://www.instagram.com/explore/tags/${encodeURIComponent((ind + loc).replace(/[^a-z0-9]/gi, "").toLowerCase())}/`]);
  items.push([`Google Maps: ${ind} in ${loc}`, `https://www.google.com/maps/search/${encodeURIComponent(ind + " in " + loc + ", Nigeria")}`]);
  return items;
}

function candHtml(c) {
  const sigs = c.snippet_signals || [];
  const imported = c.status === "imported";
  const dup = c.matched_lead_id;
  return `<div class="cand">
    <input type="checkbox" class="csel" value="${c.id}" ${imported || c.status === "dismissed" ? "disabled" : ""} ${!imported && !dup && c.platform !== "article" ? "checked" : ""} aria-label="Select ${esc(c.name_guess || c.title)}">
    <div style="min-width:0">
      <div class="row" style="gap:8px"><span class="plat">${esc(PLAT[c.platform] || c.platform)}</span><span class="t">${esc(c.name_guess || c.title || c.url)}</span>${c.handle ? `<span class="faint small">@${esc(c.handle)}</span>` : ""}</div>
      ${safeUrl(c.url) ? `<a class="u" href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)}</a>` : ""}
      ${c.snippet ? `<div class="s">${esc(c.snippet)}</div>` : ""}
      <div class="chips" style="margin-top:6px">
        ${c.result_date ? `<span class="chip">${esc(fmtDate(c.result_date))}</span>` : ""}
        ${c.extra?.followers ? `<span class="chip">~${esc(c.extra.followers.toLocaleString())} followers (snippet)</span>` : ""}
        ${c.extra?.rating ? `<span class="chip">★ ${esc(c.extra.rating)} (${esc(c.extra.rating_count || 0)})</span>` : ""}
        ${c.platform === "places" ? `<span class="chip ${c.extra?.website ? "" : "pain"}">${c.extra?.website ? "Has website" : "No website listed"}</span>` : ""}
        ${sigs.map((s) => `<span class="chip ${["dm_for_price", "whatsapp_ordering", "link_in_bio_dependency", "location_in_captions"].includes(s) ? "pain" : "buy"}">${esc(s.replaceAll("_", " "))}</span>`).join("")}
      </div>
    </div>
    <div>${imported ? `<a class="btn small" href="#/lead/${c.matched_lead_id}">Open</a>` : dup ? `<a class="chip bronze" href="#/lead/${c.matched_lead_id}" title="${esc(c.match_reason)}">In Radar</a>` : c.status === "dismissed" ? `<span class="chip no">Dismissed</span>` : ""}</div>
  </div>`;
}

export async function render(el, params, { state }) {
  el.dataset.title = "Find leads";
  const meta = state.meta;
  const home = await get("/api/discover");
  const configured = home.providers.filter((p) => p.configured);
  let mode = params.mode || "search";
  let run = null, importResults = null;

  const draw = () => {
    const p = run?.params || {};
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Discovery</div><h1>Find leads</h1>
        <p class="sub">Search public sources for businesses showing digital friction and growth activity. Instagram and TikTok are searched through search-engine results only — never scraped.</p></div></div>
      <div class="seg" role="tablist" style="margin-bottom:16px">
        <button class="${mode === "search" ? "on" : ""}" data-mode="search">Search APIs</button>
        <button class="${mode === "paste" ? "on" : ""}" data-mode="paste">Paste URLs</button>
        <button class="${mode === "playbook" ? "on" : ""}" data-mode="playbook">Search playbook</button>
      </div>
      <div class="split">
        <section class="card">
          ${mode === "search" ? `
            ${configured.length ? `<div class="notice info" style="margin-bottom:14px"><div>Using: <b>${esc(configured.map((c) => c.label).join(", "))}</b>. Each search runs up to 6 queries.</div></div>`
              : `<div class="notice warn" style="margin-bottom:14px"><div><b>No search provider configured.</b> Add <code>SERPER_API_KEY</code>, <code>BRAVE_SEARCH_API_KEY</code> or <code>GOOGLE_PLACES_API_KEY</code> as an environment variable (Vercel → Settings → Environment Variables, then redeploy; or .env locally, then restart). Until then, use <b>Paste URLs</b> or the <b>Search playbook</b> — nothing will be invented.</div></div>`}
            <form id="dform" class="form-grid">
              <label class="field"><span>Location</span><input type="text" name="location" list="dcities" required value="${esc(p.location || params.location || "Lagos")}"></label>
              <label class="field"><span>Industry</span><select name="industry">${meta.industries.map((i) => `<option ${i === (p.industry || params.industry) ? "selected" : ""}>${esc(i)}</option>`).join("")}</select></label>
              <label class="field full"><span>Keywords <span class="hint">comma-separated, up to 3 are searched</span></span><input type="text" name="keywords" value="${esc((p.keywords || []).join(", "))}" placeholder="new collection, DM to order"></label>
              <div class="chips full">${KW_SUGGEST.map((k) => `<button type="button" class="chip button" data-kw="${esc(k)}">+ ${esc(k)}</button>`).join("")}</div>
              <fieldset class="full"><legend class="field"><span>Sources</span></legend><div class="row">
                ${[["instagram", "Instagram"], ["tiktok", "TikTok"], ["web", "Web"], ["places", "Google Maps"]].map(([v, l]) => `<label class="check"><input type="checkbox" name="src_${v}" ${!p.sources || p.sources.includes(v) ? "checked" : ""}> ${l}</label>`).join("")}</div></fieldset>
              <label class="field"><span>Minimum Kard score</span><input type="number" name="min_score" min="0" max="100" value="${esc(p.min_score ?? meta.min_opportunity_score)}"></label>
              <div class="field" style="justify-content:flex-end"><button class="btn primary" type="submit" ${configured.length ? "" : "disabled"}>Discover leads</button></div>
              <datalist id="dcities">${meta.cities.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
            </form>` : ""}
          ${mode === "paste" ? `
            <form id="pform" class="form-grid">
              <label class="field full"><span>Profile or website URLs <span class="hint">one per line — Instagram, TikTok, websites, Linktree…</span></span>
                <textarea name="urls" rows="7" required placeholder="https://www.instagram.com/brandname/\nhttps://www.tiktok.com/@brandname\nhttps://brandname.com"></textarea></label>
              <label class="field"><span>Location</span><input type="text" name="location" list="pcities" value="Lagos"></label>
              <label class="field"><span>Industry</span><select name="industry">${meta.industries.map((i) => `<option>${esc(i)}</option>`).join("")}</select></label>
              <div class="actions full"><button class="btn primary" type="submit">Create candidates</button></div>
              <datalist id="pcities">${meta.cities.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
              <p class="small faint full">Pasted profiles become candidates you can import. Add a social snapshot on each lead to give the scorer real activity data.</p>
            </form>` : ""}
          ${mode === "playbook" ? `
            <form id="bform" class="form-grid">
              <label class="field"><span>Location</span><input type="text" name="location" value="Lagos" list="bcities"></label>
              <label class="field"><span>Industry</span><select name="industry">${meta.industries.map((i) => `<option>${esc(i)}</option>`).join("")}</select></label>
              <label class="field full"><span>Keywords</span><input type="text" name="keywords" placeholder="DM to order, new collection"></label>
              <datalist id="bcities">${meta.cities.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
            </form>
            <div class="playbook" id="plinks" style="margin-top:14px"></div>
            <p class="small faint" style="margin-top:10px">These open in your own browser. When you find a promising profile, paste it under <b>Paste URLs</b> or <a href="#/new">add it manually</a>.</p>` : ""}
        </section>
        <aside class="side">
          <section class="card"><div class="card-head"><h2>Recent searches</h2></div>
            <div class="list">${home.runs.length ? home.runs.map((r) => `<a class="list-item" href="#/discover?run=${r.id}"><div class="grow"><div class="title">${esc(r.params.industry || "")} · ${esc(r.params.location || "")}</div>
              <div class="meta">${esc(r.params.mode === "pasted" ? "Pasted URLs" : (r.params.keywords || []).join(", ") || "no keywords")} · ${r.result_count} result(s) · ${esc(ago(r.created_at))}</div></div></a>`).join("") : `<div class="empty">No searches yet.</div>`}</div></section>
        </aside>
      </div>
      <div id="results" style="margin-top:18px"></div>`;
    drawResults();
    if (mode === "playbook") drawPlaybook();
  };

  const drawPlaybook = () => {
    const f = el.querySelector("#bform");
    const kws = f.keywords.value.split(",").map((s) => s.trim()).filter(Boolean);
    el.querySelector("#plinks").innerHTML = playbook(f.location.value.trim() || "Lagos", f.industry.value, kws)
      .map(([label, href]) => `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer"><span>${esc(label)}</span><span class="faint">↗</span></a>`).join("");
  };

  const drawResults = () => {
    const box = el.querySelector("#results");
    if (!run) { box.innerHTML = ""; return; }
    const cands = run.candidates || [];
    const minScore = Number(run.params?.min_score ?? meta.min_opportunity_score);
    box.innerHTML = `<section class="card">
      <div class="card-head"><h2>${cands.length} candidate(s)</h2><span class="small faint">${esc(run.providers.join(", "))} · ${esc(fmtDate(run.created_at))}</span></div>
      ${run.message ? `<div class="notice ${run.status === "ok" ? "" : "warn"}" style="margin-bottom:12px"><div>${esc(run.message)}</div></div>` : ""}
      ${importResults ? `<div class="notice info" style="margin-bottom:12px;display:block"><b>Imported ${importResults.length} lead(s).</b> ${importResults.filter((r) => r.meets_min).length} meet the minimum score of ${minScore}.
        <div class="table-wrap"><table class="data" style="margin-top:10px"><thead><tr><th>Business</th><th>Action</th><th class="num">Score</th><th>Confidence</th><th></th></tr></thead><tbody>
        ${importResults.map((r) => r.lead_id ? `<tr><td>${esc(r.business_name)}</td><td>${esc(r.action)}</td><td class="num">${pill(r.opportunity_score, "", meta)}</td><td>${esc(r.confidence)}</td><td>${r.meets_min ? `<span class="chip yes">≥ ${minScore}</span>` : `<span class="chip no">below min</span>`} <a class="btn small" href="#/lead/${r.lead_id}">Open</a></td></tr>` : `<tr><td colspan="5">${esc(r.error)}</td></tr>`).join("")}
        </tbody></table></div></div>` : ""}
      ${cands.length ? `<div>${cands.map(candHtml).join("")}</div>
        <div class="bulkbar"><label class="check"><input type="checkbox" id="csall"> Select all</label><span class="spacer"></span>
          <label class="check"><input type="checkbox" id="doresearch" checked> Research websites on import</label>
          <button class="btn" data-dismiss>Dismiss selected</button><button class="btn primary" data-import>Import &amp; analyse selected</button></div>
        <p class="small faint" style="margin-top:10px">Candidates already in Radar are merged, not duplicated. Scores from snippets alone are low-confidence until you add evidence.</p>`
        : `<div class="empty">No candidates.</div>`}
    </section>`;
  };

  if (params.run) {
    try { run = await get(`/api/discover/${encodeURIComponent(params.run)}`); mode = run.params?.mode === "pasted" ? "paste" : "search"; } catch (e) { run = null; }
  }
  draw();

  el.addEventListener("click", async (e) => {
    const t = e.target;
    const m = t.closest("[data-mode]");
    if (m) { mode = m.dataset.mode; draw(); return; }
    const kw = t.closest("[data-kw]");
    if (kw) {
      const inp = el.querySelector('#dform [name="keywords"]');
      const cur = inp.value.split(",").map((s) => s.trim()).filter(Boolean);
      if (!cur.includes(kw.dataset.kw)) cur.push(kw.dataset.kw);
      inp.value = cur.join(", ");
      return;
    }
    if (t.id === "csall") { el.querySelectorAll(".csel:not(:disabled)").forEach((c) => { c.checked = t.checked; }); return; }
    const ids = () => [...el.querySelectorAll(".csel:checked")].map((c) => Number(c.value));
    const imp = t.closest("[data-import]");
    if (imp) {
      if (!ids().length) return toast("Select at least one candidate", "bad");
      await busy(imp, async () => {
        try {
          const r = await post("/api/discover/import", { candidate_ids: ids(), research: el.querySelector("#doresearch").checked });
          importResults = r.results;
          run = await get(`/api/discover/${run.id}`);
          drawResults();
          toast(`Imported ${r.results.filter((x) => x.lead_id).length} lead(s)`, "good");
        } catch (err) { toast(err.message, "bad"); }
      });
      return;
    }
    const dis = t.closest("[data-dismiss]");
    if (dis) {
      await post("/api/discover/dismiss", { candidate_ids: ids() });
      run = await get(`/api/discover/${run.id}`);
      drawResults();
    }
  });

  el.addEventListener("input", (e) => { if (e.target.closest("#bform")) drawPlaybook(); });
  el.addEventListener("change", (e) => { if (e.target.closest("#bform")) drawPlaybook(); });

  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, btn = f.querySelector('button[type="submit"]');
    if (f.id === "dform") {
      const sources = ["instagram", "tiktok", "web", "places"].filter((s) => f[`src_${s}`].checked);
      if (!sources.length) return toast("Choose at least one source", "bad");
      await busy(btn, async () => {
        try {
          run = await post("/api/discover", { location: f.location.value, industry: f.industry.value, keywords: f.keywords.value.split(",").map((s) => s.trim()).filter(Boolean), sources, min_score: Number(f.min_score.value) });
          importResults = null;
          drawResults();
          el.querySelector("#results").scrollIntoView({ behavior: "smooth" });
        } catch (err) { toast(err.message, "bad"); }
      });
    } else if (f.id === "pform") {
      await busy(btn, async () => {
        try {
          run = await post("/api/discover/urls", { urls: f.urls.value, location: f.location.value, industry: f.industry.value });
          importResults = null;
          drawResults();
          el.querySelector("#results").scrollIntoView({ behavior: "smooth" });
        } catch (err) { toast(err.message, "bad"); }
      });
    }
  });
}
