"""Tiền xử lý Agoda theo pipeline NPS + chủ đề của Le et al.

Chỉ đọc data/agoda_vi_reviews.csv và ghi đè một đầu ra
data/agoda_vi_reviews_preprocessed.csv. Đây là phiên bản chạy dòng lệnh;
notebook chứa đầy đủ mã xử lý tương ứng và có thể chạy độc lập.
"""

from __future__ import annotations

import csv
import hashlib
import html
import os
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from underthesea import lang_detect, pos_tag


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data/agoda_vi_reviews.csv"
OUTPUT_PATH = ROOT / "data/agoda_vi_reviews_preprocessed.csv"
OUTPUT_COLUMNS = [
    "hotel_id", "review_id", "review_date", "rating_10", "nps_group", "label",
    "split", "language_code", "language_detected", "language_rule",
    "first_seen_sort", "first_seen_page", "review_title_clean",
    "review_text_clean", "review_text_normalized", "accent_status", "model_text",
    "lda_text", "lda_token_count",
]
REQUIRED_COLUMNS = {
    "hotel_id", "review_id", "review_date", "rating_10", "review_title",
    "review_text", "language_code", "nps_group", "first_seen_sort", "first_seen_page",
}

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>]+", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?84|0)(?:[ .()-]*\d){8,10}(?!\w)")
HTML_TAG_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
INVISIBLE_RE = re.compile("[\u200b\ufeff]")
WORD_RE = re.compile(r"[A-Za-zÀ-ỹĐđ]+", re.I)
ACCENT_RE = re.compile(
    "[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩ"
    "òóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I
)

# Chỉ thay những dạng ít nhập nhằng trong ngữ cảnh review khách sạn.
ABBREVIATIONS = {
    "ks": "khách sạn", "k.s": "khách sạn", "nv": "nhân viên",
    "ko": "không", "k0": "không",
    "dc": "được", "đc": "được", "vsinh": "vệ sinh",
}

# Các cụm không dấu phổ biến, gồm một số cụm mà tần suất đơn từ dễ đoán sai.
ACCENT_PHRASES = {
    "khach san": "khách sạn", "nhan vien": "nhân viên",
    "than thien": "thân thiện", "sach se": "sạch sẽ",
    "gia re": "giá rẻ", "phong oc": "phòng ốc",
    "rat tot": "rất tốt", "rat dep": "rất đẹp",
    "tuyet voi": "tuyệt vời", "khong sach": "không sạch",
    "khong tot": "không tốt", "khong dep": "không đẹp",
    "chinh sach": "chính sách", "hai long": "hài lòng",
    "an sang": "ăn sáng", "nhiet tinh": "nhiệt tình",
    "tien nghi": "tiện nghi", "hop li": "hợp lí",
    "hop ly": "hợp lý", "rong rai": "rộng rãi",
    "gan bien": "gần biển", "le tan": "lễ tân",
    "lich su": "lịch sự", "chat luong": "chất lượng",
    "do an": "đồ ăn", "nuoc nong": "nước nóng",
    "ho boi": "hồ bơi", "gia ca": "giá cả",
    "phong sach": "phòng sạch", "sach dep": "sạch đẹp",
    "phong cach": "phong cách",
}

# Dù corpus thiên về review khách sạn, từ phổ biến vẫn có thể đa nghĩa:
# sach = sạch/sách, quen = quen/quên, ga = ga/gà, toilet là từ tiếng Anh.
# Chỉ cho phép từ đơn đã được rà soát và có bằng chứng tần suất từ corpus.
SAFE_ACCENT_KEYS = {
    "tot", "dep", "phong", "sach", "rat", "khong", "duoc",
    "nguoi", "khach",
}

