"""Research pipeline: COLLECT -> NORMALIZE -> DETECT -> (AI) -> SCORE -> OUTREACH.

Every step writes inspectable rows (observations, signals, snapshots) and returns human-readable step notes."""
import re

from . import ai as AI
from . import fetcher, outreach, scoring, website
from . import leads as L
from . import normalize as N
from . import signals as S
from .config import Config
from .db import Conn, dumps, loads
from .dedupe import find_duplicates
from .discovery import candidate_lead_fields, providers

MANUAL_KINDS = {"manual_note", "post", "bio"}


def add_observation(conn: Conn, lead_id: int, kind: str, content: str, source: str, source_url: str = "",
                    observed_at=None, meta: dict | None = None) -> int:
    d = N.to_date(observed_at) if observed_at else None
    return conn.insert("observations", {
        "lead_id": lead_id, "kind": kind, "source": source, "source_url": N.clean_text(source_url, 1000),
        "content": N.clean_text(content, 6000), "observed_at": d.isoformat() if d else None,
        "collected_at": N.now_iso(), "meta": dumps(meta or {})})


def _fill_from_extracted(conn: Conn, lead: dict, ext: dict, settings: dict, source: str) -> list[str]:
    """Fill blank contact / social fields from a fetched page. Never overwrites existing values."""
    data, filled = {}, []
    if ext.get("emails") and not lead.get("email"):
        data["email"] = ext["emails"][0]
        filled.append(f"email {ext['emails'][0]}")
    if ext.get("whatsapp") and not lead.get("whatsapp"):
        data["whatsapp"] = ext["whatsapp"][0]
        filled.append("WhatsApp number")
    if ext.get("phones") and not lead.get("phone"):
        data["phone"] = ext["phones"][0]
        filled.append("phone number")
    socials = ext.get("socials") or {}
    if socials.get("instagram") and not lead.get("instagram_handle") and N.instagram_handle(socials["instagram"]):
        data["instagram_url"] = socials["instagram"]
        filled.append("Instagram")
    if socials.get("tiktok") and not lead.get("tiktok_handle") and N.tiktok_handle(socials["tiktok"]):
        data["tiktok_url"] = socials["tiktok"]
        filled.append("TikTok")
    other = loads(lead.get("other_socials"), {}) if isinstance(lead.get("other_socials"), str) else (lead.get("other_socials") or {})
    changed = False
    for k in ("facebook", "x", "youtube", "linkedin"):
        if socials.get(k) and not other.get(k):
            other[k] = socials[k]
            changed = True
            filled.append(k.capitalize())
    if changed:
        data["other_socials"] = other
    if data:
        try:
            L.update(conn, lead["id"], data, settings)
            L.log(conn, lead["id"], "enriched", detail=f"From {source}: " + ", ".join(filled))
        except L.DuplicateError as e:
            L.log(conn, lead["id"], "enriched", detail=f"Skipped enrichment from {source}: it matches lead #{e.matches[0]['lead_id']}")
            return []
    return filled


