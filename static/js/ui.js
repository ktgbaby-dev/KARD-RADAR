// UI helpers. Every interpolated value goes through esc() — lead data is untrusted text.
export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function safeUrl(u) {
  const s = String(u || "").trim();
  return /^https?:\/\//i.test(s) ? s : "";
}

export function tier(score, meta) {
  if (score === null || score === undefined) return "none";
  const hi = meta?.high_opportunity_score ?? 80;
  const mid = meta?.min_opportunity_score ?? 65;
  return score >= hi ? "high" : score >= mid ? "mid" : "low";
}

export function ring(score, { size = 64, label = "", meta } = {}) {
  const r = 26, c = 2 * Math.PI * r;
  if (score === null || score === undefined) {
    return `<div class="ring unscored" style="--size:${size}px" role="img" aria-label="Not scored yet">
      <svg viewBox="0 0 60 60"><circle class="trk" cx="30" cy="30" r="${r}" fill="none" stroke-width="5"/></svg>
      <div class="n">—</div></div>`;
  }
  const off = c * (1 - Math.max(0, Math.min(100, score)) / 100);
  return `<div class="ring ${tier(score, meta)}" style="--size:${size}px" role="img" aria-label="${esc(label || "Score")} ${score} out of 100">
    <svg viewBox="0 0 60 60"><circle class="trk" cx="30" cy="30" r="${r}" fill="none" stroke-width="5"/>
    <circle class="val" cx="30" cy="30" r="${r}" fill="none" stroke-width="5" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}"/></svg>
    <div class="n"><span>${score}${label ? `<small>${esc(label)}</small>` : ""}</span></div></div>`;
}

export function pill(score, label, meta) {
  if (score === null || score === undefined) return `<span class="score-pill" title="${esc(label)}">—<small>&nbsp;${esc(label)}</small></span>`;
  return `<span class="score-pill ${tier(score, meta)}" title="${esc(label)} ${score}/100">${score}<small>&nbsp;${esc(label)}</small></span>`;
}

export function meterHtml(label, value, max, { detail = "", cls = "" } = {}) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const t = pct >= 75 ? "high" : pct >= 45 ? "mid" : "";
  return `<div class="meter ${cls}">
    <div class="meter-top"><span>${esc(label)}</span><b>${fmtNum(value)}<span class="faint">/${max}</span></b></div>
    <div class="bar ${t}" role="img" aria-label="${esc(label)} ${fmtNum(value)} of ${max}"><i style="width:${pct.toFixed(1)}%"></i></div>
    ${detail ? `<div class="small faint">${esc(detail)}</div>` : ""}</div>`;
}

export function fmtNum(n) {
  if (n === null || n === undefined || n === "") return "—";
  const x = Number(n);
  return Number.isInteger(x) ? String(x) : x.toFixed(1).replace(/\.0$/, "");
}

export function compact(n) {
  if (n === null || n === undefined) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1e4) return Math.round(n / 1e3) + "K";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

export function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s.length <= 10 ? s + "T00:00:00" : s);
  if (isNaN(d)) return esc(s);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function ago(s) {
  if (!s) return "";
  const d = new Date(s.length <= 10 ? s + "T00:00:00" : s);
  if (isNaN(d)) return "";
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days < 0) return `in ${-days}d`;
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

export function today() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function addDays(n) {
  const d = new Date(Date.now() + n * 86400000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function statusBadge(s) {
  const cls = "s-" + String(s || "").toLowerCase().replace(/[^a-z]+/g, "-");
  return `<span class="status ${cls}">${esc(s)}</span>`;
}

export function confBadge(level) {
  const l = level || "Low";
  return `<span class="conf ${esc(l)}" title="Evidence confidence: ${esc(l)}"><i><b></b><b></b><b></b></i>${esc(l)}</span>`;
}

export function detBadge(d) {
  if (!d || d === "rule") return `<span class="det">Rule</span>`;
  return `<span class="det ${esc(d)}">${d === "ai" ? "AI" : "Manual"}</span>`;
}

export function toast(msg, kind = "") {
  const root = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => el.remove(), kind === "bad" ? 7000 : 3800);
}

export function modal(html, { onMount } = {}) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true">${html}</div></div>`;
  const back = root.firstElementChild;
  const close = () => { root.innerHTML = ""; document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest("[data-close]")) close(); });
  const m = back.querySelector(".modal");
  const first = m.querySelector("input, select, textarea, button");
  if (first) setTimeout(() => first.focus(), 20);
  onMount && onMount(m, close);
  return close;
}

