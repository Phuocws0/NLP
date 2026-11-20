"""Collect original Vietnamese Agoda hotel reviews with rating and date.

Run only with permission from Agoda. The site endpoint is used by the hotel's
review UI and may change. This script collects a documented sample, not a
guaranteed complete export of every review for each hotel.
"""

import argparse
import csv
import json
import os
import re
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests


REVIEWS_API = "https://www.agoda.com/api/cronos/property/review/ReviewComments"
HOTEL_ID_PATTERN = re.compile(r"BelowFoldParams/GetSecondaryData\?hotel_id=(\d+)")
FIELDNAMES = (
    "hotel_id", "hotel_name", "hotel_url", "review_id", "review_date",
    "rating_10", "review_title", "review_text", "language_code",
    "nps_group", "first_seen_sort", "first_seen_page",
)
DEFAULT_SORTS = (1, 2, 3, 7)  # recent, high rating, low rating, helpful


class BrowserReviewResponse:
    def __init__(self, status: int, data: dict | None):
        self.status_code = status
        self.data = data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} from Agoda review API")

    def json(self) -> dict:
        if self.data is None:
            raise ValueError("Agoda review API returned no JSON")
        return self.data


class BrowserReviewSession:
    def __init__(self, page):
        self.page = page

    def post(self, url: str, json: dict, headers: dict, timeout: int) -> BrowserReviewResponse:
        try:
            result = self.page.evaluate(
                """async ({url, payload}) => {
                    const response = await fetch(url, {
                        method: 'POST',
                        headers: {'content-type': 'application/json'},
                        body: JSON.stringify(payload)
                    });
                    return {
                        status: response.status,
                        data: response.ok ? await response.json() : null
                    };
                }""",
                {"url": url, "payload": json},
            )
        except Exception as exc:
            raise requests.RequestException(str(exc)) from exc
        return BrowserReviewResponse(result["status"], result["data"])


def group_for_rating(rating: float) -> str:
    if rating <= 6.4:
        return "Detractors"
    if rating <= 8.2:
        return "Passives"
    return "Promoters"


