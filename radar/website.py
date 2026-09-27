"""Static HTML analysis of a business website or link-in-bio page. Deterministic; no JavaScript execution."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from . import normalize as N

PARKED_MARKERS = [
    "domain is for sale", "buy this domain", "this domain is parked", "domain parking", "parked free",
    "coming soon", "under construction", "site is under maintenance", "website is under maintenance",
    "account suspended", "this account has been suspended", "index of /", "welcome to nginx",
    "it works!", "default web site page", "future home of", "launching soon", "website coming soon",
]
CTA_RE = re.compile(r"\b(order( now)?|shop( now)?|buy( now)?|book( now| a| an)?|reserve|contact( us)?|get a quote|enquire|"
                    r"make an enquiry|menu|call us|whatsapp us|chat with us|add to cart|checkout|subscribe)\b", re.I)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = {}
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._skip = 0
        self._in_title = False
        self._in_a: str | None = None
        self._a_text: list[str] = []
        self.forms = 0
        self.images = 0
        self.scripts = 0
        self.headings: list[str] = []
        self._in_h = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._skip += 1
            if tag == "script":
                self.scripts += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("itemprop") or "").lower()
            if key and a.get("content") is not None:
                self.meta[key] = a.get("content") or ""
        elif tag == "a":
            self._in_a = a.get("href") or ""
            self._a_text = []
        elif tag == "form":
            self.forms += 1
        elif tag == "img":
            self.images += 1
        elif tag in ("h1", "h2"):
            self._in_h = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._in_a is not None:
            self.links.append((self._in_a, " ".join(self._a_text).strip()))
            self._in_a = None
        elif tag in ("h1", "h2"):
            self._in_h = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        s = data.strip()
        if not s:
            return
        self.text_parts.append(s)
        if self._in_a is not None:
            self._a_text.append(s)
        if self._in_h and len(self.headings) < 12:
            self.headings.append(s[:120])


def analyze(html: str, url: str, status: int | None, elapsed_ms: int | None = None, error: str = "",
            final_url: str = "", ref_year: int | None = None) -> dict:
    """Return {status_label, quality, notes[], title, description, text_excerpt, extracted{...}, has_contact}."""
    ref_year = ref_year or N.today().year
    final_url = final_url or url
    result = {"url": url, "final_url": final_url, "http_status": status, "elapsed_ms": elapsed_ms,
              "status_label": "ok", "quality": None, "notes": [], "title": "", "description": "",
              "text_excerpt": "", "word_count": 0, "extracted": {"emails": [], "phones": [], "whatsapp": [],
                                                                 "socials": {}, "links": [], "ctas": []},
              "has_contact": False, "error": error}
    if not status or status >= 400 or not html:
        result["status_label"] = "unreachable"
        result["notes"].append({"ok": False, "text": error or f"Page did not load (HTTP {status})"})
        return result

    p = _Parser()
    try:
        p.feed(html)
    except Exception:  # malformed HTML: keep what was parsed
        pass
    text = re.sub(r"\s+", " ", " ".join(p.text_parts)).strip()
    lower = (text + " " + p.title).lower()
    result["title"] = N.clean_text(p.title, 200)
    result["description"] = N.clean_text(p.meta.get("description") or p.meta.get("og:description") or "", 400)
    result["text_excerpt"] = text[:1800]
    words = len(text.split())
    result["word_count"] = words

    emails, phones, whatsapp, socials, ctas, links = set(), set(), set(), {}, set(), []
    for href, label in p.links:
        href = (href or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        if href.lower().startswith("mailto:"):
            e = N.clean_email(href)
            if e:
                emails.add(e)
            continue
        if href.lower().startswith("tel:"):
            k = N.phone_key(href[4:])
            if k:
                phones.add(k)
            continue
        absu = urljoin(final_url, href)
        kind = N.classify_url(absu)
        if kind == "whatsapp":
            k = N.whatsapp_from_url(absu)
            if k:
                whatsapp.add(k)
        elif kind in ("instagram", "tiktok", "facebook", "x", "youtube", "linkedin", "threads", "pinterest", "snapchat"):
            socials.setdefault(kind, absu)
        if label and CTA_RE.search(label):
            ctas.add(label[:40])
        if len(links) < 60 and absu.startswith("http"):
            links.append({"url": absu, "text": label[:80], "kind": kind})
    for m in N.EMAIL_RE.finditer(text):
        e = N.clean_email(m[0])
        if e:
            emails.add(e)
    for m in N.NG_PHONE_RE.finditer(text):
        k = N.phone_key(m[0])
        if k:
            phones.add(k)
    for m in CTA_RE.finditer(text):
        if len(ctas) < 8:
            ctas.add(m[0][:40])
    has_contact = bool(emails or phones or whatsapp or any("contact" in (l["url"] + l["text"]).lower() for l in links))
    result["extracted"] = {"emails": sorted(emails)[:5], "phones": sorted(phones)[:5], "whatsapp": sorted(whatsapp)[:3],
                           "socials": socials, "links": links, "ctas": sorted(ctas)[:8]}
    result["has_contact"] = has_contact

    parked = [m for m in PARKED_MARKERS if m in lower]
    if parked and words < 250:
        result["status_label"] = "parked"
        result["quality"] = 10
        result["notes"].append({"ok": False, "text": f"Looks like a placeholder page (“{parked[0]}”)"})
        return result

    notes = []
    q = 0

    def check(ok: bool, pts: int, good: str, bad: str):
        nonlocal q
        if ok:
            q += pts
        notes.append({"ok": ok, "text": good if ok else bad})

    check(final_url.startswith("https://"), 15, "Served over HTTPS", "Not served over HTTPS")
    check("viewport" in p.meta, 15, "Mobile viewport configured", "No mobile viewport tag — likely not mobile-friendly")
    check(bool(result["title"]), 10, "Has a page title", "Missing page title")
    check(bool(result["description"]), 10, "Has a meta description", "No meta description")
    check(words >= 150, 15, f"Substantial content ({words} words)", f"Very little content ({words} words)")
    check(has_contact, 15, "Contact details visible", "No phone, email, WhatsApp or contact link found")
    check(bool(socials), 5, "Links to social profiles", "No links to social profiles")
    check(bool(ctas), 10, "Clear calls to action (" + ", ".join(sorted(ctas)[:3]) + ")" if ctas else "",
          "No clear call to action (order / book / contact)")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", html, re.I)
             if 1995 <= int(y) <= ref_year + 1]
    if years:
        latest = max(years)
        check(latest >= ref_year - 1, 5, f"Footer year is current ({latest})", f"Footer says © {latest} — may be outdated")
    else:
        q += 5
    if elapsed_ms and elapsed_ms > 4000:
        notes.append({"ok": False, "text": f"Slow to respond ({elapsed_ms / 1000:.1f}s)"})
    gen = p.meta.get("generator", "")
    if gen:
        notes.append({"ok": True, "text": f"Built with {gen[:40]}"})
    result["quality"] = max(0, min(100, q))
    result["notes"] = notes
    return result
