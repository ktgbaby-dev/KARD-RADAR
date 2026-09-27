# Kard Radar — Technical Plan (Phase 0)

Kard Radar answers one question per lead: **"Why is this particular business likely to benefit from Kard right now?"**
Every number it shows is computed from stored, inspectable evidence. Follower count is a supporting signal only.

## 1. Application architecture

```
Browser (SPA, vanilla ES modules)
   │  JSON over HTTPS, session cookie
   ▼
server.py  ──  radar/web.py (router, auth, security headers, static files)
                 │
                 ├─ radar/api.py         route handlers (thin)
                 ├─ radar/leads.py       lead repository + filters
                 ├─ radar/pipeline.py    research orchestration
                 │     1 COLLECT      radar/fetcher.py + radar/website.py   (safe public-web fetch, cached)
                 │     2 NORMALIZE    radar/normalize.py                    (URLs, handles, phones, names)
                 │     3 DETECT       radar/signals.py                      (deterministic rules -> signals)
                 │     4 AI ANALYSIS  radar/ai.py                           (optional, cached, evidence-cited)
                 │     5 SCORE        radar/scoring.py                      (pure function, no AI)
                 │     6 OUTREACH     radar/outreach.py + ai.py             (template + AI drafts)
                 ├─ radar/discovery.py   search providers (pluggable) + candidate parsing
                 ├─ radar/dedupe.py      duplicate detection / merge
                 ├─ radar/priority.py    Today's 20
                 ├─ radar/csvio.py       CSV import / export
                 └─ radar/db.py          SQLite (default) or PostgreSQL via DATABASE_URL
```

**Stack decision.** The brief prefers Next.js + TypeScript + Tailwind. This machine has no Node.js runtime, and the brief
requires the app to be run and tested here. V1 therefore uses Python 3.13 (standard-library HTTP server + `sqlite3`) and a
build-free vanilla-JS frontend, with the official `anthropic` SDK as the only dependency. The backend is a clean JSON API,
so a Next.js frontend can replace `static/` later without touching the research engine.

## 2. Frontend architecture
- Single-page app, hash routing (`#/`, `#/today`, `#/leads`, `#/lead/42`, `#/discover`, `#/new`, `#/data`, `#/settings`).
- `static/js/api.js` (fetch wrapper, CSRF header), `ui.js` (score ring, meters, chips, toasts, modals), one module per view.
- CSS design tokens on `:root` (Kal's Digital graphite / off-white / bronze / electric), light + dark themes, mobile-first:
  sidebar on desktop, bottom tab bar on phones, 44px+ touch targets, 16px inputs.
- No build step, no CDN scripts. Only Google Fonts are external.

## 3. Backend architecture
- `ThreadingHTTPServer`; one DB connection per request; all mutations are `POST/PUT/PATCH/DELETE` JSON.
- Services are plain modules with pure functions where possible (scoring, signals, normalization are unit-tested alone).
- Long-running work (website fetch, AI call) runs inside the request with strict timeouts; V2 can move it to a job queue.

## 4. Database schema (portable SQL: SQLite and PostgreSQL)
| Table | Purpose |
|---|---|
| `leads` | one row per business: identity, channels, location, research fields, cached scores, CRM status/dates |
| `observations` | **evidence**: every fact collected (website text, bio, dated post, search snippet, manual note) with source + date |
| `signals` | detected signals `(lead, code, state yes/no/unknown, detector rule/ai/manual, evidence refs, date)` |
| `score_snapshots` | every scoring run's full breakdown (history + learning) |
| `outreach_messages` | generated drafts per channel (template or AI) |
| `activities` | timeline: status changes, contacted, replies, notes, follow-ups, analysis runs |
| `outcomes` | learning table: contacted / responded / interested / meeting / proposal / purchased / revenue + score and feature snapshot at first contact |
| `discovery_runs`, `discovery_candidates` | every discovery search and its raw candidates (dedupe-linked to leads) |
| `fetch_cache` | cached public web fetches with timestamps (TTL) |
| `ai_runs` | every AI call: model, tokens, estimated cost, status, input hash |
| `settings` | weights, target cities/industries, thresholds, windows (JSON values) |

## 5. Lead discovery strategy
1. **Search-API providers** (pluggable `SearchProvider.search(query) -> [Result]`): Serper (Google results), Brave Search
   API, Google Places API (New) Text Search. Queries combine location × industry × keywords, e.g.
   `site:instagram.com fashion Lagos "DM to order"`. Results are search-engine data (title, URL, snippet, date);
   Instagram/TikTok pages are never fetched.
2. **Paste URLs**: profile or website URLs found while browsing become candidates without any API.
3. **Search playbook**: pre-built search links the user opens in their own browser.
4. **Manual add** and **CSV import**.

Every candidate is deduplicated against existing leads before import. With no provider configured the UI says so; it never invents results.

## 6. Data enrichment strategy
- Websites and link-in-bio pages (Linktree, Beacons, storefronts) are fetched by a polite, SSRF-guarded fetcher that honours
  `robots.txt`, times out at 10 s, caps body size and caches for 7 days. It extracts title, meta, contacts, social links,
  WhatsApp links, CTAs, copyright year, mobile viewport, HTTPS and parked/"coming soon" markers.
- Instagram / TikTok: **user-provided social snapshot** (bio, followers, dated recent posts, engagement) or search snippets.
  Official APIs plug in later and write to the same `observations` table.
- Website lookup: with a search provider, `"<business>" <city>` is searched and a plausible own domain is offered as a
  *suggestion* to confirm. "No website found" is recorded only when a check was actually performed.

## 7. AI analysis strategy
- Input: the lead record plus numbered evidence items (`obs:12`). Output (JSON-schema constrained): summary, proposed
  signals from a fixed catalogue (each citing evidence ids), pain points (each citing evidence), how Kard helps, pitch angle,
  and four outreach drafts.
- The server validates citations: anything citing no real evidence id is dropped. AI signals are labelled `AI` in the UI.
- Runs only on request, is skipped when the evidence hash is unchanged (unless forced), and is logged with token cost.
- Model `claude-opus-5` by default (`ANTHROPIC_MODEL` overrides), effort `medium`, server-side refusal fallback enabled.

## 8. Kard scoring algorithm (deterministic, `radar/scoring.py`)
| Category | Default weight | Signals (raw points) | Cap |
|---|---|---|---|
| Business fit | 20 | Nigerian 5 · target industry 5 · sells a product/service 5 · customer-facing 5 | 20 |
| Social activity | 20 | posted recently 5 · consistent posting 5 · active IG/TikTok presence 5 · engagement evidence 5 | 20 |
| Digital presence gap | 30 | no website found 10 · weak website 5 · no useful landing page 5 · weak link-in-bio 5 · key info hard to find 5 | 30 |
| Buying signals | 20 | +5 per distinct signal inside the recency window; undated 3; stale 0 | 20 |
| Accessibility | 10 | Instagram 3 · TikTok 2 · WhatsApp/phone 2 · email 1 · decision-maker identifiable 2 | 10 |

`category score = raw / cap × weight`; weights are editable and must total 100. Every line item carries a state
(yes / no / unknown), a reason and evidence references. Unknown never earns points and is displayed as "Unknown".

- **Kard Fit** (need) = 60% digital gap + 25% business fit + 15% friction depth (distinct customer-journey frictions).
- **Business Quality** (establishment) = 35% social activity + 25% brand/presentation + 15% audience size (banded, supporting only)
  + 15% marketing activity + 10% contactability.
- **Confidence**: High / Medium / Low from evidence-source coverage and the share of Unknown checks.
- **Today's 20** priority = opportunity × 0.55 + buying-signal recency (≤20) + confidence (≤10) + accessibility (≤10)
  + follow-up due (+15). Leads already in play or closed are excluded.

## 9. Social-platform data strategy
No scraping, no logged-in automation and no headless browsers against Instagram/TikTok. Allowed inputs are search-engine
results, user-entered snapshots, CSV exports and (future) Instagram Graph API / TikTok APIs once approved. Platform domains
are on a hard block-list inside the fetcher.

## 10. API requirements and restrictions
| Integration | Env var | Needed for | Notes |
|---|---|---|---|
| Anthropic Claude | `ANTHROPIC_API_KEY` | AI analysis + AI outreach | optional; template outreach works without it |
| Serper | `SERPER_API_KEY` | web / IG / TikTok discovery via Google results | paid per query, trial credits |
| Brave Search | `BRAVE_SEARCH_API_KEY` | alternative search provider | free tier available |
| Google Places (New) | `GOOGLE_PLACES_API_KEY` | restaurants, hotels, venues with phone/website | billing account required |
| Instagram Graph / TikTok | — | future | app review; business-account scopes only |

## 11. Authentication / security
- Single-admin password (`ADMIN_PASSWORD`), HMAC-signed HttpOnly `SameSite=Strict` cookie (`SESSION_SECRET`), login rate limiting.
- Mutations require an `X-Requested-With` header (CSRF defence in depth). Strict CSP, `X-Frame-Options: DENY`, `nosniff`, no referrer.
- Keys live only in the environment / `.env` (git-ignored); `/api/status` reports whether a key is set, never its value.
- The fetcher blocks private/loopback/link-local IPs and non-HTTP schemes (SSRF). Only business-public data is stored.

## 12. Deployment architecture
- Any host that runs a long-lived Python process: Render, Railway, Fly.io or a VPS: `python server.py --host 0.0.0.0 --port $PORT`.
- SQLite on a persistent volume for a single team; set `DATABASE_URL` to Postgres/Supabase for managed storage
  (adapter included; needs `psycopg`; not exercised in this environment).
- Vercel is a poor fit for V1 (serverless, ephemeral disk). A future Next.js frontend could live on Vercel against this API.

## 13. Cost considerations
- Deterministic rules run first and are free; AI runs only on demand and is cached by evidence hash.
- Rough AI cost per lead at ~4k input / ~1.5k output tokens: `claude-opus-5` ≈ $0.06, `claude-sonnet-5` ≈ $0.02.
- Search APIs: about 3 queries per discovery run; website fetches are cached for 7 days.
- Every AI call's tokens and estimated cost are stored in `ai_runs` and shown in Settings.

## 14. V1 vs future
**V1:** lead DB, discovery (providers + paste URLs + playbook), manual add, CSV import/export, dedupe, website research,
social snapshots, rule signals, deterministic scoring with full explanations, AI analysis + outreach, Today's 20, filters,
CRM statuses / activities / follow-ups, outcome tracking, dashboard, strategy settings.

**Future:** Instagram Graph / TikTok APIs, Google Sheets sync, background job queue with scheduled re-research,
multi-user roles, conversion analytics (which features correlate with Won), per-industry weight presets, more countries.
