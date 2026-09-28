"""Unit tests: normalization, signal rules, scoring, dedupe, website analysis, CSV safety."""
import copy
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("KARD_DB_PATH", os.path.join(tempfile.mkdtemp(), "unit.db"))

from radar import normalize as N  # noqa: E402
from radar import scoring, signals, website  # noqa: E402
from radar.csvio import _safe_cell  # noqa: E402
from radar.settings import DEFAULTS, SettingsError, validate  # noqa: E402

S = copy.deepcopy(DEFAULTS)


def lead(**kw):
    base = {"id": 1, "business_name": "Test", "industry": "", "city": "", "country": "", "instagram_handle": "", "tiktok_handle": "",
            "website_status": "unknown", "website_quality": None, "link_in_bio_type": "unknown", "link_in_bio_url": "",
            "whatsapp": "", "phone": "", "phone_key": "", "email": "", "founder_name": "", "other_socials": "{}",
            "followers_instagram": None, "followers_tiktok": None, "address": "", "website_url": "", "website_domain": ""}
    base.update(kw)
    return base


def obs(i, kind, content, days_ago=None, **meta):
    return {"id": i, "kind": kind, "content": content, "source": "manual",
            "observed_at": (N.today() - timedelta(days=days_ago)).isoformat() if days_ago is not None else None, "meta": meta}


def run(l, o):
    sigs = signals.detect(l, o, S)
    return scoring.score(l, signals.resolve([{**s, "detector": "rule"} for s in sigs]), o, S)


class NormalizeTests(unittest.TestCase):
    def test_instagram_handles(self):
        self.assertEqual(N.instagram_handle("https://www.instagram.com/Zuri.Threads/?hl=en"), "zuri.threads")
        self.assertEqual(N.instagram_handle("@zuri_threads"), "zuri_threads")
        self.assertEqual(N.instagram_handle("https://instagram.com/p/Cx123/"), "")
        self.assertEqual(N.instagram_handle("instagram.com/stories/brand/123"), "brand")

    def test_tiktok_handles(self):
        self.assertEqual(N.tiktok_handle("https://www.tiktok.com/@brand.ng/video/123"), "brand.ng")
        self.assertEqual(N.tiktok_handle("@brand"), "brand")

    def test_phone_keys(self):
        self.assertEqual(N.phone_key("0803 123 4567"), "2348031234567")
        self.assertEqual(N.phone_key("+234 803 123 4567"), "2348031234567")
        self.assertEqual(N.phone_key("8031234567"), "2348031234567")
        self.assertEqual(N.whatsapp_from_url("https://wa.me/2348031234567?text=hi"), "2348031234567")
        self.assertEqual(N.whatsapp_from_url("https://api.whatsapp.com/send?phone=08031234567"), "2348031234567")

    def test_domains(self):
        self.assertEqual(N.business_domain("https://www.zurithreads.com/shop"), "zurithreads.com")
        self.assertEqual(N.business_domain("https://linktr.ee/zuri"), "")
        self.assertEqual(N.business_domain("https://zuri.bumpa.shop"), "zuri.bumpa.shop")
        self.assertEqual(N.link_in_bio_type("https://linktr.ee/zuri"), "generic_link_page")
        self.assertEqual(N.link_in_bio_type("https://wa.me/234803"), "whatsapp")
        self.assertEqual(N.link_in_bio_type("https://selar.co/zuri"), "storefront")

    def test_name_key(self):
        self.assertEqual(N.name_key("Zuri Threads Ltd."), N.name_key("ZURI THREADS"))
        self.assertEqual(N.name_key("Café Délice & Co"), "cafedeliceand")

    def test_dates(self):
        ref = N.today()
        self.assertEqual(N.parse_loose_date("3 days ago", ref), ref - timedelta(days=3))
        self.assertEqual(N.parse_loose_date("20/09/2026").isoformat(), "2026-09-20")
        self.assertEqual(N.parse_loose_date("Sep 20, 2026").isoformat(), "2026-09-20")
        self.assertIsNone(N.parse_loose_date("soon"))

    def test_snippet_parsing(self):
        self.assertEqual(N.followers_from_snippet("12.5K Followers, 300 Following, 410 Posts"), 12500)
        self.assertEqual(N.name_from_title("Zuri Threads (@zurithreads) • Instagram photos and videos"), "Zuri Threads")


