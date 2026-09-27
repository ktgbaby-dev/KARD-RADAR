"""JSON API routes. Handlers are thin: validate input, call a service module, return data."""
from . import ai as AI
from . import analytics, auth, csvio, discovery, pipeline, priority
from . import leads as L
from . import normalize as N
from .db import dumps
from .settings import CATEGORY_KEYS, SettingsError, get_settings, save_settings
from .signals import CATALOG
from .scoring import CATEGORIES
from .web import ApiError, Response, route


def _id(req, key="id") -> int:
    try:
        return int(req.params[key])
    except (KeyError, ValueError):
        raise ApiError(400, "Invalid id")


def _lead_or_404(conn, lead_id):
    lead = L.get_full(conn, lead_id)
    if not lead or lead.get("archived"):
        raise ApiError(404, "Lead not found")
    return lead


def _full(conn, req, lead_id):
    lead = _lead_or_404(conn, lead_id)
    lead["ai_status"] = pipeline.ai_status(conn, lead_id, req.cfg)
    return lead


class _Guard:
    """Translate domain errors into HTTP errors."""
    def __enter__(self):
        return self

    def __exit__(self, et, e, tb):
        if et is None:
            return False
        if isinstance(e, ApiError):
            return False
        if isinstance(e, L.DuplicateError):
            raise ApiError(409, "This looks like a lead you already have", matches=e.matches)
        if isinstance(e, (L.ValidationError, SettingsError, ValueError)):
            raise ApiError(400, str(e))
        if isinstance(e, KeyError):
            raise ApiError(404, "Not found")
        if isinstance(e, AI.AIError):
            raise ApiError(502, str(e))
        return False


# ------------------------------------------------------------------ auth

@route("POST", "/api/login", auth_required=False)
def login(req):
    ip = req.handler.client_address[0]
    if not req.cfg.admin_password or not req.cfg.session_secret:
        raise ApiError(503, "Server is not configured: set ADMIN_PASSWORD and SESSION_SECRET (run: python server.py --init)")
    if auth.throttled(ip):
        raise ApiError(429, "Too many failed attempts. Wait 10 minutes and try again.")
    if not auth.check_password(ip, str(req.body.get("password") or ""), req.cfg.admin_password):
        raise ApiError(401, "Incorrect password")
    token = auth.issue(req.cfg.session_secret)
    return Response(200, {"ok": True}, headers={"Set-Cookie": auth.cookie_header(token, req.cfg.secure_cookies)})


@route("POST", "/api/logout", auth_required=False)
def logout(req):
    return Response(200, {"ok": True}, headers={"Set-Cookie": auth.cookie_header("", req.cfg.secure_cookies, clear=True)})


@route("GET", "/api/me", auth_required=False)
def me(req):
    return {"authenticated": req.handler._authed(), "configured": bool(req.cfg.admin_password and req.cfg.session_secret)}


# ------------------------------------------------------------------ meta / status

@route("GET", "/api/meta")
def meta(req):
    with req.db.connect() as conn:
        s = get_settings(conn)
    return {"statuses": L.STATUSES, "channels": L.CHANNELS, "catalog": CATALOG,
            "categories": [{"key": k, "label": lbl, "cap": cap} for k, lbl, cap, _ in CATEGORIES],
            "industries": [i["name"] for i in s["target_industries"]], "cities": s["target_cities"],
            "min_opportunity_score": s["min_opportunity_score"], "high_opportunity_score": s["high_opportunity_score"],
            "weights": s["weights"], "buying_signal_window_days": s["buying_signal_window_days"],
            "social_activity_window_days": s["social_activity_window_days"]}


@route("GET", "/api/status")
def status(req):
    cfg = req.cfg
    return {"ai": {"configured": cfg.anthropic_key_set, "model": cfg.anthropic_model, "effort": cfg.ai_effort, "env": "ANTHROPIC_API_KEY"},
            "search": discovery.provider_status(cfg), "database": "postgresql" if cfg.database_url else "sqlite"}


# ------------------------------------------------------------------ leads

@route("GET", "/api/leads")
def list_leads(req):
    f = {k: v[0] for k, v in req.query.items()}
    with _Guard(), req.db.connect() as conn:
        return L.list_leads(conn, f, get_settings(conn))


@route("POST", "/api/leads/check-duplicates")
def check_duplicates(req):
    with _Guard(), req.db.connect() as conn:
        probe = L.prepare(req.body, get_settings(conn))
        from .dedupe import find_duplicates
        return {"matches": find_duplicates(conn, probe)}


