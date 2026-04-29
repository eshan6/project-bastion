# project-bastion

Predictive military sustainment platform for high-altitude Indian Army formations. Built by Silverpot Defence Technologies.

This repository is the **ingestion + extraction pipeline** for Project Bastion: scrapers that pull from public sources (IMD, BRO, Wikipedia, CAG, RTI, Bhuvan, etc.) and per-source extractors that emit structured claims with full lineage back to the raw artifact and source.

> For full context — execution plan, ontology, model specs, working-style rules — read [`CLAUDE.md`](./CLAUDE.md). It is the master briefing for this project.

## Folder structure

```
project-bastion/
├── CLAUDE.md                      # master briefing — read this first
├── README.md
├── bastion/
│   ├── __init__.py
│   ├── cli.py                     # bastion CLI: fetch, queue, run-due, extract
│   ├── core/
│   │   ├── __init__.py
│   │   ├── extractor_base.py      # abstract Extractor + ExtractedClaim
│   │   └── db_extras.py           # idempotent claim + evidence_link writers
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── pdf.py                 # PdfExtractor (pdfplumber + OCR fallback)
│   │   └── html.py                # HtmlExtractor (BeautifulSoup + lxml)
│   └── sources/
│       ├── __init__.py            # EXTRACTOR_BY_SOURCE registry
│       ├── imd_daily_bulletin.py  # IMD weather bulletin parser
│       └── wikipedia_orbat.py     # Wikipedia Indian Army formation parser
└── tests/
    ├── __init__.py
    └── thursday_e2e_test.py       # end-to-end pipeline test (embedded Postgres)
```

## Provenance contract

Every fact in the system traces back to the artifact, source, and extractor version that produced it. The contract is enforced structurally:

- All extractors inherit from `bastion.core.extractor_base.Extractor`.
- Claims are written via `bastion.core.db_extras.insert_claim_with_evidence`, which produces deterministic UUID5 claim IDs keyed on `(extractor_name, version, claim_type, payload_hash)`.
- Re-running an extractor against the same artifact produces zero new rows. This is verified in `tests/thursday_e2e_test.py`.

The lineage view `bastion_provenance.v_claim_lineage` joins claim → evidence → artifact → source in a single query. The Provenance UI in the demo reads from this view.

## Status

Phase 1 of 5. Wedge product: Forward Stockout Predictor for a Brigade in Eastern Ladakh (XIV Corps area), built on synthetic + public data. See `CLAUDE.md` §3 for the 12-week block plan.