def research(conn: Conn, lead_id: int, settings: dict, cfg: Config, refresh: bool = False,
             lookup_website: bool = True, provider_list=None) -> dict:
    lead = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if not lead:
        raise KeyError(lead_id)
    steps = []
    cache_days = int(settings["research_cache_days"])

    # 1) link in bio (first: it can reveal the website)
    lib = lead.get("link_in_bio_url")
    if lib:
        ltype = N.link_in_bio_type(lib)
        target = lib
        if ltype == "shortener":
            res = fetcher.fetch(conn, lib, cfg, refresh, cache_days)
            if res.final_url and res.final_url != lib:
                target = res.final_url
                ltype = N.link_in_bio_type(target)
                steps.append(f"Bio short-link resolves to {N.host_of(target)}")
        conn.update("leads", lead_id, {"link_in_bio_type": ltype})
        if ltype == "own_website" and not lead.get("website_url"):
            L.update(conn, lead_id, {"website_url": target}, settings)
            steps.append(f"Bio link is the business website ({N.host_of(target)})")
        elif ltype in ("generic_link_page", "storefront"):
            res = fetcher.fetch(conn, target, cfg, refresh, cache_days)
            an = website.analyze(res.body or "", target, res.status, res.elapsed_ms, res.error or "", res.final_url or "")
            conn.run("DELETE FROM observations WHERE lead_id = ? AND kind = 'link_in_bio' AND source = 'link_fetch'", [lead_id])
            if an["status_label"] == "ok":
                links = "; ".join(f"{l['text'] or l['kind']}: {l['url']}" for l in an["extracted"]["links"][:15])
                add_observation(conn, lead_id, "link_in_bio", f"{an['title']} — {an['description']} — {an['text_excerpt'][:800]} — Links: {links}",
                                "link_fetch", target, meta={"type": ltype, "link_count": len(an["extracted"]["links"])})
                lead_now = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
                filled = _fill_from_extracted(conn, lead_now, an["extracted"], settings, "bio link page")
                own = [l["url"] for l in an["extracted"]["links"] if l["kind"] == "website" and N.business_domain(l["url"])]
                if own and not lead_now.get("website_url"):
                    L.update(conn, lead_id, {"website_url": own[0]}, settings)
                    filled.append(f"website {N.host_of(own[0])}")
                steps.append(f"Read bio link page ({N.host_of(target)})" + (f": found {', '.join(filled)}" if filled else ""))
            else:
                steps.append(f"Bio link page could not be read: {an['error'] or 'no content'}")

    # 2) website
    lead = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if lead.get("website_url"):
        url = lead["website_url"]
        res = fetcher.fetch(conn, url, cfg, refresh, cache_days)
        if res.get("blocked"):
            steps.append(f"Website not fetched: {res.error}")
        else:
            an = website.analyze(res.body or "", url, res.status, res.elapsed_ms, res.error or "", res.final_url or "")
            status = {"ok": "has_website", "parked": "parked", "unreachable": "unreachable"}[an["status_label"]]
            conn.run("DELETE FROM observations WHERE lead_id = ? AND kind = 'website' AND source = 'website_fetch'", [lead_id])
            if an["status_label"] != "unreachable":
                add_observation(conn, lead_id, "website",
                                " — ".join(x for x in [an["title"], an["description"], an["text_excerpt"]] if x),
                                "website_fetch", an["final_url"],
                                meta={"quality": an["quality"], "has_contact": an["has_contact"], "status": an["status_label"],
                                      "ctas": an["extracted"]["ctas"], "http_status": an["http_status"],
                                      "from_cache": bool(res.from_cache)})
            evidence = {"has_website": f"Website loaded ({N.host_of(an['final_url'])}) — quality {an['quality']}/100",
                        "parked": f"Website is a placeholder/parked page ({N.host_of(url)})",
                        "unreachable": f"Website did not load: {an['error'] or 'no response'}"}[status]
            conn.update("leads", lead_id, {"website_status": status, "website_quality": an["quality"],
                                           "website_quality_notes": dumps(an["notes"]), "website_evidence": evidence})
            steps.append(evidence + (" (cached)" if res.from_cache else ""))
            if an["status_label"] == "ok":
                filled = _fill_from_extracted(conn, conn.one("SELECT * FROM leads WHERE id = ?", [lead_id]),
                                              an["extracted"], settings, "website")
                if filled:
                    steps.append("Found on website: " + ", ".join(filled))

    # 3) website lookup via search (only when a provider is configured)
    lead = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if not lead.get("website_url") and lead.get("website_status") == "unknown" and lookup_website:
        provs = [p for p in (provider_list if provider_list is not None else providers(cfg)) if p.kind == "web"]
        if not provs:
            steps.append("Website status is Unknown — no search provider configured to check. Confirm manually on the lead.")
        else:
            steps.extend(_lookup_website(conn, lead, provs[0]))

    conn.update("leads", lead_id, {"last_researched_at": N.now_iso()})
    result = rescore(conn, lead_id, settings)
    L.log(conn, lead_id, "research", detail="; ".join(steps) or "Rules re-run on existing evidence")
    return {"steps": steps, "score": result}


def _lookup_website(conn: Conn, lead: dict, provider) -> list[str]:
    from .discovery import ProviderError
    name = lead["business_name"]
    q = f'"{name}" {lead.get("city") or ""}'.strip()
    try:
        results = provider.search(q)
    except ProviderError as e:
        return [f"Website lookup failed ({provider.name}): {e}"]
    tokens = [t for t in N.name_key(name) and [N.name_key(name)[:10]] or []] + \
             [w.lower() for w in name.split() if len(w) >= 4]
    for r in results[:10]:
        url = r.get("url") or ""
        dom = N.business_domain(url)
        if not dom or N.classify_url(url) != "website":
            continue
        hay = (dom + " " + (r.get("title") or "")).lower().replace("-", "")
        if any(t and t in hay for t in tokens):
            conn.update("leads", lead["id"], {"website_suggestion": url})
            return [f"Possible website found via search: {dom} — confirm it on the lead page"]
    msg = f"Web search for {q} on {N.today().isoformat()} found no website for the business"
    conn.update("leads", lead["id"], {"website_status": "none_found", "website_evidence": msg})
    add_observation(conn, lead["id"], "website_check", msg, provider.name)
    return [msg]


