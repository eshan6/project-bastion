-- ============================================================
-- Bastion Block A — Source Catalogue (Part 2)
-- Additional sources to reach ~95 total + operational views
-- ============================================================

INSERT INTO bastion_provenance.sources
(source_id, name, category, realism_tier, scrape_class, refresh_cadence, legal_posture,
 base_url, url_pattern, seed_urls, notes, rate_limit_seconds, priority)
VALUES

-- ============================================================
-- Additional ORBAT / strategic sources
-- ============================================================

('thewire_security',
 'The Wire — security section',
 'orbat', 'tier_3_journalistic', 'static_html', 'weekly', 'fair_use_research',
 'https://thewire.in',
 '/category/security',
 ARRAY['https://thewire.in/category/security'],
 'Ajai Shukla bylines. Strong on procurement criticism + LAC.',
 8.0, 3),

('scroll_defence',
 'Scroll.in — defence reporting',
 'orbat', 'tier_3_journalistic', 'static_html', 'weekly', 'fair_use_research',
 'https://scroll.in',
 '/topic/defence',
 ARRAY['https://scroll.in/topic/defence'],
 'Investigative angle. Lower volume, useful for triangulation.',
 8.0, 5),

('ajai_shukla_blog',
 'Broadsword (Ajai Shukla)',
 'orbat', 'tier_3_journalistic', 'static_html', 'weekly', 'fair_use_research',
 'https://ajaishukla.com',
 '/',
 ARRAY['https://ajaishukla.com/'],
 'Veteran defence correspondent. Procurement + capability deep dives.',
 6.0, 3),

('stratnews_global',
 'StratNews Global',
 'orbat', 'tier_3_journalistic', 'static_html', 'weekly', 'fair_use_research',
 'https://stratnewsglobal.com',
 '/category/defence',
 ARRAY['https://stratnewsglobal.com/'],
 'Nitin Gokhale. Pro-establishment but well-sourced for inductions/exercises.',
 6.0, 4),

('janes_open_articles',
 'Janes — public/free articles only',
 'orbat', 'tier_2_credible', 'static_html', 'monthly', 'fair_use_research',
 'https://www.janes.com',
 '/defence-news',
 ARRAY['https://www.janes.com/defence-news/news-detail'],
 'Subscription is not available. Public-facing news teasers carry occasional hard numbers — scrape what is openly visible only.',
 8.0, 5),

('observerresearch_security',
 'ORF — Defence & Security Studies',
 'orbat', 'tier_2_credible', 'static_html', 'weekly', 'fair_use_research',
 'https://www.orfonline.org',
 '/research/defence-security',
 ARRAY['https://www.orfonline.org/research/defence-security/'],
 'Higher-tempo than ORF Strategic. Often referenced in policy papers.',
 5.0, 5),

('takshashila_strategic',
 'Takshashila Institution — strategic studies',
 'orbat', 'tier_2_credible', 'static_html', 'monthly', 'fair_use_research',
 'https://takshashila.org.in',
 '/category/strategic-studies',
 ARRAY['https://takshashila.org.in/'],
 'Bangalore-based. Public-policy framing — useful for procurement context.',
 5.0, 6),

('uscc_china_reports',
 'US-China Economic & Security Review Commission',
 'orbat', 'tier_2_credible', 'pdf_document', 'quarterly', 'public_domain',
 'https://www.uscc.gov',
 '/annual-reports',
 ARRAY['https://www.uscc.gov/annual-report'],
 'PLA chapters discuss India-facing posture. Cross-side validation.',
 4.0, 4),

('rusi_india',
 'RUSI — India research',
 'orbat', 'tier_2_credible', 'static_html', 'monthly', 'fair_use_research',
 'https://www.rusi.org',
 '/explore-our-research/topics/india',
 ARRAY['https://www.rusi.org/'],
 'British think tank. Solid on India-China balance.',
 5.0, 6),

-- ============================================================
-- Additional vehicles / equipment
-- ============================================================

('hal_products',
 'Hindustan Aeronautics — products',
 'vehicles_equipment', 'tier_1_authoritative', 'static_html', 'quarterly', 'gov_open_data',
 'https://hal-india.co.in',
 '/products',
 ARRAY['https://hal-india.co.in/'],
 'Helicopter inventories — Cheetah, Cheetal, ALH, LCH. Critical for forward heli-resupply modelling.',
 5.0, 2),

