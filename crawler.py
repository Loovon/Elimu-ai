import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup


class SitemapCrawler:

    def __init__(self, sitemap):
        self.sitemap = sitemap

    def urls(self):
        xml = requests.get(self.sitemap, timeout=30)

        root = ET.fromstring(xml.content)

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        return [
            loc.text
            for loc in root.findall(".//sm:loc", ns)
        ]

    def scrape(self, url):

        page = requests.get(url, timeout=30)

        soup = BeautifulSoup(page.text, "html.parser")

        title = soup.title.text if soup.title else ""

        desc = ""

        tag = soup.find(
            "meta",
            attrs={"name": "description"}
        )

        if tag:
            desc = tag.get("content", "")

        keywords = ""

        tag = soup.find(
            "meta",
            attrs={"name": "keywords"}
        )

        if tag:
            keywords = tag.get("content", "")

        body = soup.get_text(" ", strip=True)

        return {
            "url": url,
            "title": title,
            "description": desc,
            "keywords": keywords,
            "content": body,
        }
