"""Prepare Vietnamese hotel reviews for an NPS-style topic-model experiment."""

import argparse
import csv
import io
import urllib.request
from pathlib import Path


SOURCE_URL = "https://zenodo.org/api/records/7967494/files/Reviews.csv/content"
OUTPUT_COLUMNS = ("source_id", "review", "rating_5", "review_date", "hotel_name", "group")


def rating_group(rating: int) -> str:
    if rating <= 3:
        return "Detractors"
    if rating == 4:
        return "Passives"
    return "Promoters"


def prepare(input_path: str | None, output_path: Path) -> dict[str, int]:
    source = open(input_path, "rb") if input_path else urllib.request.urlopen(SOURCE_URL)
    counts = {"Detractors": 0, "Passives": 0, "Promoters": 0}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with source, io.TextIOWrapper(source, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        with output_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for row in reader:
                if row["language"].strip().lower() != "vi":
                    continue
                review = row["text"].strip()
                if not review:
                    continue
                try:
                    rating = int(row["rating"])
                except (TypeError, ValueError):
                    continue
                if rating not in range(1, 6):
                    continue
                group = rating_group(rating)
                writer.writerow(
                    {
                        "source_id": row["id"],
                        "review": review,
                        "rating_5": rating,
                        "review_date": row["createdDate"],
                        "hotel_name": row["hotelName"],
                        "group": group,
                    }
                )
                counts[group] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="Local source CSV; otherwise download from Zenodo")
    parser.add_argument(
        "--output", default="data/tripadvisor_vi_reviews.csv", help="Prepared output CSV"
    )
    args = parser.parse_args()
    counts = prepare(args.input, Path(args.output))
    print(f"Prepared {sum(counts.values()):,} reviews: {counts}")