('hal_annual_reports',
 'HAL — annual reports',
 'vehicles_equipment', 'tier_1_authoritative', 'pdf_document', 'once', 'gov_open_data',
 'https://hal-india.co.in',
 '/investor-relations/annual-reports',
 ARRAY['https://hal-india.co.in/'],
 'Listed PSU. Order book disclosure backs out delivery rates by airframe.',
 5.0, 4),

('jcb_india_defence',
 'JCB India — defence/equipment',
 'vehicles_equipment', 'tier_2_credible', 'static_html', 'quarterly', 'fair_use_research',
 'https://www.jcb.com',
 '/en-in/products',
 ARRAY['https://www.jcb.com/en-in'],
 'Earthmovers used for road-clearing in winter. Tangential.',
 5.0, 8),

('larsentoubro_defence',
 'L&T Defence — products',
 'vehicles_equipment', 'tier_2_credible', 'static_html', 'quarterly', 'fair_use_research',
 'https://www.larsentoubro.com',
 '/corporate/products-and-services/defence',
 ARRAY['https://www.larsentoubro.com/'],
 'K9 Vajra etc. — peripheral to sustainment but vehicle adjacent.',
 5.0, 6),

('iaf_transport_fleet',
 'IAF transport fleet — public data',
 'vehicles_equipment', 'tier_2_credible', 'static_html', 'quarterly', 'fair_use_research',
 'https://en.wikipedia.org',
 '/wiki/List_of_active_Indian_military_aircraft',
 ARRAY['https://en.wikipedia.org/wiki/Indian_Air_Force'],
 'C-17, C-130J, IL-76, AN-32. Strategic + tactical airlift. Wiki + IAF press for tail counts.',
 4.0, 3),

-- ============================================================
-- Additional weather / closures / local press
-- ============================================================

('snowforecast_passes',
 'Snow Forecast — Himalayan passes',
 'weather_closures', 'tier_4_osint', 'static_html', 'daily', 'fair_use_research',
 'https://www.snow-forecast.com',
 '/resorts/{pass_name}',
 ARRAY['https://www.snow-forecast.com/'],
 'Crowdsourced + ECMWF-derived. Coarse but daily, free, no auth.',
 4.0, 7),

('mountain_forecast',
 'Mountain Forecast — peaks/passes',
 'weather_closures', 'tier_4_osint', 'static_html', 'daily', 'fair_use_research',
 'https://www.mountain-forecast.com',
 '/peaks/{peak_name}',
 ARRAY['https://www.mountain-forecast.com/'],
 'Same source as snow-forecast.com. Use one or the other, not both.',
 4.0, 8),

('openweather_history',
 'OpenWeatherMap — Leh/Kargil history',
 'weather_closures', 'tier_4_osint', 'api_json', 'daily', 'fair_use_research',
 'https://api.openweathermap.org',
 '/data/2.5/onecall/timemachine?lat={lat}&lon={lon}',
 ARRAY['https://openweathermap.org/api'],
 'Free tier: 1000 calls/day, 60/min. Backfill point weather where IMD AWS has gaps.',
 1.5, 4),

('era5_reanalysis',
 'ERA5 reanalysis (Copernicus C3S)',
 'weather_closures', 'tier_1_authoritative', 'api_json', 'monthly', 'gov_open_data',
 'https://cds.climate.copernicus.eu',
 '/api/v2/resources/reanalysis-era5-single-levels',
 ARRAY['https://cds.climate.copernicus.eu/'],
 'Gridded historical weather, free with registration. 0.25-degree resolution. Backbone of the closure model training set if IMD AWS is patchy.',
 3.0, 2),

('ndma_disaster_archive',
 'NDMA — disaster reports',
 'weather_closures', 'tier_1_authoritative', 'pdf_document', 'monthly', 'gov_open_data',
 'https://ndma.gov.in',
 '/Reports',
 ARRAY['https://ndma.gov.in/Reports/Disaster-Statistics'],
 'Avalanches, GLOFs, landslides. Geo-tagged events that align with road closures.',
 4.0, 3),

('igrms_himalaya_avalanche',
 'SASE / DGRE avalanche bulletins',
 'weather_closures', 'tier_1_authoritative', 'pdf_document', 'daily', 'gov_open_data',
 'https://dgre.drdo.gov.in',
 '/avalanche-bulletins',
 ARRAY['https://dgre.drdo.gov.in/'],
 'DRDO Defence Geoinformatics & Research Establishment (formerly SASE). Ladakh-specific avalanche risk forecasts. Auth-free pages only.',
 5.0, 2),

