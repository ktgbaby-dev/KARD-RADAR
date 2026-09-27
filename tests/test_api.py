"""End-to-end API tests against a real server thread, with local fakes for the web and the Anthropic API.

Nothing here touches the internet: websites are served from 127.0.0.1 (KARD_ALLOW_PRIVATE_FETCH=1, test-only),
the Anthropic SDK is pointed at a local fake via ANTHROPIC_BASE_URL, and search providers are stubbed."""
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp()
os.environ.update({
    "KARD_DB_PATH": os.path.join(TMP, "api.db"), "ADMIN_PASSWORD": "test-password-123", "SESSION_SECRET": "x" * 64,
    "KARD_ALLOW_PRIVATE_FETCH": "1", "ANTHROPIC_API_KEY": "test-key-not-real", "SERPER_API_KEY": "", "BRAVE_SEARCH_API_KEY": "",
    "GOOGLE_PLACES_API_KEY": "",
})

from radar import discovery, normalize as N  # noqa: E402
from radar.config import get_config  # noqa: E402
from radar.db import Database  # noqa: E402
from radar.web import make_server  # noqa: E402

# ------------------------------------------------------------------ fake public website
SITE_HTML = """<html><head><title>Adire Loom Studio</title><meta name="description" content="Hand-dyed adire"></head>
<body><h1>Adire Loom</h1><p>Hand-dyed adire fabrics. Pre-order now open. © 2018</p>
<a href="https://wa.me/2348099990000">WhatsApp</a><a href="https://www.instagram.com/adireloom.test/">Instagram</a></body></html>"""
LINKTREE_HTML = """<html><head><title>adireloom | Linktree</title></head><body>
<a href="http://127.0.0.1:{port}/site">Our website</a><a href="https://wa.me/2348099990000">Order on WhatsApp</a></body></html>"""