def rescore(conn: Conn, lead_id: int, settings: dict) -> dict:
    lead = L.decode(conn.one("SELECT * FROM leads WHERE id = ?", [lead_id]))
    obs = L.observations(conn, lead_id)
    rule_sigs = S.detect(lead, obs, settings)
    ts = N.now_iso()
    conn.run("DELETE FROM signals WHERE lead_id = ? AND detector = 'rule'", [lead_id])
    for s in rule_sigs:
        conn.insert("signals", {"lead_id": lead_id, "code": s["code"], "state": s["state"], "detector": "rule",
                                "detail": s["detail"][:600], "evidence": dumps(s["evidence"]), "signal_date": s["signal_date"],
                                "created_at": ts})
    resolved = S.resolve(L.signal_rows(conn, lead_id))
    result = scoring.score(lead, resolved, obs, settings)
    comp = outreach.compose(lead, result)
    ai_pains = lead.get("ai_pain_points") or []
    top_pain = result["top_pain"] or (ai_pains[0]["problem"] if ai_pains else "")
    lb = result["latest_buying_signal"]
    cats = {c["key"]: c for c in result["categories"]}
    upd = {
        "opportunity_score": result["opportunity"], "kard_fit": result["kard_fit"], "business_quality": result["business_quality"],
        "confidence": result["confidence"]["level"], "fit_points": cats["business_fit"]["points"],
        "social_points": cats["social_activity"]["points"], "gap_points": cats["digital_gap"]["points"],
        "buying_points": cats["buying_signals"]["points"], "access_points": cats["accessibility"]["points"],
        "buying_signal_count": result["buying_signal_count"],
        "latest_buying_signal_at": (lb or {}).get("date"), "latest_buying_signal": (lb or {}).get("label", ""),
        "top_reason": result["top_reason"][:400], "top_pain": top_pain[:400],
        "pitch_angle": (lead.get("ai_pitch_angle") or comp["pitch_angle"])[:200],
        "how_kard_helps": (lead.get("ai_how_kard_helps") or comp["how_kard_helps"])[:900],
        "score_breakdown": dumps({**result, "template_pitch_angle": comp["pitch_angle"], "needs_evidence": comp["needs_evidence"]}),
        "last_scored_at": ts, "updated_at": ts,
    }
    conn.update("leads", lead_id, upd)
    last = conn.one("SELECT opportunity_score, kard_fit, business_quality, confidence FROM score_snapshots WHERE lead_id = ? "
                    "ORDER BY id DESC LIMIT 1", [lead_id])
    if not last or (last["opportunity_score"], last["kard_fit"], last["business_quality"], last["confidence"]) != (
            result["opportunity"], result["kard_fit"], result["business_quality"], result["confidence"]["level"]):
        conn.insert("score_snapshots", {"lead_id": lead_id, "opportunity_score": result["opportunity"], "kard_fit": result["kard_fit"],
                                        "business_quality": result["business_quality"], "confidence": result["confidence"]["level"],
                                        "breakdown": dumps(result["categories"]), "weights": dumps(settings["weights"]),
                                        "created_at": ts})
    conn.run("DELETE FROM outreach_messages WHERE lead_id = ? AND generator = 'template'", [lead_id])
    for m in comp["messages"]:
        conn.insert("outreach_messages", {"lead_id": lead_id, "channel": m["channel"], "subject": m["subject"], "body": m["body"],
                                          "generator": "template", "grounding": dumps(comp["grounding"]), "created_at": ts})
    status = conn.scalar("SELECT status FROM leads WHERE id = ?", [lead_id])
    if settings.get("auto_qualify") and status in ("New", "Researching") and result["opportunity"] >= int(settings["min_opportunity_score"]):
        L.set_status(conn, lead_id, "Qualified", detail=f"Auto-qualified: opportunity {result['opportunity']} ≥ {settings['min_opportunity_score']}")
    return result