('rising_kashmir',
 'Rising Kashmir',
 'weather_closures', 'tier_3_journalistic', 'static_html', 'weekly', 'fair_use_research',
 'https://risingkashmir.com',
 '/?s={query}',
 ARRAY['https://risingkashmir.com/'],
 'Third Kashmir-local source for closure cross-validation.',
 8.0, 5),

('news18_jk',
 'News18 J&K bureau',
 'weather_closures', 'tier_3_journalistic', 'static_html', 'weekly', 'fair_use_research',
 'https://www.news18.com',
 '/news/jammu-kashmir',
 ARRAY['https://www.news18.com/news/jammu-kashmir/'],
 'Volume play. Lower SNR.',
 8.0, 6),

-- ============================================================
-- Additional scales / doctrine
-- ============================================================

('csir_high_altitude',
 'CSIR / DIPAS — high-altitude physiology',
 'scales_doctrine', 'tier_1_authoritative', 'static_html', 'quarterly', 'gov_open_data',
 'https://dipas.drdo.gov.in',
 '/publications',
 ARRAY['https://dipas.drdo.gov.in/'],
 'DRDO Defence Institute of Physiology & Allied Sciences. Caloric/water intake studies for HA troops — feeds ration scale modelling.',
 5.0, 2),

('drdo_publications',
 'DRDO — publications portal',
 'scales_doctrine', 'tier_1_authoritative', 'pdf_document', 'monthly', 'gov_open_data',
 'https://www.drdo.gov.in',
 '/publications',
 ARRAY['https://www.drdo.gov.in/publications'],
 'Defence Science Journal etc. Long-tail useful for specs/consumption modelling.',
 5.0, 4),

('mod_dgqa_specs',
 'DGQA — specifications (publicly indexed)',
 'scales_doctrine', 'tier_1_authoritative', 'pdf_document', 'quarterly', 'gov_open_data',
 'https://www.ddpdoo.gov.in',
 '/dgqa-specifications',
 ARRAY['https://www.ddpdoo.gov.in/'],
 'Some JSS specs are publicly indexed. Useful when packaging/storage matters for a SKU.',
 5.0, 5),

('cag_state_jk_ladakh',
 'CAG — J&K and Ladakh state audit reports',
 'scales_doctrine', 'tier_1_authoritative', 'pdf_document', 'quarterly', 'gov_open_data',
 'https://cag.gov.in',
 '/en/audit-report?state=Ladakh',
 ARRAY['https://cag.gov.in/'],
 'State audits sometimes touch civil-military convergence (eg. BRO-funded civil works).',
 4.0, 4),

('dpr_mod',
 'Directorate of Public Relations — MoD',
 'scales_doctrine', 'tier_1_authoritative', 'static_html', 'weekly', 'gov_open_data',
 'https://www.mod.gov.in',
 '/dod/dpr',
 ARRAY['https://www.mod.gov.in/dod/dpr'],
 'Speeches + ministerial events. Tempo + occasional numbers.',
 5.0, 5),

-- ============================================================
-- Additional tempo signals
-- ============================================================

('mygov_defence',
 'MyGov.in — defence consultations',
 'tempo_signals', 'tier_1_authoritative', 'static_html', 'monthly', 'gov_open_data',
 'https://www.mygov.in',
 '/group/ministry-defence',
 ARRAY['https://www.mygov.in/group/ministry-defence/'],
 'Niche but occasional public consultations on defence policy.',
 5.0, 7),

('eciexports_defence',
 'SIPRI Arms Transfers — India',
 'tempo_signals', 'tier_2_credible', 'api_json', 'quarterly', 'cc_licensed',
 'https://armstransfers.sipri.org',
 '/ArmsTransfer/TransferData',
 ARRAY['https://www.sipri.org/databases/armstransfers'],
 'Free API. India arms imports — tempo proxy for force modernization.',
 3.0, 5),

('flightradar24_archive',
 'FlightRadar24 — historical playback (free tier)',
 'tempo_signals', 'tier_4_osint', 'manual_download', 'on_event', 'fair_use_research',
 'https://www.flightradar24.com',
 '/data/airports/{airport}/arrivals',
 ARRAY['https://www.flightradar24.com/data/airports/IXL/arrivals'],
 'Leh (IXL), Thoise, Kargil. Free tier shows 7d playback. Manual capture only — no scraping that scales.',
 0.0, 6),

