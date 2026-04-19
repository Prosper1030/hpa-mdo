# AVL Structural Load-State Alignment Report

> 文件性質：Track V/W 修正後的最小必要對齊報告
> 任務日期：2026-04-19
> 任務目標：把 `candidate_avl_spanwise` 修回「舊 AVL-first flow + spanwise lift distribution」，不要再把 AVL trim-required state 直接吃成 structural selected state。

## 1. 結論

- **有修回來。**
- 目前 repaired `candidate_avl_spanwise` 的 structural selected state 不再吃 `AoA 12.536 deg`。
- 它現在會先沿用 `legacy_refresh` 的 structural load-state owner，再只用 candidate-owned AVL strip-force artifact 取代 **lift distribution shape**。
- 同一組 fixed seed 下，repaired `candidate_avl_spanwise` 已經和 `legacy_refresh` 明顯貼近：
  - `legacy_refresh`: `AoA 0.000 deg / lift 450.904 N / torque 260.296 N*m`
  - repaired `candidate_avl_spanwise`: `AoA 0.000 deg / lift 450.668 N / torque 260.296 N*m`
  - `candidate_rerun_vspaero`: `AoA 4.000 deg / lift 448.190 N / torque 228.141 N*m`
- 所以現在可以把 repaired `candidate_avl_spanwise` 描述成：
  - **`舊 AVL-first flow + candidate-owned spanwise lift distribution`**
  - 但**不是** `candidate_rerun_vspaero` 的替代品，因為 rerun 仍然是另一個較重的 candidate-owned full geometry / load contract。

## 2. 先回答問題定義

### 2.1 原本 `AoA 12.536 deg` 是怎麼來的？

修正前，`candidate_avl_spanwise` 直接把 artifact 內的：

- `selected_cruise_aoa_deg = outer-loop AVL trim AoA`

拿來當 structural baseline case，再把整份 AVL case 的 lift / torque 一起交給 refresh path。

在這組 seed 上，這就把：

- outer-loop 用來過 trim / gate 的 `AVL trim-required state`

錯當成：

- structural selected load-state owner

所以最後會落到：

- `AoA 12.536 deg`
- `lift 570.711 N`
- `torque 0.623 N*m`

這已經不是「舊流程 + lift distribution」，而是另一個 state。

### 2.2 修正後 structural selected state 怎麼決定？

現在 `candidate_avl_spanwise` 改成兩層：

1. 先用和 `legacy_refresh` 相同的 shared `cfg.io` VSPAero sweep，重建 **structural selected state owner**
2. 再對每個 legacy sweep case，從 candidate-owned AVL strip-force artifact 挑一個最接近的 lift-shape case，並把該 lift shape **rescale 回 legacy-selected total lift**

重點是：

- structural selected state：還是 `legacy_refresh` owner
- outer-loop trim / gates：仍然只是 gate owner
- candidate-owned AVL：現在只接管 `spanwise lift distribution shape`
- torque / drag：保留 legacy-selected state，不再被 raw AVL case 偷偷洗掉

在這組 seed 上，selected structural state 因此回到：

- `AoA 0.000 deg`

而不是：

- `AoA 12.536 deg`

## 3. FS 語義檢查

已對照 `docs/Manual/avl_doc.txt` 與 `.fs` 實際欄位：

- `FS` 是 strip forces，不是 total force summary
- `.fs` table 欄位包含 strip-level `cl / cd / cm_c/4`
- 這次修正**沒有**再把 `FS` 擴張成 full candidate load-state owner

也就是說，這包不是再重做 parser；修的是 **state ownership / structural contract**：

- AVL `FS` 仍然只拿來提供 candidate-owned lift-shape evidence
- structural load-state owner 改回舊流程節奏

## 4. 最小 compare

### 4.1 compare 設定

- fixed seed
  - `target_shape_z_scale = 4.0`
  - `dihedral_exponent = 2.2`
  - `rib_zonewise = off`
  - `main_plateau_grid = 1.0`
  - `main_taper_fill_grid = 0.999999500019976`
  - `rear_radius_grid = 0.9999997444012075`
  - `rear_outboard_grid = 1.0`
  - `wall_thickness_grid = 0.04630959736295326`
