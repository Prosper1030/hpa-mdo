# Track V — AVL Spanwise Ownership Realignment

> 目標：把 `candidate_avl_spanwise` 收回成你原本要的版本。  
> 你不是要一條全新的奇怪流程；你要的是 **保留舊 AVL-first outer-loop 節奏，只補上 candidate-owned AVL spanwise lift distribution 給結構吃**。

## 為什麼現在要做這包

Track U 已經證明：

- AVL `.fs` strip-force output 可以被解析成展向載荷
- 這份載荷也確實可以被接進 `SpanwiseLoad` / `LoadMapper` / inverse design

但現在的第一版實作有 drift：

- 不只加了 spanwise lift distribution
- 還順手改了 load-state / AoA ownership
- 還讓 smoke 主要靠 `--skip-aero-gates` 才顯得合理
- 還把 recovery 節奏和舊 AVL-first 流程拉開

這不是使用者要的版本。

## 你要守住的設計原則

你這次不是在重新設計主線。

你要守住的是：

1. `multiplier / dihedral` 改 shape 的方法保持原本 AVL-first 節奏
2. trim / stability / beta / aero gate 保持原本 outer-loop contract
3. ground-clearance recovery 不要因為新 mode 被關掉
4. 新增的只有：
   - candidate-owned AVL spanwise lift distribution
   - 它要能被正式餵進結構主線
5. **不要讓 `candidate_avl_spanwise` 自己偷偷變成新的 cruise/load-state owner**

一句話講：

> **只補 spanwise lift ownership，不改原本 AVL-first 搜尋的其他主線假設。**

## 寫入範圍

你只能修改：

- `scripts/dihedral_sweep_campaign.py`
- `scripts/direct_dual_beam_inverse_design.py`
- `src/hpa_mdo/aero/avl_spanwise.py`
- `tests/test_avl_spanwise.py`
- `tests/test_inverse_design.py`

如果你需要補一份短報告，只能新增：

- `docs/task_packs/current_parallel_work/reports/avl_spanwise_realign_report.md`

## 不要碰

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/GRAND_BLUEPRINT.md`
- `configs/blackcat_004.yaml`
- `docs/NOW_NEXT_BLUEPRINT.md`
- `project_state.yaml`
- 任一 hi-fi / Track C 檔案
- 任一 rib penalty / rib tuning 檔案

## 必做要求

### 1. 先對照 repo 內的 AVL manual

請先看：

- `docs/Manual/avl_doc.txt`

至少確認：

- `FT / FN / FS` 的意義
- 你現在用的 `FS strip forces` 到底對應什麼
- 你現在抓的欄位與 surface/strip 語義，和 manual 是否一致

如果 manual 與現有實作不一致，優先修正實作，不要硬凹。

### 2. 不要再讓新 mode 偷偷改掉 AoA / load-state ownership

現在最可疑的 drift 是：

- `candidate_avl_spanwise` 不是只補了一份分佈
- 它還讓結構路徑吃到新的 trim AoA / load-state

你要把它修回：

- **舊 AVL-first 外圈先決定 candidate 的 aero gate / candidate state**
- 然後 `candidate_avl_spanwise` 只是把這個 candidate 的 AVL spanwise lift distribution 交給結構

也就是：

- 不要讓 `candidate_avl_spanwise` 變成另一個新的 `selected_cruise_aoa_deg` owner
- 不要讓它為了做 spanwise artifact，又額外重定義 structural baseline state

### 3. 保留 recovery，不要再要求 `--no-ground-clearance-recovery`

如果現在 `candidate_avl_spanwise` 需要關掉 ground-clearance recovery 才能跑，
這不是使用者要的流程。

你要盡量修到：

- 新 mode 不會自動禁用舊有 recovery 節奏
- 至少不應該因為接了 AVL spanwise loads，就把 recovery 從主線拿掉

### 4. 不要把 `--skip-aero-gates` 當成功標準

debug smoke 可以存在，
但這包的成功，不應該建立在：

- `skip-aero-gates`
- 然後得到一個很重、但 full gate 本來就不會接受的結構 candidate

這包真正要證明的是：

> repaired `candidate_avl_spanwise` 不會再因為新的 ownership 漂移，把原本的 AVL-first 流程弄壞。

## 你應該怎麼驗證

### 最小必要測試

1. `tests/test_avl_spanwise.py`
2. `tests/test_inverse_design.py`
   - 補或修正和 `candidate_avl_spanwise` contract 相關的測試
   - 特別要測：
     - 不再偷偷改掉 selected AoA / load-state semantics
     - recovery 沒有被這個 mode 無故禁用

### 真實 smoke

請至少對一組已知 seed 做真實 smoke，比較：

- `legacy_refresh`
- repaired `candidate_avl_spanwise`
- 如果需要，可以對照 `candidate_rerun_vspaero`

建議 seed：

- `target_shape_z_scale = 4.0`
- `dihedral_exponent = 2.2`
- `rib_zonewise = off`

### 你最後要回報的關鍵問題

1. 你有沒有真的對過 `docs/Manual/avl_doc.txt`？
2. repaired `candidate_avl_spanwise` 還有沒有偷偷改 load-state / selected AoA ownership？
3. 它還需不需要 `--skip-aero-gates` 才看起來合理？
4. recovery 現在有沒有保留？
5. 同一組 seed 下，新的 path 還會不會再把結構 mass 推到明顯不合理的級別？

## 成功標準

- `candidate_avl_spanwise` 被收回成「舊 AVL-first 流程 + spanwise lift ownership」
- 不再順手改掉 gate / recovery / load-state ownership
- 不再把 `--skip-aero-gates` 當主要成功證據
- 至少有一份簡短報告說清楚：
  - 修掉了哪些 drift
  - 還剩哪些邊界