# Bằng chứng nhận biết tiếng Việt không dấu; không tính "hotel", "room".
VN_ASCII_CUES = {
    "khach", "san", "phong", "sach", "dep", "nhan", "vien", "than",
    "thien", "rat", "tot", "tuyet", "voi", "khong", "ko", "gia", "re",
    "ngon", "nho", "lon", "thoai", "mai", "nghi", "duong", "gan",
    "bien", "nhiet", "tinh", "luon", "duoc", "minh", "toi", "cua",
    "cho", "nua", "khac", "o", "la", "va", "nhung", "khau",
}
EN_CUES = {
    "the", "and", "was", "were", "with", "this", "that", "very", "good",
    "nice", "great", "excellent", "staff", "staffs", "room", "rooms",
    "hotel", "hotels", "stay", "stayed", "breakfast", "clean", "service",
    "location", "friendly", "would", "again", "not", "for", "from",
}

# Bỏ từ dừng sau POS; giữ các từ chủ đề như phòng, khách sạn, sạch, giá.
STOPWORDS = {
    "mình", "tôi", "chúng_tôi", "chúng_mình", "bạn", "anh", "chị", "em",
    "họ", "nó", "mọi_người", "người_ta", "lần", "lúc", "hôm", "ngày",
    "đây", "đó", "này", "kia", "cái", "con", "việc", "điều", "thứ",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: str, counts: Counter | None = None) -> str:
    """NFC, HTML, khoảng trắng và ẩn chuỗi liên hệ; không xóa dấu tiếng Việt."""
    text = unicodedata.normalize("NFC", html.unescape(value or ""))
    for pattern, replacement, name in (
        (HTML_TAG_RE, " ", "html_tags"),
        (INVISIBLE_RE, "", "invisible_chars"),
        (EMAIL_RE, "[EMAIL]", "emails"),
        (URL_RE, "[URL]", "urls"),
        (PHONE_RE, "[PHONE]", "phone_candidates"),
    ):
        text, n = pattern.subn(replacement, text)
        if counts is not None:
            counts[name] += n
    text = "".join(
        " " if char.isspace() else "" if unicodedata.category(char) == "Cc" else char
        for char in text
    )
    return " ".join(text.split())


def fold_ascii(token: str) -> str:
    token = token.lower().replace("đ", "d")
    return "".join(
        char for char in unicodedata.normalize("NFD", token)
        if unicodedata.category(char) != "Mn"
    )


def build_accent_lexicon(raw_rows: list[dict]) -> dict[str, str]:
    """Học dạng có dấu từ chính phần review đã có dấu; chọn đơn nghĩa rõ ràng."""
    forms: dict[str, Counter] = defaultdict(Counter)
    for row in raw_rows:
        body = clean_text(row.get("review_text", ""))
        if not ACCENT_RE.search(body):
            continue
        for token in WORD_RE.findall(body.lower()):
            if ACCENT_RE.search(token):
                forms[fold_ascii(token)][token] += 1
    lexicon = {}
    for plain, candidates in forms.items():
        accented, frequency = candidates.most_common(1)[0]
        total = sum(candidates.values())
        if (plain in SAFE_ACCENT_KEYS and frequency >= 10
                and frequency / total >= 0.92):
            lexicon[plain] = accented
    return lexicon


def normalize_abbreviations(text: str) -> tuple[str, int]:
    text = text.lower()
    changes = 0
    for short, expanded in ABBREVIATIONS.items():
        text, n = re.subn(r"(?<!\w)" + re.escape(short) + r"(?!\w)", expanded, text)
        changes += n
    return text, changes


def classify_language(text: str) -> tuple[str, str]:
    """Kết hợp FastText và luật cho review ngắn/không dấu.

    Trả (ngôn ngữ xác định, quy tắc). `unknown` bị loại khỏi CSV cho LDA.
    """
    words = [fold_ascii(word) for word in WORD_RE.findall(text)]
    if not words:
        return "unknown", "no_words"
    accent = bool(ACCENT_RE.search(text))
    vn_hits = sum(word in VN_ASCII_CUES for word in words)
    en_hits = sum(word in EN_CUES for word in words)
    if len(words) < 5:
        if accent:
            return "vi", "short_with_accent"
        if vn_hits and not en_hits:
            return "vi", "short_vietnamese_cue"
        if en_hits:
            return "en", "short_english_cue"
        return "unknown", "short_ambiguous"
    model_lang = lang_detect(text)
    if model_lang == "vi":
        return "vi", "fasttext"
    if vn_hits >= 2 and vn_hits > en_hits and (not accent or vn_hits >= en_hits + 2):
        return "vi", "vietnamese_cues"
    return model_lang or "unknown", "fasttext_other"


