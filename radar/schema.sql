-- Kard Radar schema. Portable between SQLite and PostgreSQL.
-- {PK} is replaced per dialect. Timestamps are ISO-8601 UTC text. JSON is stored as text.

CREATE TABLE IF NOT EXISTS leads (
    id {PK},
    business_name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    industry TEXT DEFAULT '',
    subcategory TEXT DEFAULT '',
    city TEXT DEFAULT '',
    state TEXT DEFAULT '',
    country TEXT DEFAULT '',
    instagram_url TEXT DEFAULT '',
    instagram_handle TEXT DEFAULT '',
    tiktok_url TEXT DEFAULT '',
    tiktok_handle TEXT DEFAULT '',
    website_url TEXT DEFAULT '',
    website_domain TEXT DEFAULT '',
    website_status TEXT DEFAULT 'unknown',
    website_evidence TEXT DEFAULT '',
    website_quality INTEGER,
    website_quality_notes TEXT DEFAULT '[]',
    website_suggestion TEXT DEFAULT '',
    link_in_bio_url TEXT DEFAULT '',
    link_in_bio_type TEXT DEFAULT 'unknown',
    whatsapp TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    phone_key TEXT DEFAULT '',
    email TEXT DEFAULT '',
    other_socials TEXT DEFAULT '{}',
    founder_name TEXT DEFAULT '',
    followers_instagram INTEGER,
    followers_tiktok INTEGER,
    followers_source TEXT DEFAULT '',
    profile_bio TEXT DEFAULT '',
    address TEXT DEFAULT '',
    status TEXT DEFAULT 'New',
    source TEXT DEFAULT 'manual',
    discovered_at TEXT NOT NULL,
    contacted_at TEXT,
    last_contact_channel TEXT DEFAULT '',
    follow_up_at TEXT,
    notes TEXT DEFAULT '',
    opportunity_score INTEGER,
    kard_fit INTEGER,
    business_quality INTEGER,
    confidence TEXT DEFAULT 'Low',
    fit_points REAL,
    social_points REAL,
    gap_points REAL,
    buying_points REAL,
    access_points REAL,
    buying_signal_count INTEGER DEFAULT 0,
    latest_buying_signal_at TEXT,
    latest_buying_signal TEXT DEFAULT '',
    top_reason TEXT DEFAULT '',
    top_pain TEXT DEFAULT '',
    pitch_angle TEXT DEFAULT '',
    how_kard_helps TEXT DEFAULT '',
    ai_summary TEXT DEFAULT '',
    ai_pitch_angle TEXT DEFAULT '',
    ai_how_kard_helps TEXT DEFAULT '',
    ai_pain_points TEXT DEFAULT '[]',
    ai_input_hash TEXT DEFAULT '',
    ai_model TEXT DEFAULT '',
    score_breakdown TEXT DEFAULT '{}',
    last_researched_at TEXT,
    last_analyzed_at TEXT,
    last_scored_at TEXT,
    archived INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_name_key ON leads(name_key);
CREATE INDEX IF NOT EXISTS idx_leads_ig ON leads(instagram_handle);
CREATE INDEX IF NOT EXISTS idx_leads_tt ON leads(tiktok_handle);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(website_domain);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone_key);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(opportunity_score);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);

CREATE TABLE IF NOT EXISTS observations (
    id {PK},
    lead_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    content TEXT NOT NULL,
    observed_at TEXT,
    collected_at TEXT NOT NULL,
    meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_obs_lead ON observations(lead_id);

CREATE TABLE IF NOT EXISTS signals (
    id {PK},
    lead_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    state TEXT NOT NULL,
    detector TEXT NOT NULL,
    detail TEXT DEFAULT '',
    evidence TEXT DEFAULT '[]',
    signal_date TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_lead ON signals(lead_id);

CREATE TABLE IF NOT EXISTS score_snapshots (
    id {PK},
    lead_id INTEGER NOT NULL,
    opportunity_score INTEGER,
    kard_fit INTEGER,
    business_quality INTEGER,
    confidence TEXT,
    breakdown TEXT NOT NULL,
    weights TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_lead ON score_snapshots(lead_id);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id {PK},
    lead_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT DEFAULT '',
    body TEXT NOT NULL,
    generator TEXT NOT NULL,
    grounding TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach_messages(lead_id);

CREATE TABLE IF NOT EXISTS activities (
    id {PK},
    lead_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    channel TEXT DEFAULT '',
    from_status TEXT DEFAULT '',
    to_status TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_act_lead ON activities(lead_id);

CREATE TABLE IF NOT EXISTS outcomes (
    lead_id INTEGER PRIMARY KEY,
    contacted INTEGER DEFAULT 0,
    responded INTEGER DEFAULT 0,
    interested INTEGER DEFAULT 0,
    meeting INTEGER DEFAULT 0,
    proposal INTEGER DEFAULT 0,
    purchased INTEGER DEFAULT 0,
    lost INTEGER DEFAULT 0,
    revenue REAL,
    currency TEXT DEFAULT 'NGN',
    package TEXT DEFAULT '',
    first_contacted_at TEXT,
    responded_at TEXT,
    won_at TEXT,
    score_at_contact INTEGER,
    fit_at_contact INTEGER,
    quality_at_contact INTEGER,
    features_at_contact TEXT DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id {PK},
    params TEXT NOT NULL,
    providers TEXT DEFAULT '[]',
    status TEXT NOT NULL,
    message TEXT DEFAULT '',
    result_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id {PK},
    run_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    query TEXT DEFAULT '',
    title TEXT DEFAULT '',
    url TEXT DEFAULT '',
    snippet TEXT DEFAULT '',
    result_date TEXT,
    platform TEXT DEFAULT '',
    handle TEXT DEFAULT '',
    name_guess TEXT DEFAULT '',
    extra TEXT DEFAULT '{}',
    snippet_signals TEXT DEFAULT '[]',
    matched_lead_id INTEGER,
    match_reason TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cand_run ON discovery_candidates(run_id);

CREATE TABLE IF NOT EXISTS fetch_cache (
    url TEXT PRIMARY KEY,
    final_url TEXT DEFAULT '',
    status INTEGER,
    content_type TEXT DEFAULT '',
    body TEXT DEFAULT '',
    error TEXT DEFAULT '',
    elapsed_ms INTEGER,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_runs (
    id {PK},
    lead_id INTEGER,
    purpose TEXT NOT NULL,
    model TEXT DEFAULT '',
    status TEXT NOT NULL,
    input_hash TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    est_cost_usd REAL DEFAULT 0,
    error TEXT DEFAULT '',
    dropped TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
