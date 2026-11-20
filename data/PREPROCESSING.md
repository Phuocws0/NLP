# Tiền xử lý review Agoda theo Le et al.

Nguồn duy nhất: `data/agoda_vi_reviews.csv`  
Đầu ra duy nhất: `data/agoda_vi_reviews_preprocessed.csv`  
Notebook tự chứa toàn bộ mã và chạy từng bước: `notebooks/preprocess_agoda_reviews.ipynb`  
Phiên bản chạy dòng lệnh (tùy chọn): `scripts/preprocess_agoda_reviews.py`

Chạy lại:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-preprocess.txt
.venv/bin/python scripts/preprocess_agoda_reviews.py
```

Có thể chọn kernel `.venv` và chạy toàn bộ notebook từ trên xuống. Notebook không import script ngoài; cell 5 xử lý toàn bộ raw và cell 7 ghi CSV thật. Thư viện Underthesea tải mô hình nhận diện ngôn ngữ ở lần chạy đầu. Cả notebook và script dòng lệnh ghi qua file `.csv.tmp` rồi thay thế đúng CSV đầu ra hiện có; file tạm không phải dataset phụ.

## Những bước đã xử lý

1. Đọc CSV raw, kiểm tra cột bắt buộc, ID và rating 0–10; bỏ bản ghi rỗng hoặc khóa `(hotel_id, review_id)` trùng.
2. Làm sạch văn bản: Unicode NFC, HTML entity/thẻ, ký tự vô hình và khoảng trắng. Email, URL, chuỗi nghi là số điện thoại được thay bằng placeholder. Dấu tiếng Việt và từ phủ định ở văn bản sạch được giữ lại.
3. Kiểm tra **ngôn ngữ từ phần thân review**. FastText qua Underthesea xử lý câu đủ dài; luật cho câu ngắn/câu không dấu dựa trên dấu tiếng Việt và từ ngữ thường gặp. Bỏ bản ghi xác định là ngôn ngữ khác và trường hợp quá mơ hồ. `language_code=vi` của Agoda chỉ là điều kiện đầu vào, không thay cho kiểm tra này.
4. Mở rộng các viết tắt rõ nghĩa trong ngữ cảnh khách sạn như `ks` → `khách sạn`, `nv` → `nhân viên`, `ko` → `không`. Từ điển nằm trong script và có thể chỉnh khi rà soát mẫu thực tế.
5. Với câu gốc **hoàn toàn không dấu**, thử phục hồi các cụm thông dụng và một danh sách từ đơn đã rà soát. Từ đơn còn phải có bằng chứng từ chính raw: ít nhất 10 lần xuất hiện và một dạng có dấu chiếm ≥92%. Không tự gán dấu cho từ đa nghĩa hoặc từ tiếng Anh; `accent_status` ghi rõ câu đã có dấu, được thêm dấu một phần, hay vẫn chưa giải quyết. Đây là phục hồi dấu bảo thủ, chưa thể khẳng định đúng cho mọi câu.
6. Tách từ/gán POS tiếng Việt bằng Underthesea, chỉ giữ danh từ `N*` và tính từ `A*`, bỏ danh sách từ dừng và ký hiệu. Từ ghép viết bằng `_`, ví dụ `nhân_viên`. Dòng không còn token sau bước này bị loại. Chỉ **phần thân** tạo `lda_text`.
7. Chia NPS từ điểm: Detractors `<=6.4`, Passives `>6.4` đến `<=8.2`, Promoters `>8.2`. Giữ `split` cũ theo khách sạn để tương thích thí nghiệm supervised; **LDA theo bài báo không dùng split**.
8. Ghi đúng một CSV đầu ra, đọc lại để kiểm tra khóa duy nhất, `lda_text` không rỗng, nhãn ngôn ngữ tiếng Việt, tách biệt khách sạn giữa các split và SHA-256 raw không đổi.

## Kết quả lần chạy 2026-10-29

| Chỉ số | Kết quả |
| --- | ---: |
| Review raw | 100.090 |
| Review đầu ra | 87.837 |
| Bỏ vì ngôn ngữ khác/mơ hồ | 10.002 |
| Bỏ vì không còn danh từ/tính từ | 2.251 |
| Review còn lại được thêm dấu một phần | 505 |
| Review còn lại không dấu chưa phục hồi được | 60 |
| Promoters | 57.255 |
| Passives | 12.462 |
| Detractors | 18.120 |

SHA-256 raw trước và sau: `c0a184d01cacb88e49d3f9f2fbe420b06bb10453c98a4c18805c3b16da2aa79b`.

CSV đầu ra có 87.837 khóa review duy nhất, không có `lda_text` rỗng. Cả 87.837 dòng đều qua bước nhận diện tiếng Việt. Bộ lọc ngôn ngữ là tự động nên số dòng bị loại gồm cả 4.986 trường hợp ngắn hoặc mơ hồ; nên rà soát mẫu trước khi kết luận tất cả là ngôn ngữ khác.

## Cột quan trọng

- `review_text_clean`: nội dung sau làm sạch cơ bản, còn nguyên từ/cụm tiếng Việt.
- `review_text_normalized`: đã mở rộng viết tắt và thêm dấu có kiểm soát.
- `lda_text`: danh từ/tính từ đã tách từ, ngăn cách bằng khoảng trắng; dùng cột này cho LDA.
- `accent_status`, `language_rule`, `language_detected`: truy vết các quyết định tự động.
- `label`: nhóm NPS; chạy LDA riêng từng nhóm, thử K=1–6 và đánh giá coherence theo bài báo.
- `rating_10`, `nps_group`, `split`, ID, ngày và thông tin scrape: metadata, không phải token đầu vào LDA.

Quy trình bám theo các bước bài Le et al., nhưng bài báo không công bố đúng bộ công cụ, danh sách từ dừng hoặc từ điển viết tắt. Bản này là một triển khai có giải thích và có thể chạy lại; cần rà soát thủ công mẫu câu không dấu và kết quả POS trước khi diễn giải topic. Quy trình cào raw đã được ghi trong `scripts/collect_agoda_dataset.py`.
