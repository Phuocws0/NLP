"""Resolve Agoda hotel IDs from hotel URLs, checkpointing as URLs are processed."""

import argparse
import csv
import re
import shutil
import time
from pathlib import Path

import requests


PATTERN = re.compile(r"BelowFoldParams/GetSecondaryData\?hotel_id=(\d+)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", default="data/agoda_hotel_urls_sitemap.txt")
    parser.add_argument("--output", default="data/agoda_hotel_id_map.csv")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--max-new", type=int)
    parser.add_argument("--start-index", type=int, help="Override the automatic resume position")
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--browser", action="store_true", help="Resolve IDs with Chrome instead of HTTP")
    args = parser.parse_args()

    urls = [line.strip() for line in Path(args.urls).read_text(encoding="utf-8").splitlines() if line.strip()]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    mapped = {}
    if output.exists():
        with output.open(encoding="utf-8", newline="") as stream:
            mapped = {row["url"]: row["hotel_id"] for row in csv.DictReader(stream)}
    start_index = args.start_index
    if start_index is None:
        start_index = max((index + 1 for index, url in enumerate(urls) if url in mapped), default=0)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    })
    playwright = browser = page = None
    if args.browser:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            executable_path=shutil.which("google-chrome") or shutil.which("chromium"),
            headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page(locale="vi-VN")

    processed = found = consecutive_network_failures = cooldown_cycles = 0
    try:
        with output.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("url", "hotel_id"))
            if not mapped:
                writer.writeheader()
            for index, url in enumerate(urls):
                if index < start_index or url in mapped:
                    continue
                if args.max_new and processed >= args.max_new:
                    break
                try:
                    html = None
                    for attempt in range(3):
                        try:
                            if args.browser:
                                response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                                if response is None:
                                    raise requests.RequestException("No browser response")
                                if response.status >= 500:
                                    raise requests.RequestException(f"HTTP {response.status}")
                                if response.status >= 400:
                                    raise ValueError(f"HTTP {response.status}")
                                html = page.content()
                            else:
                                response = session.get(url, timeout=25)
                                if response.status_code >= 500:
                                    raise requests.RequestException(f"HTTP {response.status_code}")
                                response.raise_for_status()
                                html = response.text
                            break
                        except requests.RequestException:
                            if attempt == 2:
                                raise
                            time.sleep(2 ** attempt)

                    match = PATTERN.search(html or "")
                    if not match:
                        raise ValueError("Hotel ID absent")
                    mapped[url] = match.group(1)
                    writer.writerow({"url": url, "hotel_id": match.group(1)})
                    stream.flush()
                    found += 1
                    consecutive_network_failures = 0
                    cooldown_cycles = 0
                except Exception as exc:
                    message = str(exc).splitlines()[0]
                    print(f"ERROR {url}: {message}", flush=True)
                    if isinstance(exc, requests.RequestException) or "net::ERR" in message:
                        consecutive_network_failures += 1
                    else:
                        consecutive_network_failures = 0
                        cooldown_cycles = 0
                    if consecutive_network_failures >= 10:
                        cooldown_cycles += 1
                        if cooldown_cycles >= 4:
                            print("Stopped after four network-error cooldowns", flush=True)
                            break
                        print(f"Ten consecutive network errors; cooling down for 60 seconds ({cooldown_cycles}/3)", flush=True)
                        time.sleep(60)
                        consecutive_network_failures = 0
                processed += 1
                if processed % args.progress_every == 0:
                    print(f"Processed {processed} URLs; mapped {len(mapped)} IDs", flush=True)
                time.sleep(args.delay)
    finally:
        if browser is not None:
            browser.close()
            playwright.stop()

    print(f"Mapped {found} new hotels; {len(mapped)} total", flush=True)


if __name__ == "__main__":
    main()