def restore_accents(
    text: str, lexicon: dict[str, str], original_has_accents: bool
) -> tuple[str, str]:
    """Chỉ thêm dấu cho văn bản hoàn toàn không dấu, với từ/cụm đủ tin cậy."""
    if original_has_accents:
        return text, "already_accented"
    before = text
    for plain, accented in ACCENT_PHRASES.items():
        text = re.sub(r"(?<!\w)" + re.escape(plain) + r"(?!\w)", accented, text)
    text = re.sub(
        r"\b[a-z]+\b",
        lambda match: lexicon.get(match.group(), match.group()),
        text,
    )
    # "phong cách" có âm tiết đầu vốn không mang dấu.
    text = re.sub(r"\bphòng cách\b", "phong cách", text)
    return text, "partially_restored" if text != before else "unresolved_unaccented"


def topic_tokens(text: str) -> list[str]:
    """POS tiếng Việt; chỉ lấy danh từ (N*) và tính từ (A*), bỏ từ dừng."""
    tokens = []
    for word, tag in pos_tag(text):
        term = word.strip().lower().replace(" ", "_")
        if (tag.startswith("N") or tag.startswith("A")) and term not in STOPWORDS:
            if WORD_RE.search(term) and not term.startswith("["):
                tokens.append(term)
    return tokens


def label_from_rating(rating: float) -> str:
    if rating <= 6.4:
        return "Detractors"
    if rating <= 8.2:
        return "Passives"
    return "Promoters"


def read_raw() -> tuple[list[dict], list[str]]:
    with RAW_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        missing = REQUIRED_COLUMNS - set(columns)
        if missing:
            raise ValueError(f"Thiếu cột: {sorted(missing)}")
        return list(reader), columns


def process_rows(raw_rows: list[dict], lexicon: dict[str, str]) -> tuple[list[dict], Counter]:
    output = []
    audit = Counter()
    seen = set()
    text_cache = {}
    for index, row in enumerate(raw_rows, 1):
        hotel_id = (row.get("hotel_id") or "").strip()
        review_id = (row.get("review_id") or "").strip()
        key = (hotel_id, review_id)
        if not all(key) or key in seen:
            audit["dropped_missing_or_duplicate_id"] += 1
            continue
        seen.add(key)
        if (row.get("language_code") or "").strip() != "vi":
            audit["dropped_source_language"] += 1
            continue
        try:
            rating = float(row["rating_10"])
        except (ValueError, TypeError):
            audit["dropped_invalid_rating"] += 1
            continue
        if not 0 <= rating <= 10:
            audit["dropped_invalid_rating"] += 1
            continue
        title = clean_text(row.get("review_title", ""), audit)
        body = clean_text(row.get("review_text", ""), audit)
        if not body:
            audit["dropped_empty_body"] += 1
            continue
        # Phần thân review quyết định ngôn ngữ và từ chủ đề; tiêu đề chỉ lưu tham chiếu.
        detected, rule = classify_language(body)
        if detected != "vi":
            audit[f"dropped_language_{detected}"] += 1
            continue
        normalized, n_abbr = normalize_abbreviations(body)
        audit["abbreviations_expanded"] += n_abbr
        normalized, accent_status = restore_accents(
            normalized, lexicon, bool(ACCENT_RE.search(body))
        )
        if accent_status == "partially_restored":
            audit["reviews_partially_restored"] += 1
        if accent_status == "unresolved_unaccented":
            audit["reviews_unresolved_unaccented"] += 1
        if normalized not in text_cache:
            text_cache[normalized] = topic_tokens(normalized)
        tokens = text_cache[normalized]
        if not tokens:
            audit["dropped_no_topic_tokens"] += 1
            continue
        label = label_from_rating(rating)
        if label != (row.get("nps_group") or "").strip():
            audit["source_label_mismatch"] += 1
        output.append({
            "hotel_id": hotel_id, "review_id": review_id,
            "review_date": (row.get("review_date") or "").strip(),
            "rating_10": (row.get("rating_10") or "").strip(),
            "nps_group": (row.get("nps_group") or "").strip(),
            "label": label, "split": "", "language_code": "vi",
            "language_detected": detected, "language_rule": rule,
            "first_seen_sort": (row.get("first_seen_sort") or "").strip(),
            "first_seen_page": (row.get("first_seen_page") or "").strip(),
            "review_title_clean": title, "review_text_clean": body,
            "review_text_normalized": normalized, "accent_status": accent_status,
            "model_text": f"{title}. {body}" if title else body,
            "lda_text": " ".join(tokens), "lda_token_count": len(tokens),
        })
        if index % 10000 == 0:
            print(f"Đã xử lý {index:,}/{len(raw_rows):,} review gốc", flush=True)
    audit["retained"] = len(output)
    return output, audit


