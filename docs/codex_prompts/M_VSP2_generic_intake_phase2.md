# M-VSP2 — Generic VSP Intake Phase 2（翼型、控制面、分段自動化）

## 前置條件

Phase 1 已完成：`src/hpa_mdo/aero/vsp_introspect.py` 可以從任何符合
「主翼 + H-tail + V-fin」慣例的 .vsp3 抽出 span / root / tip chord / 位置，
`scripts/analyze_vsp.py` 把結果灌進 template 後跑最佳化。

目前 Phase 1 的限制（會寫在 `docs/hi_fidelity_validation_stack.md`）：

1. 翼型（AFILE / NACA）沒 introspect —— 依賴 template 的 `io.airfoil_dir`。
2. 控制面（副翼 / 方向舵 / 升降舵）沒抓 —— AVL 輸出要的 CONTROL 區段得手動寫。
3. `main_spar.segments` 固定 `[1.5, 3.0, 3.0, ...]`，對不同 span 的飛機會出錯。
4. dihedral schedule 只被抽了「每段常數」，曲線翼尖會失真。

## 目標

### 1. 翼型抽取

- 在 `vsp_introspect.py` 加 `_extract_airfoil_refs(vsp, wing_id) -> list[str]`：
  - 對每個 XSec 用 `GetXSecParm(xs, "TopFileName")` 或類似 API 讀 AFILE
    路徑；VSP 內建 NACA 系列就讀 `Num_Digits` 湊 NACA 字串。
  - 回 `[{"station_y": float, "name": str, "source": "afile"|"naca"}]`。
- `_pack_surface` 增 `airfoils` 欄位。
- `merge_into_config_dict` 時：
  - 如果 template 沒給 `io.airfoil_dir`、或 AFILE 檔名在 airfoil_dir
    底下找得到 → 直接用 VSP 值。
  - 否則印 WARN 保留 template 值。

### 2. 控制面偵測

- VSP 的 control surface 存在 `SubSurface` 裡（`GetNumSubSurf` /
  `GetSubSurf`）。抽：
  - Name、type（aileron / elevator / rudder）、`eta_start`、`eta_end`、
    `chord_fraction`、`hinge_axis`。
- 寫進 summary dict 的 `controls` 子欄位；`merge_into_config_dict` 目前
  **不動 config**（配合現況 `HPAConfig` 沒有 control schema），只把
  資訊 dump 到 `resolved_config.yaml` 旁的 `controls.json` 供後續用。

### 3. 翼梁分段自動縮放

- `_scale_segments(template_segments, template_half_span, new_half_span)`：
  - 比例縮放：`new_seg[i] = template_seg[i] * (new_half_span / template_half_span)`。
  - 加總後的 tolerance check：`abs(sum(new_seg) - new_half_span) < 1e-3`。
- `merge_into_config_dict` 加旗標 `scale_segments: bool = True`（預設 on）。
- 印 INFO 讓使用者知道改了什麼。

### 4. 連續 dihedral

- Phase 1 只抽每段的 `Dihedral` parm（常數）。Phase 2：
  - 對每個 XSec station 抽 z 位置（從 schedule 裡累加 `span * sin(dihedral)`），
    寫進 `wing.dihedral_schedule: [[y1, z1], [y2, z2], ...]`。
  - `HPAConfig.wing` 加 optional `dihedral_schedule` 欄位；`VSPBuilder`
    優先吃 schedule，退回去吃常數 `dihedral_deg`。

## 驗收標準

- `scripts/analyze_vsp.py --vsp blackcat004.vsp3` 輸出與 Phase 1 完全一致
  （val_weight 差 < 0.1%）。
- 換一個不同 span / 翼型的 .vsp3（使用者提供），**不改 template** 也能跑完
  最佳化不 crash，產出 `resolved_config.yaml` + `controls.json`。
- `pytest tests/test_vsp_introspect_phase2.py` 包：
  - AFILE / NACA 抽取單元測試。
  - Segment scaling tolerance 測試。
  - Dihedral schedule 與 template 常數 fallback 測試。

## 不要做的事

- 不要把 control surface 塞進 `HPAConfig`；schema 還沒準備好。用 side
  car JSON 先放著。
- 不要偷改 `VSPBuilder` 的 writer，保持與 Phase 1 兼容；只在新的
  `dihedral_schedule` 存在時才走新 code path。
- 不要在 `merge_into_config_dict` 裡呼叫 OpenVSP API — 保持 summary dict
  為純 JSON-serializable 中間物。

## 建議 commit 訊息

```
feat(aero): M-VSP2 Generic VSP intake phase 2

vsp_introspect 抽 airfoil / control surface / 連續 dihedral；
merge_into_config_dict 支援 segment auto-scale。Phase 1 baseline 不動，
新 .vsp3 可直接吃不用改 template。control surface 暫存 sidecar
controls.json，待 HPAConfig 加 schema 後再併入。

Co-Authored-By: Codex 5.4 (Extreme High)
```