- compare outputs
  - `legacy_refresh`: `/tmp/avl_align_direct_legacy/direct_dual_beam_inverse_design_refresh_summary.json`
  - repaired `candidate_avl_spanwise`: `/tmp/avl_align_direct_candidate_avl/direct_dual_beam_inverse_design_refresh_summary.json`
  - `candidate_rerun_vspaero`: `/tmp/avl_align_direct_candidate_rerun/direct_dual_beam_inverse_design_refresh_summary.json`
- `design_report`
  - `output/blackcat_004/ansys/crossval_report.txt`
  - 這裡只把它當 inspection / baseline artifact，不把它包裝成 validation truth

### 4.2 compare 結果

| path | selected structural AoA | total half-span lift | total `|torque|` half-span | jig clearance | mass | feasible | recovery |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `legacy_refresh` | `0.000 deg` | `450.904 N` | `260.296 N*m` | `-26.532 mm` | `21.740001 kg` | `false` | `triggered=true` |
| repaired `candidate_avl_spanwise` | `0.000 deg` | `450.668 N` | `260.296 N*m` | `-23.716 mm` | `21.740001 kg` | `false` | `triggered=true` |
| `candidate_rerun_vspaero` | `4.000 deg` | `448.190 N` | `228.141 N*m` | `+0.621 mm` | `21.740001 kg` | `true` | `triggered=false` |

### 4.3 判讀

- repaired `candidate_avl_spanwise` vs `legacy_refresh`
  - `AoA delta = 0.000 deg`
  - `lift delta = -0.236 N`
  - `torque delta = -0.000 N*m`
  - `clearance delta = +2.815 mm`
- repaired `candidate_avl_spanwise` vs `candidate_rerun_vspaero`
  - `AoA delta = -4.000 deg`
  - `lift delta = +2.478 N`
  - `torque delta = +32.156 N*m`
  - `clearance delta = -24.337 mm`

這代表：

- repaired `candidate_avl_spanwise` 已經**非常接近 `legacy_refresh`**
- 它不再是之前那個 `AoA 12.536 deg / torque ~0` 的另一個 state
- 它和 `candidate_rerun_vspaero` 仍然不同，但這個不同比較像是：
  - `legacy-style AVL-first structural baseline`
  - 對上
  - `candidate-owned rerun confirm contract`

## 5. 不再依賴 debug bootstrap artifact

- 這次另外把 `scripts/dihedral_sweep_campaign.py` 修成：
  - 只要 trim 成功，就會先產出 `candidate_avl_spanwise_loads.json`
  - 即使後續 aero gate fail，也不需要再靠 `--skip-aero-gates` 才能留下 compare artifact
- 這讓現在的 compare 路徑可以走：
  - 正常 gate flow 先留 artifact
  - direct compare 再吃這份 artifact
- 所以這次的主 compare **不是靠 debug bootstrap artifact 成立**

## 6. 是否可以開 Track X？

- **可以。**

理由：

- `candidate_avl_spanwise` 的 structural selected state 已經回到 legacy owner
- gate / recovery 節奏沒有再飄掉
- current repaired path 現在已經能被合理描述成：
  - `old AVL-first flow + candidate-owned spanwise lift distribution`

## 7. 還剩下的差異是什麼？

如果之後要再追問 repaired AVL 和 rerun 為什麼還不同，剩下的最小差異是：

- repaired `candidate_avl_spanwise`
  - 故意保留 `legacy_refresh` 的 structural torque / drag owner
  - 只換 candidate-owned AVL lift-shape
- `candidate_rerun_vspaero`
  - 是 candidate-owned OpenVSP geometry rebuild + VSPAero rerun
  - 它的 torque / clearance 本來就不會保證和 legacy 完全一樣

所以目前剩下的差異，不再是「selected state 選錯到 trim-required AoA」；
而是：

- `AVL-first legacy-aligned screening contract`
  和
- `rerun confirm contract`

本來就不是同一層級的東西。
