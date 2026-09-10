#!/usr/bin/env python3
import asyncio
import csv
import gzip
import html
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

INPUT = Path(os.getenv("INPUT_FILE", "companies_no_email.csv.gz"))
REFERENCE = Path(os.getenv("REFERENCE_FILE", "companies_with_emails.csv.gz"))
STATE = Path(os.getenv("STATE_FILE", "progress.json"))
RESULTS = Path(os.getenv("RESULTS_DIR", "results"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "80"))
PER_HOST = int(os.getenv("PER_HOST", "2"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "18"))
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))
MAX_BYTES = int(os.getenv("MAX_RESPONSE_BYTES", str(2 * 1024 * 1024)))
USER_AGENT = "AstraEmailDiscovery/1.0 (+https://github.com/worldwidetradex4/2gis-email-discovery)"

EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])([a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)")
CONTACT_HINTS = ("contact", "contacts", "kontakt", "kontakty", "kontakti", "контакт", "about", "o-nas", "company", "requisite", "rekvizit", "связ", "feedback")
BAD_LOCAL = {"test", "example", "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "root"}
BAD_DOMAINS = {"example.com", "example.org", "example.net", "localhost", "sentry.io"}
BAD_HOSTS = {"t.me", "max.ru", "jivo.chat", "tilda.ws"}
ASSETS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".pdf", ".zip", ".rar", ".7z", ".mp4", ".mp3", ".woff", ".woff2", ".ttf")


def host_of(url):
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def canonical(url):
    try:
        url, _ = urldefrag(url.strip())
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        host = p.hostname.lower()
        if host in BAD_HOSTS or any(host.endswith("." + x) for x in BAD_HOSTS):
            return None
        if p.path.lower().endswith(ASSETS):
            return None
        port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
        return f"{p.scheme.lower()}://{host}{port}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
    except Exception:
        return None


def clean_email(value):
    value = html.unescape(value or "").strip().strip(".,;:()[]{}<>\"'").lower()
    if value.count("@") != 1 or len(value) > 254 or ".." in value:
        return None
    local, domain = value.rsplit("@", 1)
    if local in BAD_LOCAL or domain in BAD_DOMAINS or domain.endswith(ASSETS):
        return None
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}", local, re.I):
        return None
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", domain, re.I):
        return None
    return value


def emails_in(text):
    found = set()
    for raw in EMAIL_RE.findall(html.unescape(text or "")):
        email = clean_email(raw)
        if email:
            found.add(email)
    return found


def decode_cf(encoded):
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def parse_html(base_url, body, root_host):
    soup = BeautifulSoup(body, "html.parser")
    emails = emails_in(body)
    links = []
    for tag in soup.select("[data-cfemail]"):
        email = clean_email(decode_cf(tag.get("data-cfemail", "")))
        if email:
            emails.add(email)
    for tag in soup.find_all("a", href=True):
        href = html.unescape(tag.get("href", "").strip())
        if href.lower().startswith("mailto:"):
            for raw in re.split(r"[,;]", href[7:].split("?", 1)[0]):
                email = clean_email(raw)
                if email:
                    emails.add(email)
            continue
        absolute = canonical(urljoin(base_url, href))
        if not absolute or host_of(absolute) != root_host:
            continue
        signal = (tag.get_text(" ", strip=True) + " " + absolute).lower()
        score = sum(hint in signal for hint in CONTACT_HINTS)
        if score:
            links.append((score, absolute))
    links.sort(key=lambda item: (-item[0], len(item[1])))
    return emails, [url for _, url in links]


async def fetch(session, url):
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status != 200:
                return None, None, f"http_{response.status}"
            content_type = (response.headers.get("content-type") or "").lower()
            if "html" not in content_type and "text/plain" not in content_type:
                return None, None, "non_html"
            data = await response.content.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return None, None, "too_large"
            try:
                body = data.decode(response.charset or "utf-8", errors="replace")
            except LookupError:
                body = data.decode("utf-8", errors="replace")
            return str(response.url), body, None
    except asyncio.TimeoutError:
        return None, None, "timeout"
    except aiohttp.ClientError as exc:
        return None, None, type(exc).__name__
    except Exception as exc:
        return None, None, type(exc).__name__