def get_json(session: requests.Session, url: str, payload: dict, referer: str) -> dict:
    for attempt in range(3):
        try:
            response = session.post(url, json=payload, headers={"Referer": referer}, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable")


def hotel_details(session: requests.Session, url: str) -> tuple[int, str]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    match = HOTEL_ID_PATTERN.search(response.text)
    if not match:
        raise ValueError(f"Hotel ID absent from page: {url}")
    slug = url.rstrip("/").split("/hotel/")[0].split("/")[-1]
    return int(match.group(1)), slug.replace("-", " ").title()


def collect_hotel(
    session: requests.Session, url: str, page_size: int, max_pages: int,
    delay: float, sorts: tuple[int, ...], mapped_hotel: tuple[int, str] | None = None
) -> tuple[list[dict], dict]:
    hotel_id, hotel_name = mapped_hotel or hotel_details(session, url)
    found = {}
    provider_count = None
    repeated_pages = 0
    requests_made = 0

    for sorting in sorts:
        no_new_pages = 0
        for page in range(1, max_pages + 1):
            payload = {
                "hotelId": hotel_id,
                "providerId": 332,  # Agoda's own review provider
                "demographicId": 0,
                "page": page,
                "pageSize": page_size,
                "sorting": sorting,
                "providerIds": [332],
                "isReviewPage": True,
                "isCrawlablePage": False,
                "filters": {"language": [24], "room": []},  # Vietnamese
                "searchKeyword": "",
                "searchFilters": [],
            }
            data = get_json(session, REVIEWS_API, payload, url)
            requests_made += 1
            for provider in data.get("providerList", []):
                if provider.get("id") == 332:
                    provider_count = max(provider_count or 0, provider.get("totalIndex") or 0)

            new_count = 0
            for item in data.get("comments", []):
                if item.get("providerId") != 332 or item.get("translateSource") != "vi":
                    continue
                review_id = item.get("hotelReviewId")
                review_text = (item.get("originalComment") or item.get("reviewComments") or "").strip()
                if not review_id or not review_text or review_id in found:
                    continue
                try:
                    rating = float(item["rating"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not 0 <= rating <= 10:
                    continue
                found[review_id] = {
                    "hotel_id": hotel_id,
                    "hotel_name": hotel_name,
                    "hotel_url": url,
                    "review_id": review_id,
                    "review_date": item.get("reviewDate", ""),
                    "rating_10": rating,
                    "review_title": (item.get("originalTitle") or item.get("reviewTitle") or "").strip(),
                    "review_text": review_text,
                    "language_code": "vi",
                    "nps_group": group_for_rating(rating),
                    "first_seen_sort": sorting,
                    "first_seen_page": page,
                }
                new_count += 1

            if new_count == 0:
                no_new_pages += 1
                repeated_pages += 1
            else:
                no_new_pages = 0
            if not data.get("comments") or no_new_pages >= 2:
                break
            time.sleep(delay)

        # If the provider has at most one page in total, other sort orders can
        # only reshuffle the same reviews. Skip those requests for small hotels.
        if (provider_count is not None and provider_count <= page_size) or (provider_count is None and not found):
            break

    details = {
        "hotel_id": hotel_id,
        "hotel_name": hotel_name,
        "url": url,
        "collected_reviews": len(found),
        "api_total_index_observed_max": provider_count,
        "requests_made": requests_made,
        "pages_without_new_reviews": repeated_pages,
    }
    return list(found.values()), details


def write_report(path: Path, report: dict, rows: dict) -> None:
    report["last_updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = {
        "hotels_attempted": len(report["hotels"]) + len(report["errors"]),
        "hotels_succeeded": len(report["hotels"]),
        "reviews_saved": len(rows),
        "groups": dict(Counter(row["nps_group"] for row in rows.values())),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", default="data/agoda_hotel_urls.txt")
    parser.add_argument("--output", default="data/agoda_vi_reviews.csv")
    parser.add_argument("--report", default="data/agoda_collection_report.json")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--sorts", default="1,2,3,7", help="Comma-separated sort IDs")
    parser.add_argument("--resume", action="store_true", help="Append to existing CSV and report")
    parser.add_argument("--target-reviews", type=int, help="Stop after reaching this many rows")
    parser.add_argument("--max-hotels", type=int, help="Process at most this many new hotels")
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--id-map", help="CSV with url and hotel_id; avoids hotel-page requests")
    parser.add_argument("--browser-api", action="store_true", help="Fetch reviews in a Chrome page session")
    args = parser.parse_args()
    sorts = tuple(int(value) for value in args.sorts.split(","))
    if not sorts or any(value not in DEFAULT_SORTS for value in sorts):
        parser.error("--sorts must contain one or more of 1,2,3,7")

    urls = [
        line.strip() for line in Path(args.urls).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    id_map = {}
    if args.id_map:
        with Path(args.id_map).open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                slug = row["url"].rstrip("/").split("/hotel/")[0].split("/")[-1]
                id_map[row["url"]] = (int(row["hotel_id"]), slug.replace("-", " ").title())
    browser = None
    playwright = None
    if args.browser_api:
        if not args.id_map:
            parser.error("--browser-api requires --id-map")
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            executable_path=shutil.which("google-chrome") or shutil.which("chromium"),
            headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page(locale="vi-VN")
        landings = (
            "https://www.agoda.com/",
            "https://www.agoda.com/vi-vn/petro-house-hotel/hotel/vung-tau-vn.html",
        )
        for attempt in range(5):
            try:
                response = page.goto(landings[attempt % len(landings)], wait_until="domcontentloaded", timeout=20000)
                if response is not None and response.status < 400:
                    break
            except Exception:
                pass
            time.sleep(2 ** attempt)
        else:
            browser.close()
            playwright.stop()
            raise RuntimeError("Could not open an Agoda page in Chrome")
        session = BrowserReviewSession(page)
    else:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report)
    rows = {}
    if args.resume and output.exists():
        with output.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                rows[(str(row["hotel_id"]), str(row["review_id"]))] = row
    if args.resume and report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {
            "source": "Agoda",
            "language": "vi",
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "hotels": [],
            "errors": [],
        }
    seen_urls = {item["url"] for item in report["hotels"]}
    seen_hotel_ids = {item["hotel_id"] for item in report["hotels"]}
    new_hotels = 0
    consecutive_errors = 0
    cooldown_cycles = 0
    mode = "a" if args.resume and output.exists() else "w"
    with output.open(mode, encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        if mode == "w":
            writer.writeheader()
        for url in urls:
            if url in seen_urls:
                continue
            if args.id_map and url not in id_map:
                continue
            if args.id_map and id_map[url][0] in seen_hotel_ids:
                continue
            if args.target_reviews and len(rows) >= args.target_reviews:
                break
            if args.max_hotels and new_hotels >= args.max_hotels:
                break
            try:
                hotel_rows, details = collect_hotel(
                    session, url, args.page_size, args.max_pages, args.delay,
                    sorts, id_map.get(url)
                )
                fresh = []
                for row in hotel_rows:
                    key = (str(row["hotel_id"]), str(row["review_id"]))
                    if key not in rows:
                        rows[key] = row
                        fresh.append(row)
                writer.writerows(fresh)
                stream.flush()
                report["hotels"].append(details)
                report["errors"] = [error for error in report["errors"] if error["url"] != url]
                seen_urls.add(url)
                seen_hotel_ids.add(details["hotel_id"])
                consecutive_errors = 0
                cooldown_cycles = 0
            except (requests.RequestException, ValueError, KeyError) as exc:
                report["errors"] = [error for error in report["errors"] if error["url"] != url]
                report["errors"].append({"url": url, "error": str(exc)})
                print(f"ERROR {url}: {exc}", flush=True)
                consecutive_errors += 1
            new_hotels += 1
            write_report(report_path, report, rows)
            if new_hotels % args.progress_every == 0:
                print(f"New hotels: {new_hotels}; unique reviews: {len(rows)}", flush=True)
            if consecutive_errors >= 10:
                cooldown_cycles += 1
                if cooldown_cycles >= 4:
                    print("Stopped after four error cooldowns", flush=True)
                    break
                print(f"Ten consecutive errors; cooling down for 60 seconds ({cooldown_cycles}/3)", flush=True)
                time.sleep(60)
                consecutive_errors = 0
            time.sleep(args.delay)

    write_report(report_path, report, rows)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    if browser is not None:
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