('marinetraffic_imo',
 'MarineTraffic — Indian naval/auxiliary movements',
 'tempo_signals', 'tier_4_osint', 'static_html', 'weekly', 'fair_use_research',
 'https://www.marinetraffic.com',
 '/en/ais/home',
 ARRAY['https://www.marinetraffic.com/'],
 'Out of scope for Eastern Ladakh demo but kept for ontology generality.',
 5.0, 9);

-- ============================================================
-- OPERATIONAL VIEWS
-- ============================================================

-- Quick read: priority-1 sources for the demo, by category
CREATE OR REPLACE VIEW bastion_provenance.v_demo_priority_sources AS
SELECT
    category,
    realism_tier,
    source_id,
    name,
    scrape_class,
    refresh_cadence,
    rate_limit_seconds,
    enabled
FROM bastion_provenance.sources
WHERE priority <= 2
ORDER BY category, priority, source_id;

-- Source counts by category — sanity check the catalogue is balanced
CREATE OR REPLACE VIEW bastion_provenance.v_source_counts AS
SELECT
    category,
    COUNT(*) AS total_sources,
    COUNT(*) FILTER (WHERE priority <= 2) AS demo_critical,
    COUNT(*) FILTER (WHERE priority BETWEEN 3 AND 5) AS realism_floor,
    COUNT(*) FILTER (WHERE priority >= 6) AS nice_to_have,
    COUNT(*) FILTER (WHERE realism_tier = 'tier_1_authoritative') AS tier_1,
    COUNT(*) FILTER (WHERE realism_tier = 'tier_2_credible') AS tier_2,
    COUNT(*) FILTER (WHERE realism_tier = 'tier_3_journalistic') AS tier_3,
    COUNT(*) FILTER (WHERE realism_tier IN ('tier_4_osint','tier_5_inferred')) AS tier_4_5
FROM bastion_provenance.sources
GROUP BY category
ORDER BY category;

-- Stale source detection — for the cron health dashboard
CREATE OR REPLACE VIEW bastion_provenance.v_stale_sources AS
SELECT
    source_id,
    name,
    category,
    priority,
    refresh_cadence,
    last_success_at,
    consecutive_failures,
    CASE
        WHEN last_success_at IS NULL THEN 'never_succeeded'
        WHEN refresh_cadence = 'daily'   AND last_success_at < NOW() - INTERVAL '2 days'  THEN 'stale'
        WHEN refresh_cadence = 'weekly'  AND last_success_at < NOW() - INTERVAL '10 days' THEN 'stale'
        WHEN refresh_cadence = 'monthly' AND last_success_at < NOW() - INTERVAL '40 days' THEN 'stale'
        WHEN refresh_cadence = 'quarterly' AND last_success_at < NOW() - INTERVAL '100 days' THEN 'stale'
        ELSE 'ok'
    END AS status
FROM bastion_provenance.sources
WHERE enabled = TRUE
ORDER BY priority, last_success_at NULLS FIRST;

-- Lineage helper: given a curated row's claim_id, walk back to artifacts and sources
CREATE OR REPLACE VIEW bastion_provenance.v_claim_lineage AS
SELECT
    c.claim_id,
    c.claim_type,
    c.confidence,
    c.extractor_version,
    el.relation,
    ra.artifact_id,
    ra.fetched_at,
    ra.fetched_url,
    s.source_id,
    s.name             AS source_name,
    s.realism_tier,
    s.legal_posture
FROM bastion_provenance.claims c
JOIN bastion_provenance.evidence_links el ON el.claim_id = c.claim_id
JOIN bastion_provenance.raw_artifacts ra  ON ra.artifact_id = el.artifact_id
JOIN bastion_provenance.sources s         ON s.source_id = ra.source_id;

-- Crawl scheduler queue — what to fetch next, ordered by priority + staleness
CREATE OR REPLACE VIEW bastion_provenance.v_crawl_queue AS
SELECT
    source_id,
    name,
    category,
    priority,
    scrape_class,
    rate_limit_seconds,
    seed_urls,
    last_attempt_at,
    consecutive_failures,
    CASE
        WHEN last_attempt_at IS NULL THEN 9999
        ELSE EXTRACT(EPOCH FROM (NOW() - last_attempt_at))::INT
    END AS seconds_since_attempt
FROM bastion_provenance.sources
WHERE enabled = TRUE
  AND consecutive_failures < 5
ORDER BY priority ASC,
         seconds_since_attempt DESC;