@route("POST", "/api/leads")
def create_lead(req):
    b = req.body
    with _Guard(), req.db.connect() as conn:
        s = get_settings(conn)
        lead_id = L.create(conn, b, s, source="manual", force=bool(b.get("force")))
        if b.get("notes"):
            L.log(conn, lead_id, "note", detail=b["notes"])
        conn.commit()
        steps = []
        if b.get("analyze", True):
            steps = pipeline.research(conn, lead_id, s, req.cfg)["steps"]
        else:
            pipeline.rescore(conn, lead_id, s)
        conn.commit()
        ai_msg = None
        if b.get("ai") and req.cfg.anthropic_key_set:
            try:
                pipeline.run_ai(conn, lead_id, s, req.cfg)
            except AI.AIError as e:
                ai_msg = str(e)
        lead = _full(conn, req, lead_id)
        return {"lead": lead, "steps": steps, "ai_error": ai_msg}


@route("GET", "/api/leads/<id>")
def get_lead(req):
    with _Guard(), req.db.connect() as conn:
        return _full(conn, req, _id(req))


@route("PATCH", "/api/leads/<id>")
def patch_lead(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        s = get_settings(conn)
        _lead_or_404(conn, lead_id)
        L.update(conn, lead_id, req.body, s)
        pipeline.rescore(conn, lead_id, s)
        return _full(conn, req, lead_id)


@route("DELETE", "/api/leads/<id>")
def delete_lead(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        L.archive(conn, lead_id)
        return {"ok": True}


@route("POST", "/api/leads/<id>/research")
def research(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        r = pipeline.research(conn, lead_id, get_settings(conn), req.cfg, refresh=bool(req.body.get("refresh")))
        return {"steps": r["steps"], "lead": _full(conn, req, lead_id)}


@route("POST", "/api/leads/<id>/ai")
def ai_analysis(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        try:
            r = pipeline.run_ai(conn, lead_id, get_settings(conn), req.cfg, force=bool(req.body.get("force")))
        except AI.AIError as e:
            conn.commit()  # keep the ai_runs error log
            raise ApiError(502, str(e))
        return {"result": {k: v for k, v in r.items() if k != "score"}, "lead": _full(conn, req, lead_id)}


@route("POST", "/api/leads/<id>/analyze")
def analyze(req):
    """Full Kard analysis: research (collect + rules + score), then AI if configured and requested."""
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        s = get_settings(conn)
        r = pipeline.research(conn, lead_id, s, req.cfg, refresh=bool(req.body.get("refresh")))
        conn.commit()
        ai_result, ai_error = None, None
        if req.body.get("ai", True):
            if not req.cfg.anthropic_key_set:
                ai_error = "AI skipped: ANTHROPIC_API_KEY is not set. Rule-based analysis and template outreach are complete."
            else:
                try:
                    ai_result = pipeline.run_ai(conn, lead_id, s, req.cfg, force=bool(req.body.get("force")))
                    ai_result = {k: v for k, v in ai_result.items() if k != "score"}
                except AI.AIError as e:
                    conn.commit()
                    ai_error = str(e)
        return {"steps": r["steps"], "ai": ai_result, "ai_error": ai_error, "lead": _full(conn, req, lead_id)}


@route("POST", "/api/leads/<id>/social")
def social(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        r = pipeline.add_social_snapshot(conn, lead_id, req.body, get_settings(conn))
        return {"added": r["added"], "lead": _full(conn, req, lead_id)}


@route("POST", "/api/leads/<id>/observations")
def add_obs(req):
    lead_id = _id(req)
    b = req.body
    kind = b.get("kind") or "manual_note"
    if kind not in pipeline.MANUAL_KINDS:
        raise ApiError(400, "Evidence type must be a note, a post or a bio")
    content = N.clean_text(b.get("content"), 6000)
    if not content:
        raise ApiError(400, "Evidence text is required")
    if b.get("observed_at") and not N.to_date(b["observed_at"]):
        raise ApiError(400, "Date is not valid")
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        pipeline.add_observation(conn, lead_id, kind, content, "manual", b.get("source_url") or "", b.get("observed_at"),
                                 meta={"platform": b.get("platform")} if b.get("platform") else {})
        L.log(conn, lead_id, "evidence", detail=f"Added {kind.replace('_', ' ')}: {content[:120]}")
        pipeline.rescore(conn, lead_id, get_settings(conn))
        return _full(conn, req, lead_id)


@route("DELETE", "/api/leads/<id>/observations/<oid>")
def del_obs(req):
    lead_id, oid = _id(req), _id(req, "oid")
    with _Guard(), req.db.connect() as conn:
        o = conn.one("SELECT * FROM observations WHERE id = ? AND lead_id = ?", [oid, lead_id])
        if not o:
            raise ApiError(404, "Evidence not found")
        if o["source"] not in ("manual", "manual snapshot"):
            raise ApiError(400, "Only evidence you added can be removed; collected evidence refreshes on re-research")
        conn.run("DELETE FROM observations WHERE id = ?", [oid])
        L.log(conn, lead_id, "evidence", detail=f"Removed evidence: {o['content'][:120]}")
        pipeline.rescore(conn, lead_id, get_settings(conn))
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/signals")
def override_signal(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        pipeline.set_manual_signal(conn, lead_id, req.body.get("code"), req.body.get("state"), req.body.get("note") or "")
        pipeline.rescore(conn, lead_id, get_settings(conn))
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/website")
def website_action(req):
    lead_id = _id(req)
    action = req.body.get("action")
    with _Guard(), req.db.connect() as conn:
        lead = _lead_or_404(conn, lead_id)
        s = get_settings(conn)
        if action == "accept_suggestion" and lead.get("website_suggestion"):
            L.update(conn, lead_id, {"website_url": lead["website_suggestion"]}, s)
            pipeline.research(conn, lead_id, s, req.cfg, lookup_website=False)
        elif action == "reject_suggestion":
            conn.update("leads", lead_id, {"website_suggestion": ""})
            L.log(conn, lead_id, "website", detail="Rejected suggested website")
            pipeline.rescore(conn, lead_id, s)
        elif action == "confirm_none":
            L.update(conn, lead_id, {"website_url": "", "no_website_confirmed": True}, s)
            conn.update("leads", lead_id, {"website_suggestion": ""})
            L.log(conn, lead_id, "website", detail="Confirmed: no website")
            pipeline.rescore(conn, lead_id, s)
        else:
            raise ApiError(400, "Unknown website action")
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/status")
def set_status(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        L.set_status(conn, lead_id, req.body.get("status"), N.clean_text(req.body.get("note"), 1000))
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/contacted")
def contacted(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        L.mark_contacted(conn, lead_id, req.body.get("channel") or "instagram", N.clean_text(req.body.get("note"), 1000),
                         req.body.get("follow_up_days"))
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/replied")
def replied(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        lead = _lead_or_404(conn, lead_id)
        note = N.clean_text(req.body.get("note"), 1000)
        L.log(conn, lead_id, "replied", detail=note or "Lead replied", channel=req.body.get("channel") or "")
        if lead["status"] in ("New", "Researching", "Qualified", "Contacted", "Follow-up"):
            L.set_status(conn, lead_id, "Replied", detail=note)
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/followup")
def followup(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        L.set_follow_up(conn, lead_id, req.body.get("date"), N.clean_text(req.body.get("note"), 500))
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/<id>/notes")
def add_note(req):
    lead_id = _id(req)
    text = N.clean_text(req.body.get("text"), 4000)
    if not text:
        raise ApiError(400, "Note is empty")
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        L.log(conn, lead_id, "note", detail=text)
        return _full(conn, req, lead_id)


@route("PUT", "/api/leads/<id>/outcome")
def outcome(req):
    lead_id = _id(req)
    with _Guard(), req.db.connect() as conn:
        _lead_or_404(conn, lead_id)
        L.update_outcome(conn, lead_id, req.body)
        return _full(conn, req, lead_id)


@route("POST", "/api/leads/bulk")
def bulk(req):
    ids = [int(i) for i in (req.body.get("ids") or []) if str(i).isdigit()][:200]
    action = req.body.get("action")
    if not ids:
        raise ApiError(400, "Select at least one lead")
    done, errors = 0, []
    with _Guard(), req.db.connect() as conn:
        s = get_settings(conn)
        for lead_id in ids:
            try:
                if action == "research":
                    if done >= 25:
                        errors.append({"id": lead_id, "error": "Research is limited to 25 leads per batch"})
                        continue
                    pipeline.research(conn, lead_id, s, req.cfg)
                elif action == "status":
                    L.set_status(conn, lead_id, req.body.get("status"), "Bulk update")
                elif action == "archive":
                    L.archive(conn, lead_id)
                else:
                    raise ApiError(400, "Unknown bulk action")
                conn.commit()
                done += 1
            except (L.ValidationError, KeyError) as e:
                errors.append({"id": lead_id, "error": str(e)})
    return {"done": done, "errors": errors}


# ------------------------------------------------------------------ queue + dashboard

@route("GET", "/api/today")
def today(req):
    with req.db.connect() as conn:
        s = get_settings(conn)
        return {"leads": priority.todays_list(conn, s), "count": s["today_count"], "min_score": s["min_opportunity_score"]}


@route("GET", "/api/dashboard")
def dash(req):
    with req.db.connect() as conn:
        s = get_settings(conn)
        d = analytics.dashboard(conn, s)
        d["today"] = priority.todays_list(conn, s, limit=6)
        return d


# ------------------------------------------------------------------ discovery

@route("GET", "/api/discover")
def discover_home(req):
    with req.db.connect() as conn:
        return {"providers": discovery.provider_status(req.cfg), "runs": discovery.recent_runs(conn)}


@route("POST", "/api/discover")
def discover(req):
    with _Guard(), req.db.connect() as conn:
        return discovery.run_discovery(conn, req.body, req.cfg, get_settings(conn))


@route("POST", "/api/discover/urls")
def discover_urls(req):
    urls = req.body.get("urls") or []
    if isinstance(urls, str):
        urls = [u for u in urls.replace(",", "\n").splitlines()]
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        raise ApiError(400, "Paste at least one URL or @handle")
    with _Guard(), req.db.connect() as conn:
        return discovery.candidates_from_urls(conn, urls, req.body, get_settings(conn))


@route("GET", "/api/discover/<id>")
def discover_run(req):
    with _Guard(), req.db.connect() as conn:
        return discovery.get_run(conn, _id(req))


@route("POST", "/api/discover/import")
def discover_import(req):
    ids = [int(i) for i in (req.body.get("candidate_ids") or []) if str(i).isdigit()]
    if not ids:
        raise ApiError(400, "Select at least one candidate")
    with _Guard(), req.db.connect() as conn:
        s = get_settings(conn)
        results = pipeline.import_candidates(conn, ids, s, req.cfg, do_research=bool(req.body.get("research", True)))
        return {"results": results, "min_score": s["min_opportunity_score"]}


@route("POST", "/api/discover/dismiss")
def discover_dismiss(req):
    ids = [int(i) for i in (req.body.get("candidate_ids") or []) if str(i).isdigit()]
    with req.db.connect() as conn:
        for cid in ids:
            conn.run("UPDATE discovery_candidates SET status = 'dismissed' WHERE id = ? AND status <> 'imported'", [cid])
    return {"ok": True}


# ------------------------------------------------------------------ import / export

@route("POST", "/api/import")
def import_csv(req):
    text = req.body.get("csv") or ""
    with _Guard(), req.db.connect() as conn:
        s = get_settings(conn)
        report = csvio.import_csv(conn, text, s)
        for item in report["created"] + report["merged"]:
            pipeline.rescore(conn, item["lead_id"], s)
        return report


def _csv_response(text: str, filename: str) -> Response:
    return Response(200, text, "text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@route("GET", "/api/export.csv")
def export_csv(req):
    f = {k: v[0] for k, v in req.query.items()}
    with _Guard(), req.db.connect() as conn:
        return _csv_response(csvio.export_csv(conn, f, get_settings(conn)), f"kard-radar-leads-{N.today().isoformat()}.csv")


@route("GET", "/api/export-learning.csv")
def export_learning(req):
    with req.db.connect() as conn:
        return _csv_response(csvio.export_learning_csv(conn), f"kard-radar-outcomes-{N.today().isoformat()}.csv")


# ------------------------------------------------------------------ settings

@route("GET", "/api/settings")
def settings_get(req):
    with req.db.connect() as conn:
        s = get_settings(conn)
        usage = conn.all("SELECT model, COUNT(*) AS runs, COALESCE(SUM(input_tokens),0) AS input_tokens, "
                         "COALESCE(SUM(output_tokens),0) AS output_tokens, COALESCE(SUM(est_cost_usd),0) AS cost "
                         "FROM ai_runs WHERE status = 'ok' GROUP BY model")
        errors = conn.scalar("SELECT COUNT(*) AS n FROM ai_runs WHERE status = 'error'") or 0
        return {"settings": s, "category_keys": CATEGORY_KEYS, "ai_usage": usage, "ai_errors": errors,
                "status": status(req)}


@route("PUT", "/api/settings")
def settings_put(req):
    with _Guard(), req.db.connect() as conn:
        s = save_settings(conn, req.body)
        ids = [r["id"] for r in conn.all("SELECT id FROM leads WHERE archived = 0 AND last_scored_at IS NOT NULL")]
        for lead_id in ids:
            pipeline.rescore(conn, lead_id, s)
        return {"settings": s, "rescored": len(ids)}
