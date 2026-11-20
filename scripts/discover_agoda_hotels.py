"""Find Vietnamese Agoda hotel URLs from Agoda's published review sitemaps."""

import argparse
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import requests


SITEMAP_INDEX = "https://www.agoda.com/vi-vn/sitemaps.xml"
CITY_WEIGHTS = {
    "ho-chi-minh-city-vn": 5,
    "hanoi-vn": 4,
    "da-nang-vn": 3,
    "nha-trang-vn": 2,
    "dalat-vn": 2,
    "vung-tau-vn": 1,
    "phu-quoc-island-vn": 1,
}


def locations(xml_bytes: bytes) -> list[str]:
    return [node.text for node in ET.fromstring(xml_bytes).iter() if node.tag.endswith("loc") and node.text]


def discover(limit: int, existing: set[str]) -> list[str]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    index = session.get(SITEMAP_INDEX, timeout=30)
    index.raise_for_status()
    review_sitemaps = [u for u in locations(index.content) if "pagetype_9_page" in u]
    by_city = defaultdict(list)
    for sitemap_url in review_sitemaps:
        response = session.get(sitemap_url, timeout=60)
        response.raise_for_status()
        for review_url in locations(response.content):
            match = re.search(r"/([^/]+)/reviews/([^/]+-vn\.html)$", review_url)
            if not match:
                continue
            city = match.group(2).removesuffix(".html")
            hotel_url = review_url.replace("/reviews/", "/hotel/")
            if hotel_url not in existing and hotel_url not in by_city[city]:
                by_city[city].append(hotel_url)

    weighted_cities = [city for city, weight in CITY_WEIGHTS.items() for _ in range(weight)]
    remaining_cities = sorted(set(by_city) - set(CITY_WEIGHTS))
    picked = []
    positions = defaultdict(int)
    for city_order in (weighted_cities, remaining_cities):
        while len(picked) < limit:
            before = len(picked)
            for city in city_order:
                position = positions[city]
                if position < len(by_city[city]):
                    picked.append(by_city[city][position])
                    positions[city] += 1
                    if len(picked) >= limit:
                        break
            if len(picked) == before:
                break
    return picked


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=900)
    parser.add_argument("--existing", default="data/agoda_hotel_urls.txt")
    parser.add_argument("--output", default="data/agoda_hotel_urls_sitemap.txt")
    args = parser.parse_args()
    existing = set(Path(args.existing).read_text(encoding="utf-8").splitlines())
    result = discover(args.limit, existing)
    Path(args.output).write_text("\n".join(result) + "\n", encoding="utf-8")
    print(f"Discovered {len(result)} additional hotel URLs")
