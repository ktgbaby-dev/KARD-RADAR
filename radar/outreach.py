"""Evidence-grounded outreach templates (free, deterministic). AI drafts live in ai.py.

Each message must (1) reference something observed, (2) name one relevant problem, (3) connect it to Kard,
(4) make no unsupported claims. When there is no observation to reference, the draft is flagged
`needs_evidence` instead of falling back to generic flattery."""
from . import normalize as N

BUY_PHRASE = {
    "new_collection": "your new collection", "product_launch": "your latest launch", "promotion_ads": "the promo you're running",
    "expansion": "the new location", "influencer_collab": "the recent collaboration", "event": "your upcoming event",
    "hiring": "that you're growing the team", "rebrand": "the rebrand", "frequent_promotions": "how regularly you run promotions",
    "partnership": "the new partnership", "new_service": "the new service", "increased_activity": "how active the page has been lately",
}
ANGLE_BY_BUY = {
    "new_collection": "Collection launch hub", "product_launch": "Launch destination", "promotion_ads": "Promo landing page",
    "expansion": "New-location hub", "influencer_collab": "Collab traffic catcher", "event": "Event destination",
    "hiring": "Growth-stage brand hub", "rebrand": "Rebrand showcase", "frequent_promotions": "Always-on offers page",
    "partnership": "Partnership showcase", "new_service": "Service booking page", "increased_activity": "Momentum hub",
}
FIX_BY_PAIN = {
    "whatsapp_ordering": "structured info before the WhatsApp chat",
    "dm_for_price": "prices and ordering in one place instead of DMs",
    "no_website": "the brand's first central home",
    "no_landing_page": "a real landing page behind the bio link",
    "weak_link_in_bio": "a branded page instead of a generic bio link",
    "location_in_captions": "location and details that don't get buried",
    "scattered_product_info": "every product in one browsable place",
    "multi_social_no_hub": "one hub tying every channel together",
    "link_in_bio_dependency": "a bio link worth clicking",
    "weak_website": "a mobile-first page that converts",
    "no_contact_on_website": "a clear contact and order path",
}
PAIN_SENTENCE = {
    "whatsapp_ordering": "Right now it looks like customers go from {platform} straight into WhatsApp to get details, so every enquiry starts from scratch.",
    "dm_for_price": "It looks like prices are shared by DM, so each interested customer has to message and wait before deciding.",
    "no_website": "I couldn't find a central website for {name}, so customers piece things together from posts.",
    "no_landing_page": "There isn't a proper page for people to land on after they tap the bio link.",
    "weak_link_in_bio": "{link_note}",
    "location_in_captions": "Key details like the location sit in captions, which get buried as you keep posting.",
    "scattered_product_info": "Product details are spread across individual posts, which makes browsing hard.",
    "multi_social_no_hub": "You're on several platforms, but there isn't one place tying them together.",
    "link_in_bio_dependency": "A lot of posts point to the link in bio, so that link is doing heavy lifting.",
    "weak_website": "The current website is hard to use on a phone.",
    "no_contact_on_website": "The website doesn't show a clear way to contact or order.",
}
ITEMS_BY_INDUSTRY = {
    "Fashion": "the collection, prices, WhatsApp ordering, location and socials",
    "Beauty": "services, prices, booking and location", "Hair & wigs": "units, prices, booking/ordering and location",
    "Jewelry": "the pieces, prices, ordering and socials", "Restaurants": "the menu, ordering or reservations, location and hours",
    "Cafés": "the menu, ordering, location and hours", "Hotels": "rooms, rates, booking and directions",
    "Hospitality": "the experience, bookings, location and events", "Real estate": "listings, inspection booking and contact",
    "Interior design": "the portfolio, services and consultation booking", "Photography": "the portfolio, packages and booking",
    "Videography": "the showreel, packages and booking", "Events": "past events, packages and enquiries",
    "Fitness": "classes, plans, booking and location", "Automotive": "inventory, prices, contact and location",
}
DEFAULT_ITEMS = "what you offer, contact options, WhatsApp, location and socials"


def _when(date_str):
    days = N.days_since(date_str)
    if days is None:
        return ""
    if days <= 2:
        return " this week"
    if days <= 9:
        return " last week"
    if days <= 31:
        return " recently"
    return ""