class FakeWeb(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeWeb.hits.append(self.path)
        if self.path == "/robots.txt":
            body, code = b"User-agent: *\nDisallow: /private\n", 200
        elif self.path == "/site":
            body, code = SITE_HTML.encode(), 200
        elif self.path == "/tree":
            body, code = LINKTREE_HTML.replace("{port}", str(self.server.server_address[1])).encode(), 200
        elif self.path == "/private":
            body, code = b"secret", 200
        else:
            body, code = b"not found", 404
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8" if code == 200 else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ------------------------------------------------------------------ fake Anthropic Messages API
class FakeAnthropic(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAnthropic.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        prompt = body["messages"][0]["content"]
        ids = re.findall(r"\[(obs:\d+)\]", prompt)
        real = ids[0] if ids else "field:business_name"
        result = {
            "summary": "Active adire brand pushing pre-orders; customers are sent to WhatsApp with no central page.",
            "signals": [
                {"code": "scattered_product_info", "evidence_ids": [real], "note": "Products only in posts", "date": ""},
                {"code": "hiring", "evidence_ids": ["obs:999999"], "note": "invented", "date": ""},
            ],
            "pain_points": [{"problem": "Ordering happens in WhatsApp with no catalogue", "evidence_ids": [real]},
                            {"problem": "Made-up problem", "evidence_ids": ["obs:424242"]}],
            "how_kard_helps": "One branded page with the fabrics, pre-order form and WhatsApp.",
            "pitch_angle": "Pre-order hub for Adire Loom",
            "founder_name": "Invented Person",
            "outreach": {"instagram": "Saw the pre-orders are open. Customers currently jump straight to WhatsApp…",
                         "tiktok": "Saw the pre-order post…", "whatsapp": "Hello, saw your pre-orders…",
                         "email_subject": "A home for the pre-orders", "email_body": "Hi Adire Loom team, …\n\nKal's Digital"},
        }
        msg = {"id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
               "content": [{"type": "text", "text": json.dumps(result)}], "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 1500, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
        raw = json.dumps(msg).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class StubSearch(discovery.SearchProvider):
    name = "stub"

    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.results


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = _serve(FakeWeb)
        cls.webport = cls.web.server_address[1]
        cls.claude = _serve(FakeAnthropic)
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{cls.claude.server_address[1]}"
        cfg = get_config()
        cls.db = Database(cfg)
        cls.srv = make_server("127.0.0.1", 0, cfg, cls.db, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.jar = http.cookiejar.CookieJar()
        cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.jar))

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.web, cls.claude):
            s.shutdown()

    def call(self, method, path, body=None, csrf=True, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if csrf and method != "GET":
            req.add_header("X-Requested-With", "KardRadar")
        try:
            with self.opener.open(req, timeout=30) as r:
                payload = r.read()
                return r.status, (payload.decode("utf-8") if raw else json.loads(payload)), dict(r.headers)
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload), dict(e.headers)
            except ValueError:
                return e.code, payload.decode(), dict(e.headers)

    def login(self):
        s, _, _ = self.call("POST", "/api/login", {"password": "test-password-123"})
        self.assertEqual(s, 200)

    # --------------------------------------------------------------- security
    def test_01_auth_and_csrf(self):
        s, b, h = self.call("GET", "/api/leads")
        self.assertEqual(s, 401)
        self.assertEqual(h.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", h.get("Content-Security-Policy", ""))
        s, _, _ = self.call("POST", "/api/login", {"password": "wrong"})
        self.assertEqual(s, 401)
        self.login()
        s, _, _ = self.call("POST", "/api/leads", {"business_name": "X"}, csrf=False)
        self.assertEqual(s, 403)
        cookie = next(c for c in self.jar if c.name == "kr_session")
        self.assertTrue(cookie.has_nonstandard_attr("HttpOnly") or "HttpOnly" in str(cookie._rest))

    def test_02_status_never_exposes_keys(self):
        self.login()
        s, b, _ = self.call("GET", "/api/status")
        self.assertEqual(s, 200)
        text = json.dumps(b)
        self.assertNotIn("test-key-not-real", text)
        self.assertNotIn("test-password-123", text)
        self.assertTrue(b["ai"]["configured"])
        _, settings, _ = self.call("GET", "/api/settings")
        self.assertNotIn("test-key-not-real", json.dumps(settings))
        for f in (ROOT / "static").rglob("*"):
            if f.is_file() and f.suffix in (".js", ".html", ".css"):
                t = f.read_text(encoding="utf-8")
                self.assertNotRegex(t, r"sk-ant-|ANTHROPIC_API_KEY\s*=|SERPER_API_KEY\s*=", f.name)
        s, body, _ = self.call("GET", "/../../.env", raw=True)
        self.assertNotIn("SESSION_SECRET", body)

    # --------------------------------------------------------------- lead lifecycle
    def test_03_manual_lead_research_and_dedupe(self):
        self.login()
        s, b, _ = self.call("POST", "/api/leads", {
            "business_name": "Adire Loom Studio", "instagram_url": "@adireloom.test", "industry": "artisans", "city": "Osogbo",
            "link_in_bio_url": f"http://127.0.0.1:{self.webport}/tree", "analyze": True})
        self.assertEqual(s, 200, b)
        lead = b["lead"]
        self.assertEqual(lead["state"], "Osun")
        self.assertEqual(lead["industry"], "Artisans")
        self.assertEqual(lead["link_in_bio_type"], "own_website")  # 127.0.0.1 counts as a website host in tests
        type(self).lead_id = lead["id"]
        # website discovered via bio link, fetched, analysed; WhatsApp extracted
        self.assertEqual(lead["website_status"], "has_website")
        self.assertIsNotNone(lead["website_quality"])
        self.assertEqual(lead["whatsapp"], "+2348099990000")
        self.assertTrue(any(o["kind"] == "website" for o in lead["observations"]))
        self.assertIsNotNone(lead["opportunity_score"])
        self.assertEqual(len([m for m in lead["outreach"] if m["generator"] == "template"]), 4)
        # duplicate by handle -> 409
        s, b, _ = self.call("POST", "/api/leads", {"business_name": "Totally different", "instagram_url": "https://instagram.com/adireloom.test"})
        self.assertEqual(s, 409)
        self.assertEqual(b["matches"][0]["match_on"], ["Instagram"])
        # duplicate by phone -> 409
        s, b, _ = self.call("POST", "/api/leads", {"business_name": "Other", "whatsapp": "0809 999 0000"})
        self.assertEqual(s, 409)
        # probable duplicate by name + city -> 409, but force creates
        s, b, _ = self.call("POST", "/api/leads", {"business_name": "ADIRE LOOM STUDIO Ltd", "city": "Osogbo", "analyze": False})
        self.assertEqual(s, 409)
        self.assertEqual(b["matches"][0]["strength"], "probable")
        s, b, _ = self.call("POST", "/api/leads", {"business_name": "Adire Loom Studio", "city": "Ibadan", "analyze": False})
        self.assertEqual(s, 200, "different city is not a duplicate")

    def test_04_robots_and_platform_block(self):
        from radar import fetcher
        cfg = get_config()
        with self.db.connect() as c:
            r = fetcher.fetch(c, f"http://127.0.0.1:{self.webport}/private", cfg, refresh=True)
            self.assertIn("robots", r.error)
            r = fetcher.fetch(c, "https://www.instagram.com/someone/", cfg, refresh=True)
            self.assertIn("not fetched", r.error)
        os.environ["KARD_ALLOW_PRIVATE_FETCH"] = "0"
        try:
            with self.db.connect() as c:
                r = fetcher.fetch(c, f"http://127.0.0.1:{self.webport}/site", get_config(), refresh=True)
                self.assertIn("private", r.error.lower())
        finally:
            os.environ["KARD_ALLOW_PRIVATE_FETCH"] = "1"

    def test_05_snapshot_signals_scoring(self):
        self.login()
        lid = self.lead_id
        d = lambda n: (N.today() - timedelta(days=n)).isoformat()  # noqa: E731
        s, b, _ = self.call("POST", f"/api/leads/{lid}/social", {
            "platform": "instagram", "followers": "3.4k", "bio": "Hand-dyed adire 🇳🇬 | DM for price | 📍 Osogbo",
            "posts": f"{d(1)} | New collection of indigo adire just dropped!\n{d(4)} | Pop-up at Osogbo Art Market this Saturday\n"
                     f"{d(6)} | Restocked due to demand\n{d(9)} | Behind the scenes",
            "avg_likes": 60, "avg_comments": 8, "no_link_in_bio": False})
        self.assertEqual(s, 200, b)
        lead = b["lead"]
        bd = lead["score_breakdown"]
        buy = next(c for c in bd["categories"] if c["key"] == "buying_signals")
        codes = {i["code"] for i in buy["items"] if i["points"] > 0}
        self.assertTrue({"new_collection", "event"} <= codes, codes)
        self.assertEqual(lead["latest_buying_signal_at"], d(1))
        for c in bd["categories"]:
            for i in c["items"]:
                self.assertIn(i["state"], ("yes", "no", "unknown", "stale"))
        self.assertTrue(bd["why"])
        # manual override changes the score and is recorded
        before = lead["opportunity_score"]
        s, b, _ = self.call("POST", f"/api/leads/{lid}/signals", {"code": "decision_maker", "state": "yes", "note": "Founder is Kemi"})
        self.assertEqual(s, 200)
        self.assertGreater(b["opportunity_score"], before)
        s, b, _ = self.call("POST", f"/api/leads/{lid}/signals", {"code": "decision_maker", "state": "clear"})
        self.assertEqual(b["opportunity_score"], before)

    def test_06_ai_flow_validates_citations_and_caches(self):
        self.login()
        lid = self.lead_id
        FakeAnthropic.requests.clear()
        s, b, _ = self.call("POST", f"/api/leads/{lid}/ai", {})
        self.assertEqual(s, 200, b)
        req = FakeAnthropic.requests[-1]
        self.assertEqual(req["body"]["model"], "claude-opus-5")
        self.assertEqual(req["body"]["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["body"]["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", req["headers"].get("anthropic-beta", req["headers"].get("Anthropic-Beta", "")))
        res = b["result"]
        self.assertEqual([x["code"] for x in res["signals"]], ["scattered_product_info"])  # invented-evidence signal dropped
        self.assertEqual(len(res["pain_points"]), 1)
        dropped = {(x["type"], x.get("code") or x.get("value") or x.get("problem")) for x in res["dropped"]}
        self.assertIn(("signal", "hiring"), dropped)
        self.assertIn(("founder_name", "Invented Person"), dropped)
        lead = b["lead"]
        self.assertEqual(lead["founder_name"], "")
        self.assertTrue(any(m["generator"] == "ai" for m in lead["outreach"]))
        self.assertEqual(lead["ai_status"], "current")
        self.assertTrue(lead["ai_summary"])
        # unchanged evidence -> no second API call
        n = len(FakeAnthropic.requests)
        s, b, _ = self.call("POST", f"/api/leads/{lid}/ai", {})
        self.assertTrue(b["result"]["skipped"])
        self.assertEqual(len(FakeAnthropic.requests), n)
        # new evidence -> stale
        s, b, _ = self.call("POST", f"/api/leads/{lid}/observations", {"kind": "post", "content": "Now hiring a studio assistant", "observed_at": N.today().isoformat()})
        self.assertEqual(b["ai_status"], "stale")
        # force re-run
        s, b, _ = self.call("POST", f"/api/leads/{lid}/ai", {"force": True})
        self.assertFalse(b["result"]["skipped"])
        with self.db.connect() as c:
            runs = c.all("SELECT * FROM ai_runs WHERE lead_id = ? AND status = 'ok'", [lid])
        self.assertGreaterEqual(len(runs), 2)
        self.assertGreater(runs[0]["est_cost_usd"], 0)

    def test_07_crm_status_outcomes_today(self):
        self.login()
        lid = self.lead_id
        s, b, _ = self.call("GET", "/api/today")
        self.assertIn(lid, [l["id"] for l in b["leads"]])
        s, b, _ = self.call("POST", f"/api/leads/{lid}/contacted", {"channel": "instagram", "follow_up_days": 3})
        self.assertEqual(b["status"], "Contacted")
        self.assertEqual(b["outcome"]["contacted"], 1)
        self.assertIsNotNone(b["outcome"]["score_at_contact"])
        self.assertEqual(b["follow_up_at"], (N.today() + timedelta(days=3)).isoformat())
        s, b, _ = self.call("GET", "/api/today")
        self.assertNotIn(lid, [l["id"] for l in b["leads"]], "contacted leads leave the queue until follow-up is due")
        s, b, _ = self.call("POST", f"/api/leads/{lid}/followup", {"date": N.today().isoformat()})
        s, b, _ = self.call("GET", "/api/today")
        self.assertIn(lid, [l["id"] for l in b["leads"]], "follow-up due brings it back")
        s, b, _ = self.call("POST", f"/api/leads/{lid}/replied", {"note": "Asked for prices"})
        self.assertEqual(b["status"], "Replied")
        s, b, _ = self.call("POST", f"/api/leads/{lid}/status", {"status": "Won"})
        self.assertEqual(b["outcome"]["purchased"], 1)
        s, b, _ = self.call("PUT", f"/api/leads/{lid}/outcome", {"revenue": 150000, "package": "Kard Pro"})
        self.assertEqual(b["outcome"]["revenue"], 150000)
        s, b, _ = self.call("POST", f"/api/leads/{lid}/status", {"status": "Nonsense"})
        self.assertEqual(s, 400)
        s, d, _ = self.call("GET", "/api/dashboard")
        self.assertGreaterEqual(d["counts"]["won"], 1)
        self.assertGreaterEqual(d["counts"]["revenue"], 150000)

    def test_08_filters(self):
        self.login()
        for q, expect in [("?has_instagram=1", True), ("?has_instagram=0", False), ("?city=Osogbo", True), ("?city=Kano", False),
                          ("?has_website=1", True), ("?q=adireloom", True), ("?contacted=1", True), ("?min_score=101", False),
                          ("?industry=Artisans&has_whatsapp=1", True), ("?buying_recent_days=7", True), ("?status=Won", True),
                          ("?confidence=High,Medium,Low&sort=fit", True), ("?recent_days=1", True), ("?has_email=1", False)]:
            s, b, _ = self.call("GET", "/api/leads" + q)
            self.assertEqual(s, 200, q)
            ids = [l["id"] for l in b["leads"]]
            self.assertEqual(self.lead_id in ids, expect, q)
        s, b, _ = self.call("GET", "/api/leads?min_score=abc")
        self.assertEqual(s, 400)

    def test_09_csv_round_trip(self):
        self.login()
        csv_text = ("Brand Name,IG,Website,Category,Location,WhatsApp,Email,Notes\n"
                    "Kemi Bakes,@kemibakes.test,,cafe,Ibadan,08031110000,kemi@example.org,from CSV\n"
                    "Adire Loom Studio,@adireloom.test,,,Osogbo,,hello@adireloom.test,merge me\n"
                    "Bad Email Co,,,,Lagos,,not-an-email,\n"
                    "=HYPERLINK(\"x\"),,,,Lagos,,,\n")
        s, r, _ = self.call("POST", "/api/import", {"csv": csv_text})
        self.assertEqual(s, 200, r)
        self.assertEqual(len(r["created"]), 2)  # Kemi Bakes + formula-named row (stored as text)
        self.assertEqual(len(r["merged"]), 1)
        self.assertIn("email", r["merged"][0]["fields_filled"])
        self.assertEqual(len(r["errors"]), 1)
        self.assertEqual(r["columns"]["IG"], "instagram_url")
        s, text, h = self.call("GET", "/api/export.csv", raw=True)
        self.assertEqual(s, 200)
        self.assertIn("attachment", h["Content-Disposition"])
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("kemibakes.test", text)
        # re-import the export: everything merges, nothing is duplicated
        s, r2, _ = self.call("POST", "/api/import", {"csv": text})
        self.assertEqual(len(r2["created"]), 0, r2)
        s, text2, _ = self.call("GET", "/api/export-learning.csv", raw=True)
        self.assertIn("score_at_contact", text2)

    def test_10_discovery(self):
        self.login()
        s, b, _ = self.call("POST", "/api/discover", {"location": "Lagos", "industry": "Fashion", "keywords": ["DM to order"]})
        self.assertEqual(b["status"], "no_provider")
        self.assertEqual(b["candidates"], [])
        stub = StubSearch([
            {"title": "Zuri Threads (@zurithreads.test) • Instagram photos and videos",
             "url": "https://www.instagram.com/zurithreads.test/", "snippet": "5,210 Followers · New collection out now! DM to order. Lekki, Lagos",
             "date": "2 days ago"},
            {"title": "Adire Loom (@adireloom.test) • Instagram", "url": "https://www.instagram.com/adireloom.test/", "snippet": "Adire"},
            {"title": "Top 10 fashion brands in Lagos", "url": "https://someblog.example/top-10", "snippet": "list"},
            {"title": "Mola Wears | TikTok", "url": "https://www.tiktok.com/@molawears.test/video/1", "snippet": "WhatsApp to order"},
        ])
        orig = discovery.providers
        discovery.providers = lambda cfg: [stub]
        import radar.pipeline as P
        P.providers = discovery.providers
        try:
            s, run, _ = self.call("POST", "/api/discover", {"location": "Lagos", "industry": "Fashion", "keywords": ["DM to order"],
                                                          "sources": ["instagram", "tiktok"]})
        finally:
            discovery.providers = orig
            P.providers = orig
        self.assertEqual(s, 200, run)
        self.assertEqual(len(stub.queries), 2)
        self.assertIn('site:instagram.com Fashion Lagos "DM to order"', stub.queries)
        by = {c["handle"] or c["platform"]: c for c in run["candidates"]}
        self.assertEqual(by["zurithreads.test"]["name_guess"], "Zuri Threads")
        self.assertIn("new_collection", by["zurithreads.test"]["snippet_signals"])
        self.assertEqual(by["adireloom.test"]["status"], "duplicate")
        self.assertEqual(by["article"]["platform"], "article")
        s, r, _ = self.call("POST", "/api/discover/import", {"candidate_ids": [by["zurithreads.test"]["id"], by["molawears.test"]["id"]],
                                                            "research": False})
        self.assertEqual([x["action"] for x in r["results"]], ["created", "created"])
        zid = r["results"][0]["lead_id"]
        s, z, _ = self.call("GET", f"/api/leads/{zid}")
        self.assertEqual(z["followers_instagram"], 5210)
        self.assertEqual(z["followers_source"], "search snippet (approx.)")
        snip = next(o for o in z["observations"] if o["kind"] == "search_snippet")
        self.assertEqual(snip["observed_at"], (N.today() - timedelta(days=2)).isoformat())
        self.assertEqual(z["website_status"], "unknown", "no website check was performed, so no gap is assumed")
        # importing the same candidate again does nothing
        s, r, _ = self.call("POST", "/api/discover/import", {"candidate_ids": [by["zurithreads.test"]["id"]]})
        self.assertEqual(r["results"], [])
        # paste URLs
        s, run2, _ = self.call("POST", "/api/discover/urls", {"urls": "https://www.instagram.com/zurithreads.test/\n@newbrand.test\nnot a url",
                                                             "location": "Abuja", "industry": "Beauty"})
        self.assertEqual(len(run2["candidates"]), 2)
        self.assertEqual(run2["candidates"][0]["status"], "duplicate")

    def test_11_settings_rescore(self):
        self.login()
        s, b, _ = self.call("PUT", "/api/settings", {"weights": {"business_fit": 50, "social_activity": 20, "digital_gap": 30, "buying_signals": 20, "accessibility": 10}})
        self.assertEqual(s, 400)
        self.assertIn("100", b["error"])
        s, before, _ = self.call("GET", f"/api/leads/{self.lead_id}")
        s, b, _ = self.call("PUT", "/api/settings", {"weights": {"business_fit": 10, "social_activity": 10, "digital_gap": 60, "buying_signals": 10, "accessibility": 10},
                                                     "min_opportunity_score": 60})
        self.assertEqual(s, 200, b)
        self.assertGreater(b["rescored"], 0)
        s, after, _ = self.call("GET", f"/api/leads/{self.lead_id}")
        self.assertEqual(after["score_breakdown"]["weights"]["digital_gap"], 60)
        self.assertNotEqual(before["opportunity_score"], after["opportunity_score"])
        self.call("PUT", "/api/settings", {"weights": {"business_fit": 20, "social_activity": 20, "digital_gap": 30, "buying_signals": 20, "accessibility": 10}})

    def test_12_static_and_archive(self):
        s, html, h = self.call("GET", "/", raw=True)
        self.assertEqual(s, 200)
        self.assertIn('<script type="module" src="/js/app.js">', html)
        s, js, h = self.call("GET", "/js/app.js", raw=True)
        self.assertIn("javascript", h["Content-Type"])
        self.login()
        s, b, _ = self.call("POST", "/api/leads", {"business_name": "Archive Me", "analyze": False})
        s, _, _ = self.call("DELETE", f"/api/leads/{b['lead']['id']}")
        self.assertEqual(s, 200)
        s, _, _ = self.call("GET", f"/api/leads/{b['lead']['id']}")
        self.assertEqual(s, 404)


if __name__ == "__main__":
    unittest.main()