class SignalTests(unittest.TestCase):
    def test_pain_phrases(self):
        o = [obs(1, "bio", "Luxury wigs | DM for price | WhatsApp to order 08031234567"),
             obs(2, "post", "PIP. Kindly send a DM", 2)]
        codes = {s["code"]: s for s in signals.detect(lead(), o, S)}
        self.assertEqual(codes["dm_for_price"]["state"], "yes")
        self.assertIn("obs:1", codes["dm_for_price"]["evidence"])
        self.assertEqual(codes["whatsapp_ordering"]["state"], "yes")

    def test_buying_signals_carry_dates(self):
        o = [obs(5, "post", "New collection just dropped!", 3), obs(6, "post", "We're hiring a sales rep", 40)]
        codes = {s["code"]: s for s in signals.detect(lead(), o, S)}
        self.assertEqual(codes["new_collection"]["signal_date"], (N.today() - timedelta(days=3)).isoformat())
        self.assertIn("hiring", codes)

    def test_unknown_is_not_a_gap(self):
        r = run(lead(instagram_handle="brand"), [])
        gap = next(c for c in r["categories"] if c["key"] == "digital_gap")
        self.assertEqual(gap["raw"], 0)
        no_web = next(i for i in gap["items"] if i["code"] == "no_website")
        self.assertEqual(no_web["state"], "unknown")
        self.assertEqual(r["confidence"]["level"], "Low")

    def test_no_website_only_when_checked(self):
        r = run(lead(website_status="none_found", website_evidence="checked"), [])
        gap = next(c for c in r["categories"] if c["key"] == "digital_gap")
        self.assertEqual(next(i for i in gap["items"] if i["code"] == "no_website")["points"], 10)

    def test_followers_do_not_drive_opportunity(self):
        small = lead(instagram_handle="a", website_status="none_found", link_in_bio_type="whatsapp", followers_instagram=4000,
                     industry="Fashion", city="Lagos", country="Nigeria")
        big = lead(instagram_handle="b", website_status="has_website", website_quality=92, link_in_bio_type="own_website",
                   link_in_bio_url="https://big.com", followers_instagram=250000, industry="Fashion", city="Lagos", country="Nigeria")
        o = [obs(1, "bio", "DM for price. WhatsApp to order")]
        rs, rb = run(small, o), run(big, [])
        self.assertGreater(rs["opportunity"], rb["opportunity"])
        self.assertGreater(rs["kard_fit"], rb["kard_fit"])
        self.assertGreater(rb["business_quality"] if rb["business_quality"] else 1, 0)


class ScoringTests(unittest.TestCase):
    def test_buying_cap_and_recency(self):
        o = [obs(1, "post", "New collection", 1), obs(2, "post", "Grand opening of our new branch", 2),
             obs(3, "post", "Pop-up this weekend", 3), obs(4, "post", "We're hiring", 4), obs(5, "post", "Rebrand reveal: new logo", 5),
             obs(6, "post", "Flash sale 20% off", 200)]
        r = run(lead(), o)
        buy = next(c for c in r["categories"] if c["key"] == "buying_signals")
        self.assertEqual(buy["raw"], 20)
        self.assertTrue(buy["capped"])
        stale = [i for i in buy["items"] if i["state"] == "stale"]
        self.assertEqual(stale[0]["code"], "promotion_ads")

    def test_undated_buying_gets_partial(self):
        r = run(lead(), [obs(1, "website", "Shop our new collection")])
        buy = next(c for c in r["categories"] if c["key"] == "buying_signals")
        self.assertEqual(buy["raw"], scoring.UNDATED_BUYING_POINTS)

    def test_weights_rescale(self):
        global S
        l = lead(website_status="none_found")
        base = run(l, [])["opportunity"]
        saved = S
        S = copy.deepcopy(S)
        S["weights"] = {"business_fit": 10, "social_activity": 10, "digital_gap": 60, "buying_signals": 10, "accessibility": 10}
        try:
            self.assertGreater(run(l, [])["opportunity"], base)
        finally:
            S = saved

    def test_every_point_is_explained(self):
        o = [obs(1, "bio", "Bridal wigs, DM for price 📍 Ikeja"), obs(2, "post", "Pre-order now open", 2)]
        r = run(lead(industry="Hair & wigs", city="Lagos", instagram_handle="w", whatsapp="+2348031234567"), o)
        total = sum(c["points"] for c in r["categories"])
        self.assertAlmostEqual(round(total), r["opportunity"])
        for c in r["categories"]:
            for i in c["items"]:
                if i["points"]:
                    self.assertTrue(i["detail"] or i["evidence"], i)

    def test_manual_override_wins_and_ai_fills_only_gaps(self):
        rows = [{"code": "sells_offering", "state": "unknown", "detector": "rule", "evidence": [], "detail": ""},
                {"code": "sells_offering", "state": "yes", "detector": "ai", "evidence": ["obs:1"], "detail": "ai"},
                {"code": "audience_engagement", "state": "no", "detector": "rule", "evidence": ["obs:2"], "detail": "low"},
                {"code": "audience_engagement", "state": "yes", "detector": "ai", "evidence": ["obs:2"], "detail": "ai"},
                {"code": "no_website", "state": "yes", "detector": "rule", "evidence": [], "detail": ""},
                {"code": "no_website", "state": "no", "detector": "manual", "evidence": [], "detail": "they do have one"}]
        res = signals.resolve(rows)
        self.assertEqual(res["sells_offering"]["detector"], "ai")
        self.assertEqual(res["audience_engagement"]["state"], "no")
        self.assertEqual(res["no_website"]["detector"], "manual")


