import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("bs4")

from crawler import SitemapCrawler, canonical_url, infer_metadata, merge_catalogue
from ingest import _deterministic_id, _build_search_text


def test_canonical_url_removes_tracking_duplicates():
    first = "https://www.elimulibrary.com/site/document/12/example?ref=elimutalks"
    second = "https://www.elimulibrary.com/site/document/12/example"
    assert canonical_url(first) == canonical_url(second)
    assert _deterministic_id(first) == _deterministic_id(second)


def test_infer_metadata_handles_document_category_and_article_urls():
    doc = infer_metadata(
        "https://www.elimulibrary.com/site/document/80/2024-form-3-klb-english-scheme-of-work-term-1",
        "2024 Form 3 English Scheme of Work Term 1",
        "Scheme of work for teachers",
    )
    assert doc["grade"] == "form 3"
    assert doc["subject"] == "english"
    assert doc["term"] == "term 1"
    assert doc["year"] == "2024"
    assert doc["source_type"] == "catalog_document"
    assert doc["audience"] == "teacher"

    article = infer_metadata("https://www.elimulibrary.com/knowledge/form-3-schemes-of-work")
    assert article["source_type"] == "knowledge_article"
    assert article["doctype"] == "Knowledge Article"


def test_sitemap_index_is_expanded_and_urls_are_deduplicated():
    responses = {
        "https://example.test/index.xml": b"""<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"><sitemap><loc>https://example.test/a.xml</loc></sitemap></sitemapindex>""",
        "https://example.test/a.xml": b"""<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"><url><loc>https://www.elimulibrary.com/site/document/1/item?ref=old</loc></url><url><loc>https://www.elimulibrary.com/site/document/1/item</loc></url></urlset>""",
    }

    def get(url, timeout=30):
        response = Mock(content=responses[url], text=responses[url].decode())
        response.raise_for_status.return_value = None
        return response

    with patch("crawler.requests.get", side_effect=get):
        urls = SitemapCrawler("https://example.test/index.xml").urls()

    assert urls == ["https://www.elimulibrary.com/site/document/1/item?ref=old", "https://www.elimulibrary.com/site/document/1/item"]


def test_merge_catalogue_adds_and_enriches_without_duplicates(tmp_path: Path):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps([{
        "url": "https://www.elimulibrary.com/site/document/1/item?ref=old",
        "title": "Old title",
    }]), encoding="utf-8")
    stats = merge_catalogue([{
        "url": "https://www.elimulibrary.com/site/document/1/item",
        "title": "New title",
        "subject": "mathematics",
    }, {
        "url": "https://www.elimulibrary.com/knowledge/cbc-assessment-books",
        "title": "CBC Assessment Books",
        "source_type": "knowledge_article",
    }], path)
    records = json.loads(path.read_text(encoding="utf-8"))
    assert stats == {"total": 2, "added": 1, "enriched": 1}
    assert len(records) == 2
    assert records[0]["title"] == "New title"
    assert records[0]["subject"] == "mathematics"


def test_search_text_includes_enriched_page_content():
    text = _build_search_text({
        "title": "CBC Assessment Books",
        "keywords": "cbc assessment grade 3",
        "content": "Detailed article body about assessment and revision.",
    })
    assert "Keywords:" in text
    assert "Page content:" in text
