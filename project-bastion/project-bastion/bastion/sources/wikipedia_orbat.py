"""
Wikipedia Indian Army formations extractor.

Source: https://en.wikipedia.org/wiki/{formation}
Demo seeds: XIV Corps (India), Northern Command (India), Indian Army.

What we extract:
- formation_metadata: name, type (Corps/Division/Brigade), HQ, parent, role
- subordinate_units: list of unit names mentioned in the article infobox
  + the lead section. Confidence intentionally low (0.6) — Wikipedia ORBAT
  is not authoritative; this populates the OSINT layer for triangulation.

Why this matters for the demo:
- The Forward Stockout Predictor needs to know what posts hang under
  which Brigade, under which Corps. Wikipedia gives us the skeleton.
- Damien Symon + Globalsecurity tighten the leaves later.
- CAG audits + Parliament questions cross-validate force size.
"""
from __future__ import annotations
import re
from typing import Iterable

import structlog
from bs4 import BeautifulSoup

from ..core.extractor_base import ExtractedClaim
from ..extractors.html import HtmlExtractor

log = structlog.get_logger(__name__)


# Match formation-type words in the infobox header / lead.
_FORMATION_TYPES = ["Corps", "Division", "Brigade", "Command", "Battalion", "Regiment"]


def _infobox_dict(soup: BeautifulSoup) -> dict[str, str]:
    """Convert the Wikipedia infobox into {label: value} dict."""
    out = {}
    box = soup.find("table", class_=re.compile(r"\binfobox\b"))
    if not box:
        return out
    for row in box.find_all("tr"):
        th, td = row.find("th"), row.find("td")
        if th and td:
            label = th.get_text(" ", strip=True).lower()
            value = td.get_text(" ", strip=True)
            out[label] = value
    return out


def _xpath_for(soup: BeautifulSoup, element) -> str:
    """Best-effort xpath for the provenance UI to highlight."""
    parts = []
    cur = element
    while cur and cur.name and cur.name != "[document]":
        siblings = [s for s in cur.parent.find_all(cur.name, recursive=False)] if cur.parent else []
        idx = siblings.index(cur) + 1 if cur in siblings else 1
        parts.append(f"{cur.name}[{idx}]")
        cur = cur.parent
    return "/" + "/".join(reversed(parts))


class WikipediaOrbatExtractor(HtmlExtractor):
    EXTRACTOR_NAME = "html:wikipedia_orbat"
    EXTRACTOR_VERSION = "0.1.0"

    def _claims_from_soup(
        self,
        soup: BeautifulSoup,
        source_row: dict,
        artifact_meta: dict,
    ) -> Iterable[ExtractedClaim]:
        # Title comes from h1#firstHeading
        h1 = soup.find("h1", id="firstHeading")
        title = h1.get_text(strip=True) if h1 else None
        if not title:
            log.warning("wiki_no_title", artifact_id=artifact_meta["artifact_id"])
            return

        infobox = _infobox_dict(soup)

        # Detect formation type from title or infobox 'type' field
        formation_type = None
        for t in _FORMATION_TYPES:
            if re.search(rf"\b{t}\b", title, re.IGNORECASE):
                formation_type = t.lower()
                break
        if not formation_type:
            for t in _FORMATION_TYPES:
                for v in infobox.values():
                    if re.search(rf"\b{t}\b", v, re.IGNORECASE):
                        formation_type = t.lower()
                        break
                if formation_type:
                    break

        # Headquarters / Garrison
        hq = (
            infobox.get("headquarters")
            or infobox.get("garrison/hq")
            or infobox.get("garrison")
        )

        # Parent formation (often "Part of" in infobox)
        parent = infobox.get("part of")

        yield ExtractedClaim(
            claim_type="orbat_formation",
            payload={
                "name": title,
                "formation_type": formation_type,
                "headquarters": hq,
                "parent_formation": parent,
                "infobox_raw": infobox,
                "source_url": artifact_meta["fetched_url"],
            },
            confidence=0.6,
            locator={
                "selector": "table.infobox",
                "xpath": _xpath_for(soup, soup.find("table", class_=re.compile(r"\binfobox\b"))) if infobox else "/",
            },
        )

        # Subordinate units: scan the lead paragraphs for any matches against
        # known formation-naming patterns. Conservative — only emit for
        # formations that match the Indian Army naming scheme.
        lead = ""
        content_div = soup.find("div", id="mw-content-text")
        if content_div:
            for p in content_div.find_all("p", limit=6):
                lead += p.get_text(" ", strip=True) + "\n"

        # Indian Army formation patterns
        unit_patterns = [
            r"\b(\d{1,3}(?:st|nd|rd|th)?\s+(?:Mountain|Infantry|Armoured|Mechanised|Artillery)?\s*(?:Division|Brigade|Battalion))\b",
            r"\b((?:[IVX]+)\s+Corps)\b",
        ]
        seen_units = set()
        # Normalise title for self-loop detection: "XIV Corps (India)" -> "xiv corps"
        title_norm = re.sub(r"\s*\([^)]*\)\s*", "", title).strip().lower()
        for pat in unit_patterns:
            for m in re.finditer(pat, lead, re.IGNORECASE):
                unit_name = m.group(1).strip()
                unit_norm = unit_name.lower()
                if unit_norm == title_norm or unit_norm == title.lower() or unit_name in seen_units:
                    continue
                seen_units.add(unit_name)

        for unit_name in sorted(seen_units):
            yield ExtractedClaim(
                claim_type="orbat_subordinate_link",
                payload={
                    "parent": title,
                    "subordinate": unit_name,
                    "evidence_kind": "wikipedia_lead_text",
                    "source_url": artifact_meta["fetched_url"],
                },
                confidence=0.4,           # low — needs Damien Symon corroboration
                locator={"in": "lead_paragraphs"},
            )
