"""Read-only stock news and annual filings for the chart."""

import html
import json
import re
from datetime import date
from functools import lru_cache
from io import BytesIO
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


def _get(url, params, headers=None, *, limit=4_000_000):
    with urlopen(Request(url + "?" + urlencode(params), headers=headers or {}), timeout=8) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Provider response too large")
    return data


def news(settings, name):
    search_url = "https://search.naver.com/search.naver?" + urlencode(
        {"where": "news", "query": name + " 주식"}
    )
    if not settings.naver_news_client_id or not settings.naver_news_client_secret:
        return {"status": "not_configured", "items": [], "search_url": search_url}
    data = json.loads(
        _get(
            "https://openapi.naver.com/v1/search/news.json",
            {"query": name, "display": 20, "sort": "date"},
            {
                "X-Naver-Client-Id": settings.naver_news_client_id.get_secret_value(),
                "X-Naver-Client-Secret": settings.naver_news_client_secret.get_secret_value(),
            },
        )
    )
    items = []
    for item in data["items"]:
        url = item.get("originallink") or item.get("link", "")
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username:
            continue
        title = html.unescape(re.sub(r"</?b>", "", item.get("title", "")))
        if title:
            items.append({"title": title, "url": url, "published_at": item.get("pubDate")})
    return {"status": "available", "items": items, "search_url": search_url}


@lru_cache(maxsize=4)
def _corporations(key, day):
    data = _get("https://opendart.fss.or.kr/api/corpCode.xml", {"crtfc_key": key}, limit=20_000_000)
    try:
        with ZipFile(BytesIO(data)) as archive:
            with archive.open("CORPCODE.xml") as xml:
                root = ElementTree.fromstring(xml.read(64_000_000))
    except BadZipFile:
        raise ValueError("OpenDART corporate code response failed") from None
    return {
        row.findtext("stock_code", "").strip(): row.findtext("corp_code", "").strip()
        for row in root.findall("list")
        if row.findtext("stock_code", "").strip()
    }


def financials(settings, symbol, *, today=None):
    if not settings.dart_api_key:
        return {"status": "not_configured", "items": []}
    today = today or date.today()
    key = settings.dart_api_key.get_secret_value()
    corp = _corporations(key, today).get(symbol)
    if not corp:
        return {"status": "empty", "items": []}
    for year in (today.year - 1, today.year - 2):
        for scope in ("CFS", "OFS"):
            data = json.loads(
                _get(
                    "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                    {
                        "crtfc_key": key,
                        "corp_code": corp,
                        "bsns_year": year,
                        "reprt_code": "11011",
                        "fs_div": scope,
                    },
                )
            )
            if data.get("status") == "013":
                continue
            if data.get("status") != "000":
                raise ValueError("OpenDART request failed")
            rows = data["list"]
            receipt = rows[0].get("rcept_no", "") if rows else ""
            return {
                "status": "available",
                "year": year,
                "scope": scope,
                "filing_url": "https://dart.fss.or.kr/dsaf001/main.do?"
                + urlencode({"rcpNo": receipt})
                if receipt.isdigit()
                else None,
                "items": [
                    {
                        "section": row["sj_nm"],
                        "account": row["account_nm"],
                        "detail": row.get("account_detail"),
                        "current": row.get("thstrm_amount"),
                        "previous": row.get("frmtrm_amount"),
                        "currency": row.get("currency"),
                    }
                    for row in rows
                ],
            }
    return {"status": "empty", "items": []}
