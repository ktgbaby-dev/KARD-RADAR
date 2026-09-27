import { post } from "../api.js";
import { esc, toast, busy } from "../ui.js";

const TEMPLATE = "business_name,instagram,tiktok,website,industry,city,whatsapp,email,notes\n" +
  "Example Brand,@examplebrand,,https://example.com,Fashion,Lagos,08031234567,hello@example.com,Found via hashtag\n";

export async function render(el) {
  el.dataset.title = "Import / export";
  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Data</div><h1>Import &amp; export</h1>
      <p class="sub">CSV in, CSV out. Imports are de-duplicated against existing leads by handle, domain, phone, email and name + city.</p></div></div>
    <div class="grid cols-2">
      <section class="card"><div class="card-head"><h2>Import CSV</h2><button class="btn small" id="tpl">Download template</button></div>
        <form id="iform" class="stack">
          <label class="field"><span>CSV file</span><input type="file" name="file" accept=".csv,text/csv" required></label>
          <p class="small faint">Recognised columns include: business name, instagram, tiktok, website, link in bio, industry, subcategory, city, state, country, whatsapp, phone, email, founder, followers, bio, notes, status. Column names are matched loosely (e.g. "IG", "Brand", "Location").</p>
          <button class="btn primary" type="submit">Import</button>
        </form>
        <div id="report" style="margin-top:14px"></div>
      </section>
      <section class="card"><div class="card-head"><h2>Export</h2></div>
        <div class="stack">
          <a class="btn" href="/api/export.csv" download>All leads (CSV)</a>
          <a class="btn" href="/api/export.csv?min_score=65&contacted=0" download>Qualified, not contacted</a>
          <a class="btn" href="/api/export-learning.csv" download>Outcome learning dataset</a>
          <p class="small faint">Filtered exports are also available from the Leads page (Export CSV uses the current filters). The learning dataset contains the score and signals frozen at first contact alongside each funnel outcome — the raw material for finding which characteristics actually convert.</p>
        </div>
      </section>
    </div>`;

  el.querySelector("#tpl").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "kard-radar-template.csv"; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  el.querySelector("#iform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = e.target.file.files[0];
    if (!file) return;
    if (file.size > 6 * 1024 * 1024) return toast("File is larger than 6 MB — split it into smaller files", "bad");
    const text = await file.text();
    await busy(e.target.querySelector("button"), async () => {
      try {
        const r = await post("/api/import", { csv: text });
        const mapped = Object.entries(r.columns).map(([h, m]) => `<span class="chip ${m ? "yes" : "no"}">${esc(h)}${m ? " → " + esc(m) : " (ignored)"}</span>`).join("");
        el.querySelector("#report").innerHTML = `
          <div class="notice ${r.errors.length ? "warn" : "info"}" style="display:block">
            <b>${r.created.length} created · ${r.merged.length} merged into existing · ${r.skipped.length} skipped · ${r.errors.length} error(s)</b>
            <div class="chips" style="margin-top:8px">${mapped}</div></div>
          ${r.skipped.length ? `<h3 style="margin:14px 0 6px">Skipped (possible duplicates)</h3><ul class="checks">${r.skipped.map((s) => `<li class="bad">Row ${s.row}: ${esc(s.business_name)} — ${esc(s.reason)} <a href="#/lead/${s.lead_id}">open</a></li>`).join("")}</ul>` : ""}
          ${r.merged.length ? `<h3 style="margin:14px 0 6px">Merged</h3><ul class="checks">${r.merged.slice(0, 50).map((s) => `<li>Row ${s.row}: <a href="#/lead/${s.lead_id}">${esc(s.business_name)}</a> — matched on ${esc(s.match_on.join(", "))}${s.fields_filled.length ? "; filled " + esc(s.fields_filled.join(", ")) : ""}</li>`).join("")}</ul>` : ""}
          ${r.errors.length ? `<h3 style="margin:14px 0 6px">Errors</h3><ul class="checks">${r.errors.map((s) => `<li class="bad">Row ${s.row}: ${esc(s.error)}</li>`).join("")}</ul>` : ""}
          ${r.created.length ? `<p style="margin-top:12px"><a class="btn small" href="#/leads?recent_days=1&sort=discovered">View imported leads</a></p>
            <p class="small faint" style="margin-top:6px">Imported leads are scored from the CSV data. Use "Re-research" on the Leads page to fetch their websites.</p>` : ""}`;
        toast(`Import finished: ${r.created.length} created, ${r.merged.length} merged`, "good");
      } catch (err) { toast(err.message, "bad"); }
    });
  });
}
