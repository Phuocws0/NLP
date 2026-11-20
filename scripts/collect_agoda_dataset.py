"""Tái hiện quy trình cào bộ review Agoda tiếng Việt gốc.

Chạy từ thư mục bất kỳ trong dự án::

    python3 -m pip install requests
    python3 scripts/collect_agoda_dataset.py --target-reviews 100000

Chỉ chạy khi đã được Agoda cho phép. Script này điều phối ba bước đã dùng để
tạo data/agoda_vi_reviews.csv:

1. Đọc sitemap review tiếng Việt để lấy URL khách sạn (nếu chưa có danh sách).
2. Mở từng trang khách sạn, lấy hotel_id và lưu map để có thể chạy tiếp.
3. Gọi ReviewComments với providerId=332, bộ lọc ngôn ngữ tiếng Việt (24),
   kiểm tra translateSource='vi', rồi lưu văn bản gốc, điểm 0–10 và ngày.

Collector lấy tối đa hai trang cho mỗi thứ tự: mới nhất (1), điểm cao (2),
điểm thấp (3), hữu ích (7), cỡ trang 50. Các thứ tự có thể trả lại cùng review;
collector khử trùng theo (hotel_id, review_id), ghi CSV và báo cáo sau từng
khách sạn, retry và nghỉ khi gặp nhiều lỗi 502. Đây là mẫu review truy xuất
được, không phải bản xuất đầy đủ toàn bộ review của Agoda.

Snapshot ngày 2026-10-29 được tích lũy qua nhiều lượt --resume. Các lượt
trước có dùng --max-pages=1; lượt mở rộng đến 100.000 review dùng
--max-pages=2 và --delay=1.5. Hotel_id cũng được ánh xạ theo từng đợt.
Khi Agoda trả 502 liên
tiếp, collector nghỉ rồi tiếp tục từ CSV/báo cáo đã lưu. Cuối cùng có 100.090
review duy nhất, 3.442 trang khách sạn thành công và 5 URL lỗi. Lệnh mặc định
bên dưới dùng cấu hình cuối để tạo lại quy trình; nội dung chính xác của API
có thể thay đổi theo thời gian.

Mã HTTP chi tiết nằm trong discover_agoda_hotels.py, map_agoda_hotel_ids.py và
scrape_agoda_reviews.py cùng thư mục. File này cung cấp một lệnh chạy lại đầy
đủ với cùng bộ lọc, kiểu truy vấn và cơ chế lưu tiếp.
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
URLS = ROOT / "data/agoda_hotel_urls_sitemap_all.txt"
ID_MAP = ROOT / "data/agoda_hotel_id_map.csv"
RAW = ROOT / "data/agoda_vi_reviews.csv"


def raw_row_count() -> int:
    """Đếm record CSV đúng cách vì review có thể chứa xuống dòng."""
    if not RAW.exists():
        return 0
    with RAW.open(encoding="utf-8", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def run(script: str, *arguments: str) -> None:
    """Chạy một công đoạn và dừng ngay nếu công đoạn đó thất bại."""
    command = [sys.executable, str(ROOT / "scripts" / script), *arguments]
    print("Đang chạy:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-reviews", type=int, default=100000)
    parser.add_argument(
        "--skip-mapping", action="store_true",
        help="Dùng hotel_id map đã có, hữu ích khi chỉ cần chạy tiếp collector",
    )
    args = parser.parse_args()
    if args.target_reviews < 1:
        parser.error("--target-reviews phải lớn hơn 0")

    current = raw_row_count()
    if current >= args.target_reviews:
        print(f"Đã có {current} review; đạt mục tiêu {args.target_reviews}.")
        return

    # 10.000 vượt số URL đang có trong sitemap, nên lấy toàn bộ URL phù hợp.
    if not URLS.exists():
        run(
            "discover_agoda_hotels.py", "--limit", "10000",
            "--output", str(URLS),
        )

    # Map tự resume theo URL cuối đã lưu. Giữ nhịp 4 giây để hạn chế 502.
    if not args.skip_mapping:
        run("map_agoda_hotel_ids.py", "--urls", str(URLS),
            "--output", str(ID_MAP), "--delay", "4", "--progress-every", "100")
    if not ID_MAP.exists():
        parser.error("Chưa có hotel_id map; hãy chạy lại không dùng --skip-mapping")

    # --resume không ghi đè CSV hiện có; collector dừng sau khách sạn làm
    # tổng số review đạt hoặc vượt mục tiêu.
    run(
        "scrape_agoda_reviews.py", "--urls", str(URLS),
        "--id-map", str(ID_MAP), "--resume",
        "--target-reviews", str(args.target_reviews),
        "--max-pages", "2", "--delay", "1.5", "--progress-every", "50",
    )
    print(f"Hoàn tất. CSV gốc hiện có {raw_row_count()} review.")


if __name__ == "__main__":
    main()
