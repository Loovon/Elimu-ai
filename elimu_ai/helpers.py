import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

REFERRAL_ID = "elm-elimutalks-1"


def clean_answer(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = text.replace("#", "")
    text = text.replace("```", "")
    text = text.replace("__", "")
    return text.strip()


def referral_url(url: str) -> str:
    parsed = urlparse(url)

    query = parse_qs(parsed.query)

    query["rid"] = [REFERRAL_ID]

    new_query = urlencode(query, doseq=True)

    return urlunparse(parsed._replace(query=new_query))


def rewrite_links(text: str) -> str:
    urls = re.findall(r'https?://[^\s\)\]]+', text)

    for url in urls:
        text = text.replace(url, referral_url(url))

    return text
