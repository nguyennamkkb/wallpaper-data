# AGENTS.md — wallpaper-data

Repo static (Cloudflare Pages) chứa sticker + wallpaper dạng WebP và JSON dữ liệu.
- `image/st-*/…`, `image/wp-*/…`, `image/other/…` — ảnh WebP (best + `_thumb`)
- `data/sticker.json`, `data/wallpaper.json` — dữ liệu trỏ ảnh
- `index.html` — gallery tĩnh

## Quy trình tạo sticker mới

Dùng 2 skill `app-asset-generator` + `generating-oneshot-image-prompts` và script `gen_images.py`.

### Batch 10 sticker / pack — `gen_stickers_all.py`

`gen_stickers_all.py` chứa config toàn bộ pack (`ST-06…ST-44`: style + key màu + 10 chủ thể) và
tự gen → cắt nền → despill → resize 480px cho Figma. Chạy theo nhóm pack, resumable:

```bash
python3 gen_stickers_all.py ST-31-places ST-32-travel ST-33-vietnam ST-34-food ST-35-cafe
```

- **Ảnh tham chiếu (`--ref`)**: mặc định BẬT — mỗi pack lấy `image/<pack>/01..04.webp` (4 ảnh gốc,
  inline PNG base64) làm reference để giữ đúng chất liệu/màu/độ bóng của bộ gốc. Tắt: `STICKER_REFS=0`.
- **Despill**: `despill_edges.py` khử viền xanh chroma trên dải pixel bán trong suốt; tự bỏ qua ảnh có
  chủ thể xanh thật (lá, ếch, graffiti). Audit riêng: `python3 despill_edges.py --report`.
- Output: `out/sticker-new/<pack>/01..10.png` (full-res) và `out/sticker-figma/<pack>/06..15.png` (480px).

### Tạo lẻ từng ảnh

1. **Prompt** (theo `generating-oneshot-image-prompts`): mô tả 1 chủ thể, style "soft 3D clay kawaii"
   (khớp bộ ST hiện có), câu khẳng định (không dùng từ phủ định trong prompt chính), nền chromakey:
   - chủ thể không xanh → key **xanh lá `#00FF00`**
   - chủ thể xanh (lá, cây) → key **hồng cánh sen `#FF00FF`**
   - **Không** ghi "transparent". Kết thúc prompt bằng: nền phẳng đồng nhất `#00FF00` phủ kín khung,
     1 chủ thể ở giữa, chừa lề ~12% mỗi cạnh, cạnh sắc nét.
2. **Generate** qua gateway muse2api:
   ```bash
   python3 gen_images.py "<prompt>" --sizes 1:1 --key dummy --out out/sticker-test
   ```
   (gateway chạy ở `http://127.0.0.1:18610`, model `muse-image`)
3. **Cắt nền**:
   ```bash
   python3 .claude/skills/app-asset-generator/scripts/remove_bg.py <raw.webp> -o out/sticker-test/<name>.png
   ```
   Kiểm tra JSON report (`pass: true`, `fringe_pct`/`key_left_pct` ≈ 0) và xem `_preview.png`.
4. **Dọn dẹp — CHỈ GIỮ ẢNH CUỐI**: sau khi cắt nền xong, **xoá mọi file trung gian**, chỉ giữ lại
   ảnh PNG trong suốt cuối cùng (`<name>.png`). Xoá:
   - ảnh gốc vừa generate (`*.webp`)
   - `<name>_original.png`
   - `<name>_preview.png`
   - `report-*.json`

   ```bash
   find out/sticker-test -type f ! -name '<name>.png' -delete
   ```

Ảnh cuối = PNG trong suốt, đã trim, dùng trực tiếp (đưa vào Figma / chuyển WebP cho repo).
