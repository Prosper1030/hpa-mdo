# F-Layup — 把離散疊層整合進主管線（師傅看得懂的 layup table）

## 背景

M11（11a-11g）已經把 CLT 引擎、PlyStack 列舉、snap-to-nearest-stack、
Tsai-Wu 失效、layup formatter **全部實作完**，都在：

- `src/hpa_mdo/structure/laminate.py`
- `src/hpa_mdo/utils/discrete_layup.py`（`discretize_layup_per_segment`、
  `format_stack_notation`、`build_segment_layup_results`、`format_layup_report`）
- `scripts/discrete_layup_postprocess.py`（吃 inverse-design summary JSON）

但 `examples/blackcat_004_optimize.py` 主管線**預設只跑連續壁厚**；
`optimization_summary.txt` 只印一行 `ply-step margin=+1.000`，**看不到**
每段幾層 0° / 幾層 ±45° / 幾層 90°，也沒有 `[0/+45/-45/90]s` 堆疊表。
現場打樣的碳纖維師傅看 summary 不知道要鋪什麼。

本任務把 M11 的輸出接進主管線，參考已有的 `--discrete-od` 模式，加一個
`--discrete-layup` 旗標：跑完連續最佳化 → snap 到最近離散 layup →
重新 analyze 驗證約束 → 在 summary.txt 印每段疊層 + Tsai-Wu margin。

## 目標

### 1. `examples/blackcat_004_optimize.py`

加 argparse 旗標（照 `--discrete-od` 的樣式）：
```python
parser.add_argument(
    "--discrete-layup", action="store_true", default=False,
    help="Post-process continuous wall-thickness design by snapping to the "
         "nearest integer ply stack (0/±45/90), re-evaluating Tsai-Wu FI."
)
parser.add_argument(
    "--ply-material", default=None,
    help="Override ply material key in data/materials.yaml (default: from cfg)."
)
```

實作區塊（放在 `--discrete-od` 後面、Step 7 視覺化之前）：
```python
if args.discrete_layup and result.success:
    from hpa_mdo.utils.discrete_layup import (
        enumerate_valid_stacks, build_segment_layup_results,
        summarize_layup_results, format_layup_report,
    )
    # 用 cfg.main_spar.clt_design 的 min_plies_0/45/90 限制列舉 stack
    stacks = enumerate_valid_stacks(cfg.main_spar.clt_design)
    layup_main = build_segment_layup_results(
        seg_t_mm=result.main_t_seg_mm,
        seg_r_mm=result.main_r_seg_mm,
        stacks=stacks,
        ply_material=mat_db.get(args.ply_material or cfg.main_spar.ply_material),
        load_envelope=result.segment_load_envelopes_main,  # M11 已有介面
    )
    # rear_spar 同理
    layup_rear = build_segment_layup_results(...)
    result.layup_main = layup_main
    result.layup_rear = layup_rear
    # 重新跑一次 analyze 驗證離散化後約束仍 pass
    result = opt.analyze(...)  # 用 layup 對應的等效厚度
    result.message = "Discrete layup design re-verified"
```

### 2. 在 `optimization_summary.txt` 加疊層區塊

擴充 `src/hpa_mdo/utils/visualization.py` 的
`write_optimization_summary()` / `print_optimization_summary()`：
當 `result.layup_main` 存在時加這段：
```
----------------------------------------------------------------
  DISCRETE LAYUP SCHEDULE
----------------------------------------------------------------
  Ply material: CFRP_UHM_UD, t_ply = 0.125 mm
  Main spar:
    Seg 1 (0.00-1.50 m):  [0/+45/-45/90]2s   n=16, t=2.00 mm, TW_SR=1.82 (SAFE)
    Seg 2 (1.50-4.50 m):  [0/+45/-45/90]s    n= 8, t=1.00 mm, TW_SR=1.35 (SAFE)
    Seg 3 (4.50-7.50 m):  [0/+45/-45]s       n= 6, t=0.75 mm, TW_SR=1.12 (SAFE)
    ...
  Rear spar:
    Seg 1: ...
  Total stack mass penalty vs continuous: +0.23 kg (+1.9%)
```
格式用現有 `format_stack_notation()` + `format_layup_report()` 組合，
不要自己重新發明。

### 3. 與 `--discrete-od` 互容

兩個旗標可以同時給：先做 `--discrete-od` 把 OD snap 到商規，再做
`--discrete-layup` 把 t 對應到整數 stack。order 要固定：**OD 先、layup 後**，
因為 stack 的厚度是 ply 數 × t_ply，與 OD 無關，但 Tsai-Wu 檢查依賴最終 OD。

### 4. 測試

新增 `tests/test_discrete_layup_main_pipeline.py`：
- smoke test: `main(["--discrete-layup"])` 能跑完回 float，不 raise。
- 驗證 `result.layup_main` 每段 `TsaiWuSummary.strength_ratio >= 1.0`。
- 驗證 summary.txt 裡出現 `DISCRETE LAYUP SCHEDULE` 字串。

## 驗收標準

- `python examples/blackcat_004_optimize.py`（不加旗標）→ `val_weight: 11.95...` 不變。
- `python examples/blackcat_004_optimize.py --discrete-layup` →
  - summary.txt 有完整疊層表，師傅看得懂。
  - `val_weight` 比 baseline 略高（離散懲罰 ~1-3%），PR description 記錄確切數字。
- `python examples/blackcat_004_optimize.py --discrete-od --discrete-layup` →
  兩個 post-process 都跑、順序正確、summary.txt 同時列離散 OD 與離散 layup。

## 不要做的事

- **不要**改 `laminate.py` / `discrete_layup.py` 的核心實作。介面已經完整，
  這個任務純粹是 wiring。
- **不要**把離散 layup 放進最佳化內層當設計變數。它是 post-process。
- **不要**在 summary.txt 裡硬編疊層表格欄寬；用 `format_layup_report()` 吐。
- **不要**忽略 `cfg.main_spar.clt_design` 沒設定的情況。若缺：印 WARN、
  跳過 `--discrete-layup` 不 raise，讓主流程仍能 `val_weight` 正常收尾。

## 建議 commit 訊息

```
feat(structure): F-Layup 離散疊層接進主管線 + summary 印疊層表

examples/blackcat_004_optimize.py 加 --discrete-layup 旗標；snap 連續
壁厚到最近 integer ply stack，重新 analyze 驗證 Tsai-Wu。summary.txt
新增 DISCRETE LAYUP SCHEDULE 區塊列每段 [0/±45/90]s 堆疊與 TW strength
ratio，現場打樣用。與 --discrete-od 互容（OD 先、layup 後）。
baseline val_weight: 11.95 不變；--discrete-layup 後 val_weight: ?.??。

Co-Authored-By: Codex 5.4 (Extreme High)
```
