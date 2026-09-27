"""AI business analysis with Claude (official Anthropic SDK).

The model reads numbered evidence and returns JSON (schema-constrained). It can PROPOSE signals and pain points,
but each must cite evidence ids that exist; anything else is dropped server-side. The model never sets scores —
scoring.py computes them from the resolved signals.
"""
import hashlib
import json

from . import normalize as N
from .config import Config
from .signals import AI_CODES, CATALOG

PRICES_PER_MTOK = {  # (input, output) USD — used for the cost log only
    "claude-opus-5": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0), "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0), "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0), "claude-opus-4-8": (5.0, 25.0),
}
FALLBACK_MODELS = ("claude-opus-5", "claude-opus-5-5", "claude-fable-5-1", "claude-fable-5")
EFFORT_MODELS_EXCLUDED = ("claude-haiku",)
VALID_EFFORT = {"low", "medium", "high", "xhigh", "max"}


class AIError(Exception):
    pass


SYSTEM_PROMPT = """You are the research analyst inside Kard Radar, an internal prospecting tool for Kal's Digital (Nigeria).

Kard is a digital-presence product wrapped in a physical touchpoint: each package includes a physical business card, but the real product is a custom landing page that gives a business one professional destination — brand, products/services, prices, contact, WhatsApp, booking/ordering, location and social links.

Your job for each lead: explain, from the evidence only, why this business is (or is not) likely to benefit from Kard right now. A business with modest followers and obvious customer-journey friction can be a better prospect than a famous brand with an excellent website. Never treat follower count as the main reason.

Rules:
- Use only the evidence items provided. Every signal and pain point must cite evidence ids exactly as written (e.g. "obs:12" or "field:website_status"). If nothing supports a claim, leave it out.
- Only propose signals from the allowed codes, and only when the evidence clearly supports them. Do not repeat signals already marked "yes" by rules unless you have additional evidence.
- Dates: give the date of the supporting evidence as YYYY-MM-DD when it is known, otherwise an empty string.
- If information is missing, say it is unknown. Do not assume.
- founder_name: fill only if a person is explicitly named as founder/owner/CEO in the evidence; otherwise "".
- summary: 2-4 sentences answering "why this business, why now", grounded in specific observations.
- pain_points: concrete customer-journey problems (e.g. customers pushed from Instagram into WhatsApp with no structured information; prices only in DMs; location buried in captions; no central destination).
- how_kard_helps: one or two sentences connecting those problems to a Kard page + physical card.
- pitch_angle: a short headline for the approach (max 12 words).

Outreach drafts (instagram, tiktok, whatsapp, email):
- Reference one specific thing actually observed, name one relevant problem, connect it to Kard, and end with a low-pressure question (e.g. offering a quick mock-up).
- Natural, concise, respectful Nigerian-English business tone. DMs and WhatsApp under 70 words; email body under 130 words with a short subject line.
- No generic flattery ("we love your brand"), no hype, no invented numbers or results, no mention of scores, research tools or AI.
- Sign emails as "Kal's Digital".
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "signals": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "enum": AI_CODES},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["code", "evidence_ids", "note", "date"],
            "additionalProperties": False,
        }},
        "pain_points": {"type": "array", "items": {
            "type": "object",
            "properties": {"problem": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["problem", "evidence_ids"],
            "additionalProperties": False,
        }},
        "how_kard_helps": {"type": "string"},
        "pitch_angle": {"type": "string"},
        "founder_name": {"type": "string"},
        "outreach": {
            "type": "object",
            "properties": {"instagram": {"type": "string"}, "tiktok": {"type": "string"}, "whatsapp": {"type": "string"},
                           "email_subject": {"type": "string"}, "email_body": {"type": "string"}},
            "required": ["instagram", "tiktok", "whatsapp", "email_subject", "email_body"],
            "additionalProperties": False,
        },
    },
    "required": ["summary", "signals", "pain_points", "how_kard_helps", "pitch_angle", "founder_name", "outreach"],
    "additionalProperties": False,
}

LEAD_FIELDS = ["business_name", "industry", "subcategory", "city", "state", "country", "instagram_handle", "tiktok_handle",
               "website_url", "website_status", "website_evidence", "website_quality", "link_in_bio_url", "link_in_bio_type",
               "whatsapp", "phone", "email", "founder_name", "followers_instagram", "followers_tiktok", "followers_source",
               "profile_bio", "address"]


def build_input(lead: dict, observations: list[dict], resolved: dict[str, dict]) -> tuple[str, set[str]]:
    """Return (user prompt text, set of valid evidence ids)."""
    valid = set()
    lines = [f"Today: {N.today().isoformat()}", "", "LEAD RECORD (field ids in brackets):"]
    for f in LEAD_FIELDS:
        v = lead.get(f)
        if v in (None, ""):
            continue
        valid.add(f"field:{f}")
        lines.append(f"[field:{f}] {f} = {str(v)[:400]}")
    notes = lead.get("website_quality_notes") or []
    if isinstance(notes, str):
        notes = json.loads(notes or "[]")
    if notes:
        lines.append("[field:website_quality] website checks: " + "; ".join(("✓ " if n["ok"] else "✗ ") + n["text"] for n in notes))
        valid.add("field:website_quality")
    lines += ["", "EVIDENCE (most recent first; website text is an excerpt):"]
    for o in observations[:80]:
        oid = f"obs:{o['id']}"
        valid.add(oid)
        meta = o.get("meta") or {}
        tags = [o["kind"], o["source"]]
        if meta.get("platform"):
            tags.append(meta["platform"])
        if o.get("observed_at"):
            tags.append(str(o["observed_at"])[:10])
        content = (o.get("content") or "").replace("\n", " ")[:1500]
        lines.append(f"[{oid}] ({', '.join(tags)}) {content}")
    lines += ["", "SIGNALS ALREADY ESTABLISHED BY RULES:"]
    for code, s in sorted(resolved.items()):
        if code in CATALOG and s["state"] in ("yes", "no"):
            lines.append(f"- {code}: {s['state']} — {s.get('detail', '')[:160]}")
    lines += ["", "ALLOWED SIGNAL CODES YOU MAY PROPOSE:"]
    for code in AI_CODES:
        lines.append(f"- {code}: {CATALOG[code]['label']}")
    return "\n".join(lines), valid


def input_hash(prompt: str, model: str) -> str:
    return hashlib.sha256((model + "\n" + SYSTEM_PROMPT + "\n" + prompt).encode("utf-8")).hexdigest()


def estimate_cost(model: str, usage: dict) -> float:
    pin, pout = PRICES_PER_MTOK.get(model, (5.0, 25.0))
    return round((usage.get("input_tokens", 0) * pin + usage.get("cache_read_tokens", 0) * pin * 0.1
                  + usage.get("output_tokens", 0) * pout) / 1_000_000, 5)


def call_claude(prompt: str, cfg: Config) -> tuple[dict, dict]:
    """Call the Messages API. Returns (parsed JSON, usage dict). Raises AIError with a user-facing message."""
    if not cfg.anthropic_key_set:
        raise AIError("ANTHROPIC_API_KEY is not set — AI analysis is disabled. Rule-based scoring and template outreach still work.")
    import anthropic

    client = anthropic.Anthropic(max_retries=2, timeout=180.0)
    model = cfg.anthropic_model
    kwargs = {
        "model": model,
        "max_tokens": 16000,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": prompt}],
    }
    output_config = {"format": {"type": "json_schema", "schema": SCHEMA}}
    effort = cfg.ai_effort if cfg.ai_effort in VALID_EFFORT else "medium"
    if not model.startswith(EFFORT_MODELS_EXCLUDED):
        output_config["effort"] = effort
    kwargs["output_config"] = output_config
    if model.startswith(FALLBACK_MODELS):
        # Server-side fallback: if a safety classifier declines, Anthropic re-runs on its recommended model.
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    try:
        if "betas" in kwargs:
            resp = client.beta.messages.create(**kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise AIError("The Anthropic API key was rejected (401). Check ANTHROPIC_API_KEY.")
    except anthropic.PermissionDeniedError:
        raise AIError("The API key lacks permission for this model (403).")
    except anthropic.NotFoundError:
        raise AIError(f"Model '{model}' was not found (404). Check ANTHROPIC_MODEL.")
    except anthropic.RateLimitError:
        raise AIError("Anthropic rate limit reached (429). Try again in a minute.")
    except anthropic.BadRequestError as e:
        raise AIError(f"Anthropic rejected the request (400): {getattr(e, 'message', e)}"[:300])
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic API error ({e.status_code}). Try again later.")
    except anthropic.APIConnectionError:
        raise AIError("Could not reach the Anthropic API (network error).")

    usage_obj = getattr(resp, "usage", None)
    usage = {"input_tokens": getattr(usage_obj, "input_tokens", 0) or 0,
             "output_tokens": getattr(usage_obj, "output_tokens", 0) or 0,
             "cache_read_tokens": getattr(usage_obj, "cache_read_input_tokens", 0) or 0,
             "model": getattr(resp, "model", model) or model}
    if resp.stop_reason == "refusal":
        raise AIError("The model declined to analyse this lead.")
    if resp.stop_reason == "max_tokens":
        raise AIError("The AI response was cut off (max_tokens). Try again.")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise AIError("The AI response was not valid JSON.")
    return data, usage


def validate(data: dict, valid_ids: set[str], evidence_text: str) -> tuple[dict, list[dict]]:
    """Drop anything that does not cite real evidence. Returns (clean result, dropped items)."""
    dropped = []
    clean = {"summary": N.clean_text(data.get("summary"), 1500), "signals": [], "pain_points": [],
             "how_kard_helps": N.clean_text(data.get("how_kard_helps"), 800),
             "pitch_angle": N.clean_text(data.get("pitch_angle"), 160), "founder_name": "", "outreach": {}}
    for s in data.get("signals") or []:
        code = s.get("code")
        ids = [i for i in (s.get("evidence_ids") or []) if i in valid_ids]
        if code not in AI_CODES:
            dropped.append({"type": "signal", "code": code, "reason": "code not allowed"})
            continue
        if not ids:
            dropped.append({"type": "signal", "code": code, "reason": "no valid evidence cited",
                            "cited": s.get("evidence_ids")})
            continue
        d = N.to_date(s.get("date")) if s.get("date") else None
        clean["signals"].append({"code": code, "evidence": ids, "detail": N.clean_text(s.get("note"), 300),
                                 "signal_date": d.isoformat() if d else None})
    for p in data.get("pain_points") or []:
        ids = [i for i in (p.get("evidence_ids") or []) if i in valid_ids]
        if not ids:
            dropped.append({"type": "pain_point", "problem": p.get("problem"), "reason": "no valid evidence cited"})
            continue
        clean["pain_points"].append({"problem": N.clean_text(p.get("problem"), 300), "evidence": ids})
    fn = N.clean_text(data.get("founder_name"), 80)
    if fn:
        if fn.lower() in evidence_text.lower():
            clean["founder_name"] = fn
        else:
            dropped.append({"type": "founder_name", "value": fn, "reason": "name not present in evidence"})
    o = data.get("outreach") or {}
    clean["outreach"] = {
        "instagram": N.clean_text(o.get("instagram"), 900), "tiktok": N.clean_text(o.get("tiktok"), 900),
        "whatsapp": N.clean_text(o.get("whatsapp"), 900), "email_subject": N.clean_text(o.get("email_subject"), 150),
        "email_body": N.clean_text(o.get("email_body"), 2500),
    }
    return clean, dropped