class SettingsTests(unittest.TestCase):
    def test_weights_must_total_100(self):
        with self.assertRaises(SettingsError):
            validate({"weights": {"business_fit": 20, "social_activity": 20, "digital_gap": 30, "buying_signals": 20, "accessibility": 5}})
        ok = validate({"weights": {"business_fit": 25, "social_activity": 15, "digital_gap": 30, "buying_signals": 20, "accessibility": 10}})
        self.assertEqual(sum(ok["weights"].values()), 100)

    def test_unknown_setting_rejected(self):
        with self.assertRaises(SettingsError):
            validate({"hack": 1})


class WebsiteTests(unittest.TestCase):
    def test_good_site(self):
        html = """<html><head><title>Zuri Threads</title><meta name="viewport" content="width=device-width">
        <meta name="description" content="Ready to wear"></head><body><h1>Shop the collection</h1>
        <p>""" + ("Beautiful clothes made in Lagos. " * 40) + """</p><a href="/shop">Shop now</a>
        <a href="https://wa.me/2348031234567">Chat</a><a href="https://instagram.com/zuri">IG</a>
        <a href="mailto:hi@zuri.ng">Email</a><footer>© 2026 Zuri</footer></body></html>"""
        a = website.analyze(html, "https://zuri.ng", 200, 300, ref_year=2026)
        self.assertEqual(a["status_label"], "ok")
        self.assertGreaterEqual(a["quality"], 80)
        self.assertIn("hi@zuri.ng", a["extracted"]["emails"])
        self.assertIn("2348031234567", a["extracted"]["whatsapp"])
        self.assertIn("instagram", a["extracted"]["socials"])

    def test_weak_and_parked(self):
        weak = website.analyze("<html><body>Welcome. © 2017</body></html>", "http://old.ng", 200, 100, ref_year=2026)
        self.assertLess(weak["quality"], 55)
        self.assertTrue(any("2017" in n["text"] for n in weak["notes"]))
        parked = website.analyze("<html><title>Coming soon</title><body>Website coming soon</body></html>", "https://x.ng", 200)
        self.assertEqual(parked["status_label"], "parked")
        down = website.analyze("", "https://x.ng", None, error="Could not connect")
        self.assertEqual(down["status_label"], "unreachable")


class SerperFallbackTests(unittest.TestCase):
    def test_simplify(self):
        from radar.discovery import simplify_query
        self.assertEqual(simplify_query('site:instagram.com Fashion Lagos "DM to order"'), "instagram Fashion Lagos DM to order")
        self.assertEqual(simplify_query('site:www.tiktok.com wigs Abuja'), "tiktok wigs Abuja")
        self.assertEqual(simplify_query('Fashion Lagos Nigeria "new collection"'), "Fashion Lagos Nigeria new collection")

    def test_free_plan_rejection_retries_plain_query(self):
        from radar import discovery as D
        sent = []

        def fake_http(url, method="GET", headers=None, body=None, timeout=20):
            sent.append(body["q"])
            if "site:" in body["q"] or '"' in body["q"]:
                raise D.ProviderError('HTTP 400 {"message":"Query pattern not allowed for free accounts.","statusCode":400}')
            return {"organic": [{"title": "Zuri (@zuri.ng) • Instagram", "link": "https://www.instagram.com/zuri.ng/", "snippet": "DM to order"}]}

        orig, D._http_json = D._http_json, fake_http
        D.SerperProvider.operators_blocked = False
        try:
            p = D.SerperProvider("k")
            r1 = p.search('site:instagram.com Fashion Lagos "DM to order"')
            r2 = p.search('site:tiktok.com Fashion Lagos "DM to order"')
        finally:
            D._http_json = orig
            D.SerperProvider.operators_blocked = False
        self.assertEqual(sent, ['site:instagram.com Fashion Lagos "DM to order"', "instagram Fashion Lagos DM to order",
                                "tiktok Fashion Lagos DM to order"])  # 2nd query skips the doomed attempt
        self.assertEqual(r1[0]["url"], "https://www.instagram.com/zuri.ng/")
        self.assertEqual(len(p.notes), 1)
        self.assertEqual(len(r2), 1)

    def test_other_errors_still_raise(self):
        from radar import discovery as D

        def fake_http(*a, **k):
            raise D.ProviderError("HTTP 401 unauthorized")

        orig, D._http_json = D._http_json, fake_http
        try:
            with self.assertRaises(D.ProviderError):
                D.SerperProvider("bad").search("site:instagram.com x")
        finally:
            D._http_json = orig
            D.SerperProvider.operators_blocked = False


class CsvSafetyTests(unittest.TestCase):
    def test_formula_injection(self):
        self.assertEqual(_safe_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(_safe_cell("+2348031234567"), "+2348031234567")
        self.assertEqual(_safe_cell("-cmd|x"), "'-cmd|x")


if __name__ == "__main__":
    unittest.main()
