# M-ASWING — ASWING 非線性氣動彈性 End-to-End runner

## 前置條件

Apple Silicon Mac mini 上 ASWING 二進位已安裝並放在 PATH（`brew install`
目前沒有，需要從原始碼 compile，文件留待使用者）。

## 背景

ASWING（Drela）是非線性大位移氣動彈性 solver，在高展弦比 HPA 特別好用 —
我們的 `tip_deflection_m ≈ 2.5 m / 16.5 m half_span ≈ 15%`，已經不是線性
小變形假設適用的範圍了。這讓我們對 OpenMDAO 的「線性梁 + VLM」的 val_weight
沒有絕對信心。

目標：用 ASWING 獨立跑一次配平，把翼尖 uz / 扭轉與 MDO 結果比對，差距
> 10% 時印 WARN（不改 optimizer）。

## 目標

1. 新增 `src/hpa_mdo/hifi/aswing_runner.py`：
   - `find_aswing(cfg) -> Optional[Path]` — 仿 `find_gmsh`。
   - `build_aswing_asw(cfg, ac, result, out_asw_path: Path) -> Path`：
     - 從 `cfg.wing.*`、`result.main_r_seg_mm` / `main_t_seg_mm` 推算每段
       EI / GJ / m’（線密度），寫 ASWING 標準 `.asw` 檔。
     - 翼型用 `cfg.io.airfoil_dir` 找，若無 fallback 到 NACA 2412
       （印 WARN）。
     - Boundary：root clamp，升力鋼索用 ASWING 的 `ROD` 元素模擬。
   - `run_aswing(asw_path, cfg, *, timeout_s=600) -> dict`：
     - `subprocess.run([aswing_bin], cwd=..., input=b"load\nexec\nplot\n...\nquit\n")`
       以 batch commands 驅動。失敗不 raise，回 `{"error": ...}`。
2. 新增 `scripts/hifi_validate_aswing.py`：
   - `--config configs/... --mdo-tip-defl <float> --mdo-tip-twist-deg <float>`
   - 執行：`build_aswing_asw` → `run_aswing` → parse output → 比對。
   - 輸出 `output/<stem>/hifi/aswing_report.md`：ASWING uz / θy、MDO 值、diff%、
     PASS / WARN。
3. `configs/blackcat_004.yaml` 加 `hi_fidelity.aswing` 區段：
   ```yaml
   hi_fidelity:
     aswing:
       enabled: false
       binary: null
       n_panels: 40
       vinf_mps: null   # null = 繼承 cfg.flight.velocity
   ```

## 驗收標準

- Mac mini 上 ASWING 裝好後可以跑完並產生 aswing_report.md。
- `tests/test_hifi_aswing_runner.py` 在 ASWING 未安裝時跳過 integration，
  但測試 `build_aswing_asw` 的字串 golden。
- `val_weight: 11.95...` 不變。

## 不要做的事

- 不要把 ASWING 結果反饋回 OpenMDAO objective / constraint。只印 WARN。
- 不要假設 ASWING 輸出格式穩定；用 regex + defensive parse，失敗回 error dict
  不 raise。
- 不要把 `.asw` 當純文字模板塞進 Python 字串；用 Jinja2 range over segments
  保持可讀性。

## 建議 commit 訊息

```
feat(hifi): M-ASWING ASWING 非線性氣動彈性驗證 runner

hpa_mdo.hifi.aswing_runner 從 MDO result 拼 .asw、batch 驅動 ASWING，
parse 翼尖 uz/θy 與 MDO 值比對。scripts/hifi_validate_aswing.py 產出
aswing_report.md，> 10% 差距 WARN 不 raise。OpenMDAO 迴圈不受影響。

Co-Authored-By: Codex 5.4 (Extreme High)
```
