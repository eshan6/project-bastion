"""
IMD daily weather bulletin extractor.

Source: https://mausam.imd.gov.in/Forecast/marquee_data/{yyyymmdd}_dailyweather.pdf

Format notes (from inspection of recent bulletins):
- Page 1: pan-India synoptic summary — narrative text.
- Page 2-N: per-station tables with Tmax/Tmin/Rainfall(24hr).
- Stations are organized by sub-division.
- Eastern Ladakh stations of interest: Leh, Kargil, Drass (when reported),
  sometimes Nyoma, Hanle (rarely in pan-India bulletin; appear in regional).

Claims emitted:
- imd_synoptic_summary  (one per bulletin, page 1)
- imd_station_obs       (one per station-day, with tmax/tmin/rain)

The claim payload always includes valid_from = bulletin date so the
ontology layer can join temporally to other sources.

Realistic warning: IMD's PDF format has changed at least twice in the
past decade. This extractor targets the 2020+ format. Earlier years need
a separate parser (or pdfplumber + OCR + LLM rescue, deferred to Block B
fitting work).
"""
from __future__ import annotations
import re
from datetime import date
from typing import Iterable

import structlog

from ..core.extractor_base import ExtractedClaim
from ..extractors.pdf import PdfExtractor, PdfPage

log = structlog.get_logger(__name__)


# Stations relevant to Eastern Ladakh demo — names as IMD writes them.
# Add more as we discover variants in real bulletins.
_LADAKH_STATIONS = {
    "leh": {"lat": 34.1526, "lon": 77.5770, "elev_m": 3500},
    "kargil": {"lat": 34.5553, "lon": 76.1349, "elev_m": 2680},
    "drass": {"lat": 34.4267, "lon": 75.7647, "elev_m": 3280},
    "nyoma": {"lat": 33.1736, "lon": 78.6442, "elev_m": 4200},
}

# Date pattern in IMD bulletin titles: "Dated 15 January 2026"
_DATE_RE = re.compile(
    r"(?:dated\s+)?(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}


def _extract_bulletin_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    mon = m.group(2)[:3].lower()
    year = int(m.group(3))
    try:
        return date(year, _MONTHS[mon], day).isoformat()
    except (KeyError, ValueError):
        return None


# Heuristic: a station data line in 2020+ format looks like
#   LEH    -8.5   -15.2   0.0
# or
#   Leh:  Tmax -8.5°C, Tmin -15.2°C, RF 0.0 mm
# We try both shapes.
_STATION_TABLE_LINE = re.compile(
    r"\b(?P<name>[A-Z][A-Za-z'\- ]{2,30})\s+"
    r"(?P<tmax>-?\d+(?:\.\d+)?)\s+"
    r"(?P<tmin>-?\d+(?:\.\d+)?)\s+"
    r"(?P<rain>\d+(?:\.\d+)?|TR|NIL)\b"
)
_STATION_PROSE = re.compile(
    r"\b(?P<name>[A-Z][A-Za-z'\- ]{2,30})\b[^\n]{0,80}?"
    r"(?:tmax|max(?:imum)?(?:\s+temp)?)[^\d-]{0,10}(?P<tmax>-?\d+(?:\.\d+)?)"
    r"[^\n]{0,80}?(?:tmin|min(?:imum)?(?:\s+temp)?)[^\d-]{0,10}(?P<tmin>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _norm_station(name: str) -> str | None:
    n = name.strip().lower()
    # exact match against our gazetteer
    if n in _LADAKH_STATIONS:
        return n
    # also accept variants like "leh (ladakh)"
    for key in _LADAKH_STATIONS:
        if n.startswith(key):
            return key
    return None


class ImdDailyBulletinExtractor(PdfExtractor):
    EXTRACTOR_NAME = "pdf:imd_daily_bulletin"
    EXTRACTOR_VERSION = "0.1.0"

    def _claims_from_pages(
        self,
        pages: list[PdfPage],
        source_row: dict,
        artifact_meta: dict,
    ) -> Iterable[ExtractedClaim]:
        # 1. Find the bulletin date — usually on page 1.
        bulletin_date = None
        for p in pages[:3]:
            bulletin_date = _extract_bulletin_date(p.text)
            if bulletin_date:
                break

        if not bulletin_date:
            # Fall back to fetched_at date — better than no temporal anchor.
            bulletin_date = str(artifact_meta["fetched_at"])[:10]
            log.warning(
                "imd_no_date_in_pdf",
                artifact_id=artifact_meta["artifact_id"],
                falling_back_to=bulletin_date,
            )

        # 2. Synoptic summary claim from page 1.
        if pages:
            summary = pages[0].text.strip()[:2000]
            yield ExtractedClaim(
                claim_type="imd_synoptic_summary",
                payload={
                    "date": bulletin_date,
                    "summary_text": summary,
                    "source_url": artifact_meta["fetched_url"],
                },
                confidence=0.95,
                valid_from=bulletin_date,
                valid_to=bulletin_date,
                locator={"page_no": 1, "method": pages[0].method},
            )

        # 3. Per-station observations across all pages.
        seen = set()  # dedupe (station, date)
        for page in pages:
            # Try table format first
            for m in _STATION_TABLE_LINE.finditer(page.text):
                key = _norm_station(m.group("name"))
                if not key or (key, bulletin_date) in seen:
                    continue
                tmax, tmin = float(m.group("tmax")), float(m.group("tmin"))
                rain_raw = m.group("rain")
                rain = 0.0 if rain_raw.upper() in ("TR", "NIL") else float(rain_raw)
                seen.add((key, bulletin_date))
                yield self._station_claim(key, bulletin_date, tmax, tmin, rain, page, "table", artifact_meta)

            # Try prose format
            for m in _STATION_PROSE.finditer(page.text):
                key = _norm_station(m.group("name"))
                if not key or (key, bulletin_date) in seen:
                    continue
                tmax, tmin = float(m.group("tmax")), float(m.group("tmin"))
                seen.add((key, bulletin_date))
                yield self._station_claim(key, bulletin_date, tmax, tmin, None, page, "prose", artifact_meta)

    def _station_claim(self, station_key, bulletin_date, tmax, tmin, rain, page, parse_method, artifact_meta):
        station_meta = _LADAKH_STATIONS[station_key]
        return ExtractedClaim(
            claim_type="imd_station_obs",
            payload={
                "station": station_key,
                "lat": station_meta["lat"],
                "lon": station_meta["lon"],
                "elev_m": station_meta["elev_m"],
                "date": bulletin_date,
                "tmax_c": tmax,
                "tmin_c": tmin,
                "rain_mm_24h": rain,
            },
            confidence=0.90,
            valid_from=bulletin_date,
            valid_to=bulletin_date,
            locator={
                "page_no": page.page_no,
                "method": page.method,
                "parse_method": parse_method,
            },
        )
