# Vietnamese hotel reviews for the Le et al. replication

Source: An Dinh Van et al., [TripAdvisor Vietnam Hotel Reviews](https://doi.org/10.5281/zenodo.7967494), Zenodo (2023), CC BY 4.0. The source file is `Reviews.csv`.

Run `python3 scripts/prepare_tripadvisor_vi.py` from the repository root to regenerate `data/tripadvisor_vi_reviews.csv`. The script retains rows marked `language=vi` that have nonempty review text and a valid 1–5 star rating. It omits reviewer names and user IDs.

The output columns are `source_id`, `review`, `rating_5`, `review_date`, `hotel_name`, and `group`. For an **adaptation** of Le et al.'s rating split, ratings 1–3 map to Detractors, 4 to Passives, and 5 to Promoters. These labels are rating groups, not actual Net Promoter Score responses. The original Le et al. study used Agoda ratings on a 0–10 scale, so its thresholds and numerical results cannot be replicated exactly with this source.

The `language=vi` marker comes from the source dataset. Inspect a sample manually before modeling, and report the final row counts after any additional cleaning or deduplication.

## Fresh Agoda sample

With permission from Agoda, install `requests` and run these commands from the repository root. The collector can use direct HTTP; Chrome/Playwright is optional for sites where direct requests are unavailable.

```bash
python3 scripts/map_agoda_hotel_ids.py --urls data/agoda_hotel_urls_sitemap_all.txt --delay 4
python3 scripts/scrape_agoda_reviews.py --urls data/agoda_hotel_urls_sitemap_all.txt --id-map data/agoda_hotel_id_map.csv --resume --target-reviews 100000 --max-pages 2 --delay 1.5
```

`data/agoda_hotel_urls_sitemap_all.txt` contains 5,247 URLs from Agoda's Vietnamese review sitemap. The discovery script reads that sitemap and excludes the original hand-picked URLs in `data/agoda_hotel_urls.txt`. The map script resolves hotel IDs over HTTP by default (`--browser` switches to Chrome). Both scripts resume from their saved files, and the scraper saves `data/agoda_vi_reviews.csv` and `data/agoda_collection_report.json` after each hotel.

The collector requests the site's Vietnamese review filter, retains only Agoda's own reviews (`providerId=332`) whose source language is Vietnamese, and saves the original text where supplied. Reviewer names and user IDs are omitted. It deduplicates by hotel ID and review ID. Rating groups use Le et al.'s 0–10 thresholds: Detractors <=6.4, Passives 6.5–8.2, Promoters >=8.3.

Agoda's review endpoint sometimes repeats reviews across requested pages. The output is therefore a **sample of retrieved reviews**, not a complete export. The JSON report records retrieved counts and the largest `totalIndex` value observed from the API for each hotel; that value is not a verified total of retrievable Vietnamese text reviews. Do not present their difference as missing data in the original study; the collection dates and sampled hotels differ.

At the 2026-10-29 checkpoint, the local Agoda sample contains 100,090 unique Vietnamese text reviews from 2,213 hotels with review text (3,442 hotel pages succeeded; 5 page/API errors are recorded). The groups are 66,395 Promoters, 14,091 Passives, and 19,604 Detractors. The JSON report is authoritative if the CSV is updated later. The collector checkpoints each hotel and resumes with `--resume`; if Agoda returns repeated 502 responses, wait for the site to recover and rerun the command.
