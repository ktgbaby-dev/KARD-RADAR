import { toggleTheme, logout } from "../app.js";

export async function render(el) {
  el.dataset.title = "More";
  el.innerHTML = `<div class="page-head"><div><h1>More</h1></div></div>
    <section class="card"><div class="list">
      <a class="list-item" href="#/new"><div class="grow"><div class="title">Add a lead</div><div class="meta">Manual entry from Instagram / TikTok browsing</div></div></a>
      <a class="list-item" href="#/data"><div class="grow"><div class="title">Import / export</div><div class="meta">CSV in and out, learning dataset</div></div></a>
      <a class="list-item" href="#/settings"><div class="grow"><div class="title">Strategy settings</div><div class="meta">Weights, cities, industries, windows, integrations</div></div></a>
      <button class="list-item btn-ghost" style="width:100%;justify-content:flex-start;border-radius:0" id="mtheme"><div class="grow" style="text-align:left"><div class="title">Switch colour theme</div></div></button>
      <button class="list-item btn-ghost" style="width:100%;justify-content:flex-start;border-radius:0" id="mlogout"><div class="grow" style="text-align:left"><div class="title">Sign out</div></div></button>
    </div></section>`;
  el.querySelector("#mtheme").addEventListener("click", toggleTheme);
  el.querySelector("#mlogout").addEventListener("click", logout);
}