def compose(lead: dict, result: dict) -> dict:
    """Build pitch angle, 'how Kard helps', and four channel drafts from the scoring result."""
    name = lead.get("business_name") or "your brand"
    industry = lead.get("industry") or ""
    items = ITEMS_BY_INDUSTRY.get(industry, DEFAULT_ITEMS)
    pains = result.get("pain_points") or []
    top_pain = pains[0] if pains else None
    buy = result.get("latest_buying_signal")
    platform = "Instagram" if lead.get("instagram_handle") else ("TikTok" if lead.get("tiktok_handle") else "social media")
    lib_type = lead.get("link_in_bio_type")
    host = N.host_of(lead.get("link_in_bio_url") or "")
    link_note = {"generic_link_page": f"The bio link goes to a generic link list ({host}) rather than a branded page.",
                 "whatsapp": "The bio link opens WhatsApp directly, so there's nothing to browse first.",
                 "none": "There's no link in the bio yet, so there's nowhere to send people.",
                 "social": "The bio link points to another social profile rather than a home for the brand."}.get(
        lib_type, "The bio link could be doing more work for the brand.")

    grounding = []
    opener = ""
    if buy:
        opener = f"I saw {BUY_PHRASE.get(buy['code'], 'your latest update')}{_when(buy.get('date'))}"
        grounding.append({"type": "buying_signal", "code": buy["code"], "detail": buy.get("detail", "")})
    pain_line = ""
    if top_pain:
        pain_line = PAIN_SENTENCE.get(top_pain["code"], top_pain["problem"]).format(platform=platform, name=name, link_note=link_note)
        grounding.append({"type": "pain", "code": top_pain["code"], "detail": top_pain.get("detail", "")})

    # Pitch angle + how Kard helps
    if buy and top_pain:
        angle = f"{ANGLE_BY_BUY.get(buy['code'], 'Campaign hub')}: {FIX_BY_PAIN.get(top_pain['code'], 'one branded destination')}"
    elif top_pain:
        angle = FIX_BY_PAIN.get(top_pain["code"], "One branded destination").capitalize()
    elif buy:
        angle = f"{ANGLE_BY_BUY.get(buy['code'], 'Campaign hub')}: give the momentum one branded destination"
    else:
        angle = "Not enough evidence yet — research the lead before pitching"
    helps = (f"Kard could give {name} a single branded destination linking {items}"
             + (f", giving customers {FIX_BY_PAIN.get(top_pain['code'], 'everything in one place')}" if top_pain else "")
             + ". The physical card sends people from a handshake, packaging or event straight to it.")

    needs_evidence = not (buy or top_pain)
    kard_line = f"Kard gives you one branded page ({items}) plus a physical card that sends people straight to it."
    if opener and pain_line:
        core = f"{opener}. {pain_line}"
    elif opener:
        core = f"{opener} — nice momentum."
    elif pain_line:
        core = pain_line
    else:
        core = f"I came across {name}{' in ' + lead['city'] if lead.get('city') else ''}."

    ig = f"Hi {name} team! {core} {kard_line} Would a quick mock-up be useful?"
    tt = f"Hi {name}! {core} {kard_line} Happy to send a free mock-up if you'd like to see it."
    wa = f"Hello {name}, this is Kal's Digital. {core} Kard puts {items} on one branded page, with a physical card that links to it. Can I send a quick mock-up?"
    subject = (f"A home for {name}'s {BUY_PHRASE[buy['code']].replace('your ', '').replace('the ', '')}"
               if buy and buy["code"] in ("new_collection", "product_launch", "event", "expansion", "new_service")
               else f"One branded destination for {name}")
    email = (f"Hi {name} team,\n\n{core}\n\n"
             f"Kard by Kal's Digital is a custom landing page for your brand ({items}), paired with a physical "
             f"business card that sends people straight to it — so every conversation, package or event leads to one place.\n\n"
             f"If it's useful, I can put together a quick mock-up for {name} this week. Would that be helpful?\n\n"
             f"Best,\nKal's Digital")
    messages = [
        {"channel": "instagram", "subject": "", "body": ig},
        {"channel": "tiktok", "subject": "", "body": tt},
        {"channel": "whatsapp", "subject": "", "body": wa},
        {"channel": "email", "subject": subject, "body": email},
    ]
    return {"pitch_angle": angle, "how_kard_helps": helps, "messages": messages, "grounding": grounding,
            "needs_evidence": needs_evidence}
