// Kard Radar SPA shell: auth gate, hash router, shared meta cache, theme.
import { get, post, setUnauthorizedHandler } from "./api.js";
import { esc, errorBox } from "./ui.js";

const views = {
  dashboard: () => import("./views/dashboard.js"),
  today: () => import("./views/today.js"),
  leads: () => import("./views/leads.js"),
  lead: () => import("./views/lead.js"),
  discover: () => import("./views/discover.js"),
  new: () => import("./views/newlead.js"),
  data: () => import("./views/data.js"),
  settings: () => import("./views/settings.js"),
  more: () => import("./views/more.js"),
};

export const state = { meta: null, status: null };

export async function loadMeta(force = false) {
  if (!state.meta || force) {
    [state.meta, state.status] = await Promise.all([get("/api/meta"), get("/api/status")]);
  }
  return state.meta;
}

function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(query));
  if (!parts.length) return { name: "dashboard", params };
  if (parts[0] === "lead" && parts[1]) return { name: "lead", params: { ...params, id: parts[1] } };
  return { name: views[parts[0]] ? parts[0] : "dashboard", params };
}

let renderToken = 0;
async function render() {
  const { name, params } = parseRoute();
  const token = ++renderToken;
  const nav = name === "lead" ? "leads" : name;
  document.querySelectorAll("[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === nav));
  const el = document.getElementById("view");
  el.innerHTML = `<div class="skeleton" aria-hidden="true"></div>`;
  try {
    await loadMeta();
    const mod = await views[name]();
    if (token !== renderToken) return;
    el.innerHTML = "";
    await mod.render(el, params, { state, loadMeta, navigate });
    if (token === renderToken) {
      document.title = (el.dataset.title ? el.dataset.title + " · " : "") + "Kard Radar";
    }
  } catch (e) {
    if (token !== renderToken) return;
    if (e.status === 401) return;
    el.innerHTML = errorBox(e);
  }
  el.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

export function navigate(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("kr-theme"); } catch (e) { saved = null; }
  applyTheme(saved);
  document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
}

export function toggleTheme() {
  const cur = document.documentElement.dataset.theme ||
    (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const next = cur === "light" ? "dark" : "light";
  applyTheme(next);
  try { localStorage.setItem("kr-theme", next); } catch (e) { /* storage unavailable */ }
}

export async function logout() {
  await post("/api/logout", {});
  state.meta = null;
  showLogin();
}

function showLogin(message = "") {
  document.getElementById("app").hidden = true;
  const root = document.getElementById("login-root");
  root.innerHTML = `<div class="login"><form class="card" id="login-form">
      <div class="brand"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".35"/><circle cx="16" cy="16" r="8.5" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".6"/><path d="M16 16 L27 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="22.5" cy="11.2" r="2.4" fill="var(--electric)"/></svg></span>
      <span class="brand-text"><span class="brand-sub">Kard by Kal's Digital</span></span></div>
      <div><h1>Kard Radar</h1><p class="muted" style="margin-top:6px">Lead intelligence &amp; outreach. Internal use only.</p></div>
      ${message ? `<div class="notice warn">${esc(message)}</div>` : ""}
      <label class="field"><span>Admin password</span><input type="password" name="password" autocomplete="current-password" required></label>
      <button class="btn primary" type="submit">Sign in</button>
      <p class="small faint">The password is the ADMIN_PASSWORD value in the server's .env file.</p>
    </form></div>`;
  const form = document.getElementById("login-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.setAttribute("aria-busy", "true");
    try {
      await post("/api/login", { password: form.password.value });
      root.innerHTML = "";
      startApp();
    } catch (err) {
      btn.removeAttribute("aria-busy");
      showLogin(err.message);
    }
  });
  form.password.focus();
}

let started = false;
function startApp() {
  document.getElementById("app").hidden = false;
  if (!started) {
    started = true;
    window.addEventListener("hashchange", render);
    document.getElementById("logout").addEventListener("click", logout);
    document.getElementById("global-search").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = e.target.q.value.trim();
      navigate(`#/leads?q=${encodeURIComponent(q)}`);
    });
  }
  render();
}

async function boot() {
  initTheme();
  setUnauthorizedHandler(() => showLogin("Your session has ended. Please sign in again."));
  try {
    const me = await get("/api/me");
    if (!me.configured) return showLogin("Server is not configured yet. Run: python server.py --init");
    if (me.authenticated) startApp();
    else showLogin();
  } catch (e) {
    showLogin(e.message);
  }
}

boot();