export function confirmModal(title, body, okLabel = "Confirm") {
  return new Promise((resolve) => {
    modal(`<h2>${esc(title)}</h2><p class="muted">${esc(body)}</p>
      <div class="actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>${esc(okLabel)}</button></div>`,
      { onMount: (m, close) => {
        m.querySelector("[data-ok]").addEventListener("click", () => { close(); resolve(true); });
        m.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => resolve(false)));
      } });
  });
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard", "good");
    return true;
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    toast(ok ? "Copied to clipboard" : "Copy failed — select the text manually", ok ? "good" : "bad");
    return ok;
  }
}

export async function busy(btn, fn) {
  if (!btn) return fn();
  btn.setAttribute("aria-busy", "true");
  btn.disabled = true;
  try { return await fn(); } finally { btn.removeAttribute("aria-busy"); btn.disabled = false; }
}

export function waLink(num, text = "") {
  const d = String(num || "").replace(/\D/g, "");
  if (!d) return "";
  return `https://wa.me/${d}${text ? `?text=${encodeURIComponent(text)}` : ""}`;
}

export function contactLink(l) {
  if (l.whatsapp) return { href: waLink(l.whatsapp), label: "WhatsApp" };
  if (l.phone) return { href: `tel:${String(l.phone).replace(/[^\d+]/g, "")}`, label: "Call" };
  if (l.email) return { href: `mailto:${l.email}`, label: "Email" };
  return null;
}

export function channels(l) {
  const on = (x) => (x ? "on" : "");
  return `<div class="channels" aria-label="Channels">
    <span class="${on(l.instagram_handle)}" title="Instagram">IG</span><span class="${on(l.tiktok_handle)}" title="TikTok">TT</span>
    <span class="${on(l.website_status === "has_website")}" title="Website">W</span><span class="${on(l.whatsapp || l.phone)}" title="WhatsApp / phone">WA</span>
    <span class="${on(l.email)}" title="Email">@</span></div>`;
}

export function formData(form) {
  const out = {};
  new FormData(form).forEach((v, k) => { out[k] = typeof v === "string" ? v.trim() : v; });
  form.querySelectorAll('input[type="checkbox"]').forEach((c) => { if (c.name) out[c.name] = c.checked; });
  return out;
}

export function errorBox(e) {
  return `<div class="notice bad"><div><b>Something went wrong.</b> ${esc(e.message || e)}</div></div>`;
}

export const ICON = {
  ig: `<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.2" cy="6.8" r=".9"/></svg>`,
  tt: `<svg viewBox="0 0 24 24"><path d="M14 4v10.5a3.5 3.5 0 1 1-3.5-3.5M14 4c.5 2.6 2.4 4.3 5 4.5"/></svg>`,
  web: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17"/></svg>`,
  chat: `<svg viewBox="0 0 24 24"><path d="M5 18.5l1-3.4A7.5 7.5 0 1 1 9 18z"/></svg>`,
  copy: `<svg viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 15V6a1 1 0 0 1 1-1h9"/></svg>`,
  check: `<svg viewBox="0 0 24 24"><path d="M5 12.5l4.2 4L19 7"/></svg>`,
  clock: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>`,
  bolt: `<svg viewBox="0 0 24 24"><path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/></svg>`,
  ext: `<svg viewBox="0 0 24 24"><path d="M14 5h5v5M19 5l-8 8M17 14v5H5V7h5"/></svg>`,
};
