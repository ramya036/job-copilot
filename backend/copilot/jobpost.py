"""Fetch a job posting from a URL and reduce it to readable text."""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from urllib.parse import urlparse

import requests

MAX_BYTES = 2_000_000


def _is_public(host: str) -> bool:
    """Refuse to fetch private or local addresses (the server shouldn't be used to reach its own network)."""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except (socket.gaierror, ValueError):
        return False


def html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", page)
    page = re.sub(r"(?i)<li[^>]*>", "\n- ", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def fetch_job_text(url: str, timeout: float = 10) -> str:
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Enter a full http(s) link to the job posting")
    if not _is_public(parts.hostname):
        raise ValueError("That link points to a private address")
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "job-copilot/1.0"}, stream=True)
    resp.raise_for_status()
    body = resp.raw.read(MAX_BYTES, decode_content=True).decode(resp.encoding or "utf-8", errors="replace")
    text = html_to_text(body) if "html" in resp.headers.get("content-type", "html") else body
    if len(text) < 200:
        raise ValueError("Couldn't read the job description from that page. Paste the text instead.")
    return text
