import argparse
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("elimu_crawler")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = BASE_DIR / "elimu_catalogue.json"
SITEMAP_NS = {"sm": "https://www.elimulibrary.com/sitemap.xml"}


def canonical_url(url: str) -> str:
    """Remove query/fragment noise so repeated crawls upsert one record."""
    parsed = urlparse((url or "").strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _first_match(patterns: Iterable[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).replace("-", " ").strip()
    return ""


def infer_metadata(url: str, title: str = "", description: str = "") -> Dict[str, str]:
    """Infer curriculum fields from Elimu URL/page text without an LLM."""
    text = " ".join((url, title, description)).lower().replace("_", "-")
    grade = _first_match((r"\b(grade[- ]?(?:pp)?\d+)\b", r"\b(form[- ]?[1-4])\b", r"\b(class[- ]?\d+)\b"), text)
    term = _first_match((r"\b(term[- ]?[1-3])\b",), text)
    year = _first_match((r"\b((?:19|20)\d{2})\b",), text)
    aliases = {
        "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics",
        "kiswahili": "kiswahili", "english": "english", "biology": "biology",
        "chemistry": "chemistry", "physics": "physics", "history": "history",
        "geography": "geography", "business studies": "businessstudies",
        "computer studies": "computerstudies", "home science": "homescience",
        "science": "science", "cre": "cre", "ire": "ire",
    }
    subject = next((value for key, value in aliases.items() if key in text), "")
    category = ""
    for marker, value in (
        ("schemes-of-work", "Schemes of Work"), ("lesson-plans", "Lesson Plans"),
        ("secondary-notes", "Secondary Notes"), ("primary-notes", "Primary Notes"),
        ("secondary-exams", "Secondary Exams"), ("kcse-revision", "KCSE Revision Exams"),
        ("curriculum-designs", "CBC Curriculum Designs"), ("assessment", "Assessments"),
        ("knowledge/", "Knowledge Article"),
    ):
        if marker in text:
            category = value
            break
    if "knowledge/" in text:
        source_type, doctype, audience = "knowledge_article", "Knowledge Article", "student"
    elif "/category/" in text:
        source_type, doctype, audience = "category_page", "Category Page", ""
    else:
        source_type = "catalog_document"
        doctype = ""
        audience = "teacher" if "scheme" in text or "lesson plan" in text else "student"
    return {"grade": grade, "subject": subject, "term": term, "year": year, "category": category, "doctype": doctype, "audience": audience, "source_type": source_type}


class SitemapCrawler:
    def __init__(self, sitemap):
        self.sitemap = sitemap

    def urls(self, seen: Optional[set] = None):
        """Return page URLs, recursively expanding sitemap indexes."""
        seen = seen or set()
        if self.sitemap in seen:
            return []
        seen.add(self.sitemap)
        response = requests.get(self.sitemap, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        root_tag = root.tag.rsplit("}", 1)[-1]
        locations = [loc.text.strip() for loc in root.findall(".//sm:loc", SITEMAP_NS) if loc.text]
        if root_tag == "sitemapindex":
            urls: List[str] = []
            for child in locations:
                urls.extend(SitemapCrawler(child).urls(seen))
            return urls
        return list(dict.fromkeys(locations))

    def scrape(self, url):
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description_tag = soup.find("meta", attrs={"name": "description"})
        keywords_tag = soup.find("meta", attrs={"name": "keywords"})
        description = description_tag.get("content", "") if description_tag else ""
        keywords = keywords_tag.get("content", "") if keywords_tag else ""
        canonical = canonical_url(url)
        return {"url": canonical, "title": title, "description": description, "keywords": keywords, "content": soup.get_text(" ", strip=True), **infer_metadata(canonical, title, description)}


def crawl_sitemaps(sitemaps: Iterable[str]) -> List[Dict]:
    """Crawl multiple sitemap files and deduplicate URLs across sources."""
    records: Dict[str, Dict] = {}
    for sitemap in sitemaps:
        crawler = SitemapCrawler(sitemap)
        try:
            urls = crawler.urls()
        except Exception as exc:
            logger.warning("sitemap failed %s: %s", sitemap, exc)
            continue
        logger.info("sitemap %s: %d URLs", sitemap, len(urls))
        for url in urls:
            key = canonical_url(url)
            if key in records:
                continue
            try:
                records[key] = crawler.scrape(url)
            except Exception as exc:
                logger.warning("page failed %s: %s", url, exc)
    return list(records.values())


def merge_catalogue(records: Iterable[Dict], path: Path = DEFAULT_CATALOGUE) -> Dict[str, int]:
    """Add/enrich records by canonical URL and atomically rewrite the catalogue."""
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    merged: Dict[str, Dict] = {}
    for record in existing:
        key = canonical_url(record.get("url", ""))
        if key:
            merged[key] = record
    added = enriched = 0
    for incoming in records:
        key = canonical_url(incoming.get("url", ""))
        if not key:
            continue
        incoming = {**incoming, "url": key}
        if key not in merged:
            merged[key] = incoming
            added += 1
        else:
            before = dict(merged[key])
            merged[key] = {**merged[key], **{k: v for k, v in incoming.items() if v not in (None, "", [])}}
            if merged[key] != before:
                enriched += 1
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {"total": len(merged), "added": added, "enriched": enriched}


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl and enrich Elimu Library sitemap data")
    parser.add_argument("sitemaps", nargs="+", help="Sitemap or sitemap-index URLs")
    parser.add_argument("--output", type=Path, default=DEFAULT_CATALOGUE)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(merge_catalogue(crawl_sitemaps(args.sitemaps), args.output)))


if __name__ == "__main__":
    main()