def run_ai(conn: Conn, lead_id: int, settings: dict, cfg: Config, force: bool = False) -> dict:
    lead = L.decode(conn.one("SELECT * FROM leads WHERE id = ?", [lead_id]))
    obs = L.observations(conn, lead_id)

    def prompt_now():
        lead_now = L.decode(conn.one("SELECT * FROM leads WHERE id = ?", [lead_id]))
        rows = [r for r in L.signal_rows(conn, lead_id) if r["detector"] != "ai"]
        return AI.build_input(lead_now, L.observations(conn, lead_id), S.resolve(rows))

    prompt, valid = prompt_now()
    h = AI.input_hash(prompt, cfg.anthropic_model)
    if not force and lead.get("ai_input_hash") == h:
        return {"skipped": True, "message": "AI analysis is already up to date — no new evidence since the last run. "
                                            "Use “Force refresh” to re-run it anyway."}
    ts = N.now_iso()
    try:
        data, usage = AI.call_claude(prompt, cfg)
    except AI.AIError as e:
        conn.insert("ai_runs", {"lead_id": lead_id, "purpose": "lead_analysis", "model": cfg.anthropic_model, "status": "error",
                                "input_hash": h, "error": str(e)[:500], "created_at": ts})
        raise
    evidence_text = " ".join(o.get("content") or "" for o in obs) + " " + (lead.get("profile_bio") or "")
    clean, dropped = AI.validate(data, valid, evidence_text)
    model = usage.get("model") or cfg.anthropic_model
    conn.run("DELETE FROM signals WHERE lead_id = ? AND detector = 'ai'", [lead_id])
    for s in clean["signals"]:
        conn.insert("signals", {"lead_id": lead_id, "code": s["code"], "state": "yes", "detector": "ai",
                                "detail": s["detail"], "evidence": dumps(s["evidence"]), "signal_date": s["signal_date"],
                                "created_at": ts})
    upd = {"ai_summary": clean["summary"], "ai_pain_points": dumps(clean["pain_points"]), "ai_pitch_angle": clean["pitch_angle"],
           "ai_how_kard_helps": clean["how_kard_helps"], "ai_model": model, "last_analyzed_at": ts}
    if clean["founder_name"] and not lead.get("founder_name"):
        upd["founder_name"] = clean["founder_name"]
    conn.update("leads", lead_id, upd)
    conn.run("DELETE FROM outreach_messages WHERE lead_id = ? AND generator = 'ai'", [lead_id])
    o = clean["outreach"]
    for ch, subject, body in (("instagram", "", o["instagram"]), ("tiktok", "", o["tiktok"]), ("whatsapp", "", o["whatsapp"]),
                              ("email", o["email_subject"], o["email_body"])):
        if body:
            conn.insert("outreach_messages", {"lead_id": lead_id, "channel": ch, "subject": subject, "body": body,
                                              "generator": "ai", "grounding": "[]", "created_at": ts})
    cost = AI.estimate_cost(cfg.anthropic_model, usage)
    conn.insert("ai_runs", {"lead_id": lead_id, "purpose": "lead_analysis", "model": model, "status": "ok", "input_hash": h,
                            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                            "cache_read_tokens": usage["cache_read_tokens"], "est_cost_usd": cost, "dropped": dumps(dropped),
                            "created_at": ts})
    L.log(conn, lead_id, "ai_analysis", detail=f"AI analysis ({model}): {len(clean['signals'])} signal(s), "
                                               f"{len(clean['pain_points'])} pain point(s), {len(dropped)} unsupported item(s) dropped; ≈${cost:.4f}")
    result = rescore(conn, lead_id, settings)
    prompt_after, _ = prompt_now()  # founder_name may have been filled — store the hash of the post-analysis state
    conn.update("leads", lead_id, {"ai_input_hash": AI.input_hash(prompt_after, cfg.anthropic_model)})
    return {"skipped": False, "signals": clean["signals"], "pain_points": clean["pain_points"], "dropped": dropped,
            "usage": usage, "est_cost_usd": cost, "score": result}


def ai_status(conn: Conn, lead_id: int, cfg: Config) -> str:
    """'never' | 'current' | 'stale' — whether the stored AI analysis matches today's evidence."""
    lead = L.decode(conn.one("SELECT * FROM leads WHERE id = ?", [lead_id]))
    if not lead.get("last_analyzed_at"):
        return "never"
    rows = [r for r in L.signal_rows(conn, lead_id) if r["detector"] != "ai"]
    prompt, _ = AI.build_input(lead, L.observations(conn, lead_id), S.resolve(rows))
    return "current" if AI.input_hash(prompt, cfg.anthropic_model) == lead.get("ai_input_hash") else "stale"


