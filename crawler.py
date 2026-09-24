import argparse
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse, urlunparse

import requests


logger = logging.getLogger("elimu_crawler")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = BASE_DIR / "elimu_catalogue.json"

SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9"
}

# Only used for authenticated sitemap requests.
# The token is NEVER sent to document pages.
ELIMU_SITEMAP_HEADERS = {
    "User-Agent": "ElimuSitemapMonitor/1.0",
    "Accept": "application/xml",
    "Accept-Encoding": "gzip, deflate",
}


def _sitemap_headers() -> Dict[str, str]:
    """
    Build authenticated headers for Elimu Library sitemap requests.

    ELIMU_TOKEN is intentionally used only for sitemap access.
    """
    token = os.getenv("ELIMU_TOKEN", "").strip()

    if not token:
        raise RuntimeError(
            "ELIMU_TOKEN is not configured. "
            "Add it to .env or the environment before crawling "
            "Elimu Library sitemaps."
        )

    return {
        **ELIMU_SITEMAP_HEADERS,
        "x-elimu-monitor": token,
    }


def canonical_url(url: str) -> str:
    """
    Remove query strings and fragments so repeated crawls
    upsert one catalogue record per URL.
    """
    parsed = urlparse((url or "").strip())

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
            "",
        )
    )


def extract_document_id(url: str) -> str:
    """
    Extract an Elimu Library document ID from URLs such as:

    /site/document/38/2022-form-1-business-studies-...

    Returns:
        "38"
    """
    match = re.search(
        r"/site/document/(\d+)(?:/|$)",
        url or "",
        re.IGNORECASE,
    )

    return match.group(1) if match else ""


def title_from_url(url: str) -> str:
    """
    Build a readable catalogue title from the URL slug.

    Example:
        2022-form-1-klb-business-studies-schemes-of-work-term-1

    becomes approximately:

        2022 Form 1 Klb Business Studies Schemes Of Work Term 1
    """
    parsed = urlparse(url or "")
    slug = parsed.path.rstrip("/").split("/")[-1]

    # Remove common date/time suffixes when they appear at the end.
    slug = re.sub(
        r"-\d{2}-\d{2}-[a-z]{2,3}-\d{2}-\d{2}-\d{2}$",
        "",
        slug,
        flags=re.IGNORECASE,
    )

    # Remove a numeric ID if it is part of the final slug.
    slug = re.sub(r"^\d+-", "", slug)

    title = slug.replace("-", " ").replace("_", " ").strip()

    # Normalize whitespace.
    title = re.sub(r"\s+", " ", title)

    # Capitalize words while preserving common abbreviations.
    words = []

    for word in title.split():
        lower = word.lower()

        if lower == "kcse":
            words.append("KCSE")
        elif lower == "cbc":
            words.append("CBC")
        elif lower == "klb":
            words.append("KLB")
        elif lower == "pp":
            words.append("PP")
        else:
            words.append(word.capitalize())

    return " ".join(words)


def _first_match(patterns: Iterable[str], text: str) -> str:
    """
    Return the first regex capture found in text.
    """
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(1).replace("-", " ").strip()

    return ""


def infer_metadata(
    url: str,
    title: str = "",
    description: str = "",
) -> Dict[str, str]:
    """
    Infer curriculum metadata from the URL and available catalogue text.

    No document page is fetched.
    No LLM is required.
    """
    text = " ".join(
        (
            url,
            title,
            description,
        )
    ).lower().replace("_", "-")

    # ---------------------------------------------------------
    # Grade / class / form
    # ---------------------------------------------------------

    grade = _first_match(
        (
            r"\b(grade[- ]?(?:pp)?\d+)\b",
            r"\b(form[- ]?[1-4])\b",
            r"\b(class[- ]?\d+)\b",
        ),
        text,
    )

    # ---------------------------------------------------------
    # Term
    # ---------------------------------------------------------

    term = _first_match(
        (
            r"\b(term[- ]?[1-3])\b",
        ),
        text,
    )

    # ---------------------------------------------------------
    # Year
    # ---------------------------------------------------------

    year = _first_match(
        (
            r"\b((?:19|20)\d{2})\b",
        ),
        text,
    )

    # ---------------------------------------------------------
    # Subject
    # ---------------------------------------------------------

    aliases = {
        "mathematics": "mathematics",
        "maths": "mathematics",
        "math": "mathematics",
        "kiswahili": "kiswahili",
        "english": "english",
        "biology": "biology",
        "chemistry": "chemistry",
        "physics": "physics",
        "history": "history",
        "geography": "geography",
        "business studies": "businessstudies",
        "business-studies": "businessstudies",
        "computer studies": "computerstudies",
        "computer-studies": "computerstudies",
        "home science": "homescience",
        "home-science": "homescience",
        "science": "science",
        "cre": "cre",
        "ire": "ire",
    }

    subject = ""

    for key, value in aliases.items():
        if key in text:
            subject = value
            break

    # ---------------------------------------------------------
    # Resource category
    # ---------------------------------------------------------

    category = ""

    for marker, value in (
        ("schemes-of-work", "Schemes of Work"),
        ("lesson-plans", "Lesson Plans"),
        ("secondary-notes", "Secondary Notes"),
        ("primary-notes", "Primary Notes"),
        ("secondary-exams", "Secondary Exams"),
        ("kcse-revision", "KCSE Revision Exams"),
        ("curriculum-designs", "CBC Curriculum Designs"),
        ("assessment", "Assessments"),
        ("knowledge/", "Knowledge Article"),
    ):
        if marker in text:
            category = value
            break

    # ---------------------------------------------------------
    # Source type / document type / audience
    # ---------------------------------------------------------

    if "knowledge/" in text:
        source_type = "knowledge_article"
        doctype = "Knowledge Article"
        audience = "student"

    elif "/category/" in text:
        source_type = "category_page"
        doctype = "Category Page"
        audience = ""

    else:
        source_type = "catalog_document"
        doctype = ""

        if "scheme" in text or "lesson plan" in text:
            audience = "teacher"
        else:
            audience = "student"

    return {
        "grade": grade,
        "subject": subject,
        "term": term,
        "year": year,
        "category": category,
        "doctype": doctype,
        "audience": audience,
        "source_type": source_type,
    }