async def crawl_site(session, start_url):
    root_host = host_of(start_url)
    first = canonical(start_url)
    if not root_host or not first:
        return {}, "invalid_url"
    queue = [first]
    visited = set()
    findings = {}
    last_error = "no_email"
    while queue and len(visited) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        final_url, body, error = await fetch(session, url)
        if error:
            last_error = error
            continue
        final_host = host_of(final_url)
        if final_host:
            root_host = final_host
        found, discovered = parse_html(final_url, body, root_host)
        for email in found:
            findings.setdefault(email, final_url)
        for link in discovered:
            if link not in visited and link not in queue and len(visited) + len(queue) < MAX_PAGES:
                queue.append(link)
    return findings, None if findings else last_error


def state_read():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"next_row": 0, "batch": 0, "processed": 0, "emails": 0, "done": False}


def state_write(state):
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATE)


def read_batch(start, limit):
    rows = []
    with gzip.open(INPUT, "rt", encoding="utf-8-sig", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            if index < start:
                continue
            if len(rows) >= limit:
                break
            website = (row.get("website") or "").strip()
            rows.append({
                "company_id": str(row.get("company_id", "")),
                "company_name": str(row.get("company_name", "")),
                "website": website,
            })
    return rows


def known_emails():
    known = set()
    files = [REFERENCE, *sorted(RESULTS.glob("astra-emails-*.csv.gz"))]
    for path in files:
        if not path.exists():
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    email = clean_email(row.get("email", ""))
                    if email:
                        known.add(email)
        except (OSError, EOFError, csv.Error):
            continue
    return known


async def main():
    started = time.monotonic()
    state = state_read()
    start = int(state.get("next_row", 0))
    batch = int(state.get("batch", 0)) + 1
    companies = read_batch(start, BATCH_SIZE)
    if not companies:
        state["done"] = True
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state_write(state)
        print(json.dumps(state))
        return

    previous = known_emails()
    groups = defaultdict(list)
    errors = Counter()
    for company in companies:
        host = host_of(company["website"])
        if host:
            groups[host].append(company)
        else:
            errors["invalid_url"] += 1

    timeout = aiohttp.ClientTimeout(total=TIMEOUT, connect=min(5, TIMEOUT), sock_read=TIMEOUT)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=PER_HOST, ttl_dns_cache=600, enable_cleanup_closed=True)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"}
    output = []

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        async def process(group):
            async with semaphore:
                findings, error = await crawl_site(session, group[0]["website"])
            if error:
                errors[error] += len(group)
            for company in group:
                for email, source_url in findings.items():
                    if email in previous:
                        continue
                    output.append({
                        "company_id": company["company_id"],
                        "company_name": company["company_name"],
                        "website": company["website"],
                        "email": email,
                        "source_url": source_url,
                        "source_type": "website",
                    })
        await asyncio.gather(*(process(group) for group in groups.values()))

    unique = {(row["company_id"], row["email"]): row for row in output}
    output = sorted(unique.values(), key=lambda row: (row["company_id"], row["email"]))
    RESULTS.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS / f"astra-emails-{batch:06d}.csv.gz"
    columns = ["company_id", "company_name", "website", "email", "source_url", "source_type"]
    with gzip.open(result_file, "wt", encoding="utf-8", newline="", compresslevel=6) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(output)

    state.update({
        "next_row": start + len(companies),
        "batch": batch,
        "processed": int(state.get("processed", 0)) + len(companies),
        "emails": int(state.get("emails", 0)) + len(output),
        "done": False,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_batch": {
            "start_row": start,
            "processed": len(companies),
            "hosts": len(groups),
            "emails": len(output),
            "errors": dict(errors),
            "result_file": str(result_file),
            "elapsed_seconds": round(time.monotonic() - started, 2),
        },
    })
    state_write(state)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