def add_social_snapshot(conn: Conn, lead_id: int, data: dict, settings: dict) -> dict:
    platform = data.get("platform")
    if platform not in ("instagram", "tiktok"):
        raise L.ValidationError("Platform must be instagram or tiktok")
    lead = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
    if not lead:
        raise KeyError(lead_id)
    upd = {}
    if data.get("profile_url"):
        upd[f"{platform}_url"] = data["profile_url"]
    if data.get("followers") not in (None, ""):
        upd[f"followers_{platform}"] = data["followers"]
        upd["followers_source"] = f"manual snapshot {N.today().isoformat()}"
    if data.get("link_in_bio_url"):
        upd["link_in_bio_url"] = data["link_in_bio_url"]
    if data.get("no_link_in_bio"):
        upd["no_link_in_bio"] = True
    if data.get("bio") and (platform == "instagram" or not lead.get("profile_bio")):
        upd["profile_bio"] = data["bio"]
    if upd:
        L.update(conn, lead_id, upd, settings)
    src = "manual snapshot"
    handle = (conn.one(f"SELECT {platform}_handle AS h FROM leads WHERE id = ?", [lead_id]) or {}).get("h") or ""
    purl = N.instagram_url(handle) if platform == "instagram" else N.tiktok_url(handle)
    added = 0
    if data.get("bio"):
        conn.run("DELETE FROM observations WHERE lead_id = ? AND kind = 'bio' AND source = ? AND meta LIKE ?",
                 [lead_id, src, f'%"platform": "{platform}"%'])
        add_observation(conn, lead_id, "bio", data["bio"], src, purl, meta={"platform": platform})
        added += 1
    stats = {k: data.get(k) for k in ("followers", "following", "posts_count", "posts_per_week") if data.get(k) not in (None, "")}
    if stats:
        add_observation(conn, lead_id, "social_stats",
                        f"{platform.capitalize()} snapshot: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in stats.items()),
                        src, purl, observed_at=N.today(), meta={"platform": platform, **stats})
        added += 1
    if data.get("avg_likes") not in (None, "") or data.get("avg_comments") not in (None, ""):
        add_observation(conn, lead_id, "engagement",
                        f"{platform.capitalize()} engagement: ~{data.get('avg_likes') or 0} likes, ~{data.get('avg_comments') or 0} comments per post",
                        src, purl, observed_at=N.today(),
                        meta={"platform": platform, "avg_likes": data.get("avg_likes"), "avg_comments": data.get("avg_comments")})
        added += 1
    posts = parse_posts(data.get("posts") or "")
    for d, caption in posts:
        add_observation(conn, lead_id, "post", caption or "(caption not recorded)", src, purl, observed_at=d, meta={"platform": platform})
        added += 1
    if data.get("last_post_date") and not posts:
        d = N.to_date(data["last_post_date"])
        if not d:
            raise L.ValidationError("Last post date is not valid")
        add_observation(conn, lead_id, "post", "Latest post (caption not recorded)", src, purl, observed_at=d, meta={"platform": platform})
        added += 1
    for code in ("strong_visual_branding",):
        if data.get(code) in (True, False):
            set_manual_signal(conn, lead_id, code, "yes" if data[code] else "no", "From social snapshot")
    L.log(conn, lead_id, "social_snapshot", detail=f"{platform.capitalize()} snapshot: {added} evidence item(s) added")
    result = rescore(conn, lead_id, settings)
    return {"added": added, "score": result}


def parse_posts(text: str) -> list[tuple]:
    """Lines like '2026-09-20 | New collection drops Friday' or '20/09/2026 - caption'. Undated lines keep no date."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\s*([^|\t]+?)\s*(?:\||\t| - | — | – )\s*(.*)$", line)
        d = None
        caption = line
        if m:
            d = N.parse_loose_date(m[1])
            if d:
                caption = m[2].strip()
        out.append((d, caption[:2000]))
    return out[:60]


def set_manual_signal(conn: Conn, lead_id: int, code: str, state: str, note: str = "") -> None:
    if code not in S.CATALOG:
        raise L.ValidationError("Unknown signal code")
    conn.run("DELETE FROM signals WHERE lead_id = ? AND code = ? AND detector = 'manual'", [lead_id, code])
    if state == "clear":
        L.log(conn, lead_id, "signal_override", detail=f"Cleared manual override for {S.CATALOG[code]['label']}")
        return
    if state not in ("yes", "no", "unknown"):
        raise L.ValidationError("State must be yes, no, unknown or clear")
    conn.insert("signals", {"lead_id": lead_id, "code": code, "state": state, "detector": "manual",
                            "detail": N.clean_text(note, 400) or "Set manually", "evidence": dumps(["manual"]),
                            "signal_date": N.today().isoformat() if S.CATALOG[code]["category"] == "buying_signals" and state == "yes" else None,
                            "created_at": N.now_iso()})
    L.log(conn, lead_id, "signal_override", detail=f"{S.CATALOG[code]['label']} set to {state}" + (f" — {note}" if note else ""))


def import_candidates(conn: Conn, candidate_ids: list[int], settings: dict, cfg: Config, do_research: bool = True,
                      provider_list=None) -> list[dict]:
    results = []
    researched = 0
    for cid in candidate_ids[:100]:
        c = conn.one("SELECT * FROM discovery_candidates WHERE id = ?", [cid])
        if not c or c["status"] == "imported":
            continue
        run = conn.one("SELECT params FROM discovery_runs WHERE id = ?", [c["run_id"]])
        params = loads(run["params"], {}) if run else {}
        c["extra"] = loads(c["extra"], {})
        c["followers"] = (c["extra"] or {}).get("followers")
        fields = candidate_lead_fields(c, params.get("location", ""), params.get("industry", ""))
        try:
            probe = L.prepare(fields, settings)
        except L.ValidationError as e:
            results.append({"candidate_id": cid, "action": "error", "error": str(e)})
            continue
        dups = find_duplicates(conn, probe)
        if dups:
            lead_id = dups[0]["lead_id"]
            existing = conn.one("SELECT * FROM leads WHERE id = ?", [lead_id])
            column = {"instagram_url": "instagram_handle", "tiktok_url": "tiktok_handle"}
            raw_upd = {k: v for k, v in fields.items()
                       if v not in (None, "", {}) and existing.get(column.get(k, k)) in (None, "", "{}")}
            if raw_upd:
                try:
                    L.update(conn, lead_id, raw_upd, settings)
                except L.DuplicateError:
                    pass
            action = "merged"
        else:
            lead_id = L.create(conn, fields, settings, source=f"discovery:{c['provider']}", force=True)
            action = "created"
        _candidate_evidence(conn, lead_id, c)
        conn.update("discovery_candidates", cid, {"status": "imported", "matched_lead_id": lead_id})
        if do_research and researched < 25:
            research(conn, lead_id, settings, cfg, provider_list=provider_list)
            researched += 1
        else:
            rescore(conn, lead_id, settings)
        lead = conn.one("SELECT business_name, opportunity_score, kard_fit, confidence, status FROM leads WHERE id = ?", [lead_id])
        results.append({"candidate_id": cid, "lead_id": lead_id, "action": action, **lead,
                        "meets_min": (lead["opportunity_score"] or 0) >= int(settings["min_opportunity_score"])})
    return results


def _candidate_evidence(conn: Conn, lead_id: int, c: dict) -> None:
    if c["provider"] == "pasted":
        return
    extra = c.get("extra") or {}
    if c["platform"] == "places":
        web = extra.get("website") or ""
        rating = f" — rating {extra['rating']} ({extra.get('rating_count') or 0} reviews)" if extra.get("rating") else ""
        content = (f"Google Maps listing: {c['title']} — {extra.get('category') or ''} — {extra.get('address') or ''} — "
                   f"phone {extra.get('phone') or 'not listed'} — website {web or 'not listed'}{rating}")
        add_observation(conn, lead_id, "places", content, "google_places", extra.get("maps_url") or c["url"],
                        meta={k: extra.get(k) for k in ("rating", "rating_count", "category")})
        lead = conn.one("SELECT website_status, website_url FROM leads WHERE id = ?", [lead_id])
        if not web and lead["website_status"] == "unknown" and not lead["website_url"]:
            conn.update("leads", lead_id, {"website_status": "none_found",
                                           "website_evidence": f"Google Maps listing shows no website (checked {N.today().isoformat()})"})
        return
    platform = "instagram" if c["platform"].startswith("instagram") else ("tiktok" if c["platform"] == "tiktok" else "")
    add_observation(conn, lead_id, "search_snippet", f"{c['title']} — {c['snippet']}", c["provider"], c["url"],
                    observed_at=c.get("result_date"), meta={"query": c.get("query"), "platform": platform})