def build_catalog_record(url: str) -> Dict:
    """
    Create a catalogue record from the sitemap URL only.

    IMPORTANT:
    This function does NOT fetch the document page.

    The resulting record contains metadata useful for:
        - search
        - recommendations
        - Qdrant indexing
        - AI resource discovery
        - linking users back to Elimu Library

    Actual paid document content is intentionally NOT downloaded.
    """
    canonical = canonical_url(url)

    title = title_from_url(canonical)

    document_id = extract_document_id(canonical)

    metadata = infer_metadata(
        canonical,
        title,
        "",
    )

    return {
        "url": canonical,
        "document_id": document_id,
        "title": title,
        "description": "",
        "keywords": "",
        "content": "",
        **metadata,
    }


class SitemapCrawler:
    """
    Authenticated Elimu Library sitemap crawler.

    This crawler ONLY reads sitemap XML files.

    It does NOT crawl document HTML pages.
    """

    def __init__(self, sitemap: str):
        self.sitemap = sitemap

    def urls(self, seen: Optional[set] = None) -> List[str]:
        """
        Return URLs from a sitemap or sitemap index.

        Sitemap requests use ELIMU_TOKEN authentication.
        """
        if seen is None:
            seen = set()

        if self.sitemap in seen:
            return []

        seen.add(self.sitemap)

        response = requests.get(
            self.sitemap,
            headers=_sitemap_headers(),
            timeout=30,
        )

        response.raise_for_status()

        root = ET.fromstring(response.content)

        root_tag = root.tag.rsplit("}", 1)[-1]

        locations = [
            loc.text.strip()
            for loc in root.findall(".//sm:loc", SITEMAP_NS)
            if loc.text
        ]

        # Sitemap index:
        # recursively retrieve its child sitemap URLs.
        if root_tag == "sitemapindex":
            urls: List[str] = []

            for child in locations:
                child_crawler = SitemapCrawler(child)
                urls.extend(child_crawler.urls(seen))

            return list(dict.fromkeys(urls))

        # Normal URL sitemap.
        return list(dict.fromkeys(locations))


def crawl_sitemaps(sitemaps: Iterable[str]) -> List[Dict]:
    """
    Crawl multiple authenticated sitemap files.

    IMPORTANT:
    Only sitemap XML files are requested.

    Document URLs are converted directly into catalogue records.
    Their actual HTML/content is never requested.
    """
    records: Dict[str, Dict] = {}

    for sitemap in sitemaps:
        crawler = SitemapCrawler(sitemap)

        try:
            urls = crawler.urls()

        except Exception as exc:
            logger.warning(
                "sitemap failed %s: %s",
                sitemap,
                exc,
            )
            continue

        logger.info(
            "sitemap %s: %d URLs",
            sitemap,
            len(urls),
        )

        for url in urls:
            key = canonical_url(url)

            if not key:
                continue

            if key in records:
                continue

            try:
                records[key] = build_catalog_record(key)

            except Exception as exc:
                logger.warning(
                    "catalog record failed %s: %s",
                    url,
                    exc,
                )

    return list(records.values())


def merge_catalogue(
    records: Iterable[Dict],
    path: Path = DEFAULT_CATALOGUE,
) -> Dict[str, int]:
    """
    Add/enrich records by canonical URL and atomically rewrite
    the catalogue.
    """
    existing = (
        json.loads(
            path.read_text(encoding="utf-8")
        )
        if path.exists()
        else []
    )

    merged: Dict[str, Dict] = {}

    for record in existing:
        key = canonical_url(
            record.get("url", "")
        )

        if key:
            merged[key] = record

    added = 0
    enriched = 0

    for incoming in records:
        key = canonical_url(
            incoming.get("url", "")
        )

        if not key:
            continue

        incoming = {
            **incoming,
            "url": key,
        }

        if key not in merged:
            merged[key] = incoming
            added += 1

        else:
            before = dict(merged[key])

            # Only replace existing fields with meaningful values.
            merged[key] = {
                **merged[key],
                **{
                    k: v
                    for k, v in incoming.items()
                    if v not in (None, "", [])
                },
            }

            if merged[key] != before:
                enriched += 1

    # Atomic write.
    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            list(merged.values()),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    tmp.replace(path)

    return {
        "total": len(merged),
        "added": added,
        "enriched": enriched,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl authenticated Elimu Library sitemaps "
            "and build a metadata-only catalogue."
        )
    )

    parser.add_argument(
        "sitemaps",
        nargs="+",
        help="Sitemap or sitemap-index URLs",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CATALOGUE,
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = merge_catalogue(
        crawl_sitemaps(args.sitemaps),
        args.output,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()