import { post } from "../api.js";
import { esc, toast, busy, formData, modal, today } from "../ui.js";

export async function render(el, params, { state, navigate }) {
  el.dataset.title = "Add lead";
  const meta = state.meta, st = state.status || {};
  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Manual lead</div><h1>Add a lead</h1>
      <p class="sub">Found a prospect while browsing Instagram or TikTok? Add what you can see — Kard Radar checks for duplicates, researches the website and scores it.</p></div></div>
    <form id="nform" class="split">
      <div class="stack">
        <section class="card"><div class="card-head"><h2>Business</h2></div>
          <div class="form-grid">
            <label class="field full"><span>Business name</span><input type="text" name="business_name" placeholder="Leave blank to use the handle"></label>
            <label class="field"><span>Instagram</span><input type="text" name="instagram_url" placeholder="@handle or profile URL" value="${esc(params.instagram || "")}"></label>
            <label class="field"><span>TikTok</span><input type="text" name="tiktok_url" placeholder="@handle or profile URL"></label>
            <label class="field"><span>Website</span><input type="url" name="website_url" placeholder="https://"></label>
            <label class="check" style="align-self:end"><input type="checkbox" name="no_website_confirmed"> I checked — no website</label>
            <label class="field"><span>Link in bio</span><input type="url" name="link_in_bio_url" placeholder="https://linktr.ee/… or wa.me/…"></label>
            <label class="check" style="align-self:end"><input type="checkbox" name="no_link_in_bio"> No link in bio</label>
            <label class="field"><span>Industry</span><select name="industry">${meta.industries.map((i) => `<option>${esc(i)}</option>`).join("")}</select></label>
            <label class="field"><span>Subcategory <span class="hint">(optional)</span></span><input type="text" name="subcategory" placeholder="e.g. Aso-ebi, bridal wigs"></label>
            <label class="field"><span>City</span><input type="text" name="city" list="ncities" value="Lagos"></label>
            <label class="field"><span>State</span><input type="text" name="state" placeholder="Filled automatically for known cities"></label>
            <label class="field"><span>WhatsApp</span><input type="tel" name="whatsapp" placeholder="0803 123 4567"></label>
            <label class="field"><span>Email</span><input type="email" name="email"></label>
            <label class="field"><span>Founder / owner <span class="hint">(if publicly named)</span></span><input type="text" name="founder_name"></label>
            <label class="field full"><span>Notes</span><textarea name="notes" rows="2" placeholder="Where you found them, first impressions…"></textarea></label>
            <datalist id="ncities">${meta.cities.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
          </div>
          <div id="dupwarn" style="margin-top:12px"></div>
        </section>
        <section class="card"><div class="card-head"><h2>What you saw on their profile <span class="hint small faint">optional, but it makes the score real</span></h2></div>
          <div class="form-grid">
            <label class="field"><span>Platform</span><select name="snap_platform"><option value="instagram">Instagram</option><option value="tiktok">TikTok</option></select></label>
            <label class="field"><span>Followers</span><input type="text" name="snap_followers" placeholder="e.g. 5.2k"></label>
            <label class="field full"><span>Bio</span><textarea name="snap_bio" rows="2" placeholder="Paste the bio exactly as shown"></textarea></label>
            <label class="field full"><span>Recent posts <span class="hint">one per line: date | caption — e.g. ${esc(today())} | New collection out now, DM to order</span></span><textarea name="snap_posts" rows="4"></textarea></label>
          </div>
        </section>
      </div>
      <aside class="side">
        <section class="card"><div class="card-head"><h2>Analysis</h2></div>
          <label class="check"><input type="checkbox" name="analyze" checked> Research website &amp; score now</label>
          <label class="check"><input type="checkbox" name="ai" ${st.ai?.configured ? "checked" : "disabled"}> AI analysis ${st.ai?.configured ? "" : "<span class='faint'>(needs ANTHROPIC_API_KEY)</span>"}</label>
          <button class="btn primary" type="submit" style="width:100%;margin-top:12px">Add lead &amp; analyse</button>
          <p class="small faint" style="margin-top:10px">Nothing is assumed: anything you leave blank is scored as Unknown, not as a gap.</p>
        </section>
      </aside>
    </form>`;

  const form = el.querySelector("#nform");
  const dupBox = el.querySelector("#dupwarn");
  const checkDup = async () => {
    const d = formData(form);
    const probe = { business_name: d.business_name, instagram_url: d.instagram_url, tiktok_url: d.tiktok_url, website_url: d.website_url, city: d.city, whatsapp: d.whatsapp, email: d.email };
    if (!Object.values(probe).some(Boolean)) { dupBox.innerHTML = ""; return; }
    try {
      const r = await post("/api/leads/check-duplicates", probe);
      dupBox.innerHTML = r.matches.length ? `<div class="notice warn"><div><b>Possible duplicate:</b> ${r.matches.map((m) => `<a href="#/lead/${m.lead_id}">${esc(m.business_name)}</a> (${esc(m.match_on.join(", "))})`).join("; ")}</div></div>` : "";
    } catch (e) { dupBox.innerHTML = ""; }
  };
  ["instagram_url", "tiktok_url", "website_url", "business_name", "whatsapp", "email"].forEach((n) => form[n].addEventListener("blur", checkDup));

  const submit = async (force) => {
    const d = formData(form);
    const body = { ...d, force };
    ["snap_platform", "snap_followers", "snap_bio", "snap_posts"].forEach((k) => delete body[k]);
    if (!body.no_website_confirmed) delete body.no_website_confirmed;
    if (!body.no_link_in_bio) delete body.no_link_in_bio;
    const hasSnap = d.snap_followers || d.snap_bio || d.snap_posts;
    const btn = form.querySelector('button[type="submit"]');
    await busy(btn, async () => {
      try {
        // create first without AI when a snapshot follows, so AI sees the snapshot evidence
        const r = await post("/api/leads", { ...body, ai: hasSnap ? false : body.ai });
        const id = r.lead.id;
        if (hasSnap) {
          await post(`/api/leads/${id}/social`, { platform: d.snap_platform, followers: d.snap_followers, bio: d.snap_bio, posts: d.snap_posts });
          if (body.ai) {
            try { await post(`/api/leads/${id}/ai`, {}); } catch (e) { toast(e.message, "bad"); }
          }
        }
        if (r.ai_error) toast(r.ai_error, "bad");
        toast("Lead added and analysed", "good");
        navigate(`#/lead/${id}`);
      } catch (err) {
        if (err.status === 409) {
          const ms = err.data.matches || [];
          modal(`<h2>This looks like a lead you already have</h2>
            <div class="list">${ms.map((m) => `<a class="list-item" href="#/lead/${m.lead_id}" data-close><div class="grow"><div class="title">${esc(m.business_name)}</div><div class="meta">${esc(m.strength)} match on ${esc(m.match_on.join(", "))} · ${esc(m.status)}</div></div><span class="btn small">Open</span></a>`).join("")}</div>
            <div class="actions"><button class="btn" data-close>Cancel</button>${ms.some((m) => m.strength === "strong") ? "" : `<button class="btn primary" data-force>Create anyway</button>`}</div>`,
            { onMount: (m, close) => { const f = m.querySelector("[data-force]"); if (f) f.addEventListener("click", () => { close(); submit(true); }); } });
        } else toast(err.message, "bad");
      }
    });
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(false); });
}
