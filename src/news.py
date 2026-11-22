"""Noticias de mercado: por activo (yfinance) y generales (feeds RSS/Atom).

Los titulares son datos públicos: se cachean en RAM del proceso (como las
cotizaciones de :mod:`src.market`) y no se guardan en la BD. La lista de feeds
es configurable por usuario en ``app_config['news_feeds']``.

Todo el texto que llega de fuera es **no fiable**: el asistente lo recibe
marcado como tal y nunca como instrucciones.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_FEEDS: list[dict[str, str]] = [
    {"name": "Expansión · Mercados", "url": "https://e00-expansion.uecdn.es/rss/mercados.xml"},
    {
        "name": "Cinco Días",
        "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/portada",
    },
    {"name": "Investing.com España", "url": "https://es.investing.com/rss/news.rss"},
    {
        "name": "CNBC · Markets",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    },
    {"name": "MarketWatch", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
]
CONFIG_KEY = "news_feeds"
MAX_FEEDS = 15
MAX_BYTES = 2 * 1024 * 1024
TTL = 900
TIMEOUT = 8.0

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None, limit: int = 400) -> str:
    text = unescape(_TAG_RE.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _cached(key: str) -> list[dict[str, Any]] | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < TTL:
        return entry[1]
    return None


def _iso(value: str | int | float | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, UTC).isoformat()
        try:
            return parsedate_to_datetime(value).astimezone(UTC).isoformat()
        except (TypeError, ValueError):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


# ── Seguridad de URLs configurables ──────────────────────────────────────────


def validate_feed_url(url: str) -> str:
    """Solo http(s) a hosts públicos (evita que un feed apunte a la red interna)."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("El feed debe ser una URL http(s)")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"No se puede resolver {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("El feed debe apuntar a un servidor público")
    return url


# ── Feeds del usuario ────────────────────────────────────────────────────────


def get_feeds() -> list[dict[str, str]]:
    from .db.session import _session
    from .models import AppConfig

    with _session() as s:
        row = s.query(AppConfig).filter_by(key=CONFIG_KEY).first()
        if row is None or not row.value:
            return [dict(f) for f in DEFAULT_FEEDS]
        try:
            items = json.loads(row.value)
        except ValueError:
            return [dict(f) for f in DEFAULT_FEEDS]
    return [
        {"name": str(i.get("name") or i.get("url")), "url": str(i["url"])}
        for i in items
        if isinstance(i, dict) and i.get("url")
    ]


def set_feeds(feeds: list[dict[str, str]]) -> list[dict[str, str]]:
    from .db.session import _session
    from .models import AppConfig

    if len(feeds) > MAX_FEEDS:
        raise ValueError(f"Como mucho {MAX_FEEDS} feeds")
    clean = []
    for feed in feeds:
        url = validate_feed_url(feed.get("url", ""))
        clean.append({"name": (feed.get("name") or urlparse(url).hostname or url)[:80], "url": url})
    with _session() as s:
        row = s.query(AppConfig).filter_by(key=CONFIG_KEY).first()
        if row is None:
            row = AppConfig(key=CONFIG_KEY)
            s.add(row)
        row.value = json.dumps(clean, ensure_ascii=False)
    return clean


# ── RSS / Atom ───────────────────────────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(data: bytes, source: str) -> list[dict[str, Any]]:
    """RSS 2.0 y Atom sin dependencias (ElementTree no resuelve entidades externas)."""
    if b"<!ENTITY" in data[:4096]:
        raise ValueError("Feed con entidades XML no soportado")
    root = ET.fromstring(data)
    items: list[dict[str, Any]] = []
    for node in root.iter():
        if _local(node.tag) not in {"item", "entry"}:
            continue
        fields: dict[str, str] = {}
        link = ""
        for child in node:
            name = _local(child.tag)
            if name == "link":
                link = link or child.get("href") or (child.text or "")
            elif name in {"title", "description", "summary", "pubdate", "published", "updated", "date"}:
                fields.setdefault(name, child.text or "")
        title = _clean(fields.get("title"), 300)
        if not title:
            continue
        items.append(
            {
                "title": title,
                "summary": _clean(fields.get("description") or fields.get("summary")),
                "url": link.strip(),
                "source": source,
                "published_at": _iso(
                    fields.get("pubdate")
                    or fields.get("published")
                    or fields.get("updated")
                    or fields.get("date")
                ),
            }
        )
    return items


def fetch_feed(feed: dict[str, str]) -> list[dict[str, Any]]:
    key = f"feed:{feed['url']}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        # Cada salto (incluidas redirecciones) se valida contra hosts privados.
        with httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=3,
            event_hooks={"request": [lambda request: validate_feed_url(str(request.url))]},
            headers={"User-Agent": "financial-tools/0.2 (+rss reader)"},
        ) as client:
            with client.stream("GET", feed["url"]) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Feed demasiado grande")
                    chunks.append(chunk)
        items = parse_feed(b"".join(chunks), feed.get("name") or feed["url"])
    except Exception as exc:  # un feed caído no rompe el resto
        logger.info("feed %s: %s", feed.get("url"), exc)
        items = []
    _cache[key] = (time.time(), items)
    return items


def market_news(query: str | None = None, limit: int = 20) -> dict[str, Any]:
    feeds = get_feeds()
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(feeds)))) as pool:
        batches = list(pool.map(fetch_feed, feeds))
    items = [item for batch in batches for item in batch]
    if query:
        terms = [t for t in query.lower().split() if t]
        items = [
            i for i in items if any(t in (i["title"] + " " + i["summary"]).lower() for t in terms)
        ]
    seen: set[str] = set()
    unique = []
    for item in sorted(items, key=lambda i: i["published_at"] or "", reverse=True):
        fingerprint = re.sub(r"\W+", "", item["title"].lower())[:80]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(item)
    return {
        "items": unique[:limit],
        "feeds": [f["name"] for f in feeds],
        "failed": [f["name"] for f, batch in zip(feeds, batches, strict=True) if not batch],
    }


# ── Noticias por activo (yfinance) ───────────────────────────────────────────


def _yf_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    title = _clean(content.get("title"), 300)
    if not title:
        return None
    provider = content.get("provider") or {}
    url = (content.get("canonicalUrl") or {}).get("url") or content.get("link") or ""
    return {
        "title": title,
        "summary": _clean(content.get("summary") or content.get("description")),
        "url": url,
        "source": (provider.get("displayName") if isinstance(provider, dict) else None)
        or content.get("publisher")
        or "Yahoo Finance",
        "published_at": _iso(content.get("pubDate") or content.get("providerPublishTime")),
    }


def asset_news(ticker: str, limit: int = 10) -> dict[str, Any]:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("Indica un ticker")
    key = f"yf:{ticker}"
    items = _cached(key)
    if items is None:
        import yfinance as yf

        try:
            raw = yf.Ticker(ticker).news or []
        except Exception as exc:
            logger.info("news %s: %s", ticker, exc)
            raw = []
        items = [i for i in (_yf_item(r) for r in raw if isinstance(r, dict)) if i]
        _cache[key] = (time.time(), items)
    return {"ticker": ticker, "items": items[:limit]}