def assign_splits(rows: list[dict]) -> Counter:
    # Giữ cách chia theo khách sạn cho supervised; LDA theo bài không dùng split.
    hotel_ids = sorted({row["hotel_id"] for row in rows})
    random.Random(42).shuffle(hotel_ids)
    train_end = int(len(hotel_ids) * 0.80)
    val_end = int(len(hotel_ids) * 0.90)
    mapping = {
        hotel_id: "train" if i < train_end else "validation" if i < val_end else "test"
        for i, hotel_id in enumerate(hotel_ids)
    }
    for row in rows:
        row["split"] = mapping[row["hotel_id"]]
    return Counter(row["split"] for row in rows)


def write_and_verify(rows: list[dict], raw_hash_before: str) -> tuple[str, Counter]:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_PATH.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, OUTPUT_PATH)
    keys = set()
    hotels = {}
    labels = Counter()
    with OUTPUT_PATH.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["hotel_id"], row["review_id"])
            if key in keys or not row["lda_text"] or row["language_detected"] != "vi":
                raise RuntimeError("CSV đầu ra có khóa trùng, văn bản LDA rỗng hoặc sai ngôn ngữ")
            keys.add(key)
            if row["hotel_id"] in hotels and hotels[row["hotel_id"]] != row["split"]:
                raise RuntimeError("Một khách sạn xuất hiện ở nhiều tập")
            hotels[row["hotel_id"]] = row["split"]
            labels[row["label"]] += 1
    raw_hash_after = sha256(RAW_PATH)
    if raw_hash_before != raw_hash_after or len(keys) != len(rows):
        raise RuntimeError("Dữ liệu gốc thay đổi hoặc số dòng đầu ra không khớp")
    return raw_hash_after, labels


def main() -> None:
    raw_hash_before = sha256(RAW_PATH)
    raw_rows, columns = read_raw()
    print("Nguồn:", RAW_PATH)
    print("Cột raw:", columns)
    print("Số dòng raw:", len(raw_rows))
    print("SHA-256 raw:", raw_hash_before)
    lexicon = build_accent_lexicon(raw_rows)
    print("Số mục từ thêm dấu độ tin cậy cao:", len(lexicon))
    rows, audit = process_rows(raw_rows, lexicon)
    splits = assign_splits(rows)
    raw_hash_after, labels = write_and_verify(rows, raw_hash_before)
    print("Đã lưu:", OUTPUT_PATH)
    print("Kiểm toán:", dict(audit))
    print("Nhãn:", dict(labels))
    print("Split:", dict(splits))
    print("SHA-256 raw không đổi:", raw_hash_after)


if __name__ == "__main__":
    main()
