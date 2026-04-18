# Track R — Multi-Seed Rib Smoke Signal Hunt Report

> 文件性質：真實 rerun-aero smoke / signal hunt
> 任務來源：`docs/task_packs/current_parallel_work/prompts/track_r_multiseed_rib_smoke_signal_hunt.md`
> 更新日期：2026-04-19
> Verdict：**SUSPICIOUS**

## 1. TL;DR

- 這次實際跑了 `3` 個 seed、共 `6` 組 `candidate_rerun_vspaero` replay：
  - `seed22_frontier_feasible`
  - `seed20_clearance_nearfeasible`
  - `seed18_clearance_nearfeasible`
- seed 選擇不是亂猜，而是直接取自舊的 `output/_archive_pre_2026_04_15/direct_dual_beam_inverse_design_feasibility_sweep_15_22/`：
  - `22 kg` 舊 sweep 裡是可行 frontier
  - `20 kg`、`18 kg` 舊 sweep 裡是最接近 clearance gate 的 near-feasible 點
- 六組 replay 都有真正走到：
  - candidate-owned `.vsp3`
  - VSPAero rerun
  - `.lod` parse
  - feasibility sweep summary JSON
- 但六組 selected-case 全部仍然落到同一種 sentinel fallback：
  - `selection_status = nearest_candidate`
  - `objective_value_kg = 1e12`
  - `total_structural_mass_kg = 1e12`
  - `jig_ground_clearance_min_m = -inf`
  - `target_shape_error_max_m = inf`
  - `loaded_shape_main_z_error_max_m = inf`
- `off` 和 `limited_zonewise` 在這一輪只有 `rib_design.design_key` 不同：
  - `off -> legacy_uniform`
  - `limited_zonewise -> baseline_uniform`
- 內層 refresh summary 的 selected 訊息，六組都一致是：
  - `RuntimeError: Explicit wire truss Newton solve did not converge.`
- feasibility sweep 對外摘要則把這類失敗折疊成：
  - `reject_reason = geometry / discrete boundary`

結論是：

- 這一輪不是 `BLOCKED`
- 但也沒有找到任何一組**不是 sentinel fallback** 的可比 `off` vs `limited_zonewise` selected-case
- 所以目前仍然只能判成 **`SUSPICIOUS`**

## 2. Seed 選擇與理由

| Seed | 來源 | 為什麼選它 | 舊 sweep 狀態 |
| --- | --- | --- | --- |
| `seed22_frontier_feasible` | `target_22.0kg` 舊 summary 的 selected candidate | 舊 sweep 裡唯一真的 `overall_feasible=true` 的 frontier，最值得先拿來測 candidate rerun 下還有沒有訊號 | `21.740 kg`, clearance `~0 mm`, target error `~0`, `overall_feasible=true` |
| `seed20_clearance_nearfeasible` | `target_20.0kg` 舊 summary 的 selected candidate | 不是明顯死點，而是舊 sweep 裡最接近 clearance gate 的 near-feasible 點之一 | `20.620 kg`, clearance `-96.987 mm`, target error `~0`, `overall_feasible=false` |
| `seed18_clearance_nearfeasible` | `target_18.0kg` 舊 summary 的 selected candidate | 和 `20 kg` 相近，但幾何趨勢略不同，可避免只重播單一邊界點 | `20.720 kg`, clearance `-90.441 mm`, target error `~0`, `overall_feasible=false` |

補充：

- 舊 summary 存的是實際 reduced-variable 值，不是目前 CLI 要的 `[0, 1]` grid fraction。
- 這次 replay 先把舊 summary 的 `main_plateau_scale` / `main_taper_fill` / `rear_radius_scale` 轉回目前 CLI fraction 空間，再用一點式 grid 重播。
- 為了遵守這包只改 report write scope 的限制，所有實際 solver 輸出都寫到 `/tmp/hpa_mdo_track_r_multiseed_20260419/`，沒有寫回 repo 內 `output/`。

## 3. 實際執行命令

以下是這次實際跑的六條命令，皆在 repo root `/Volumes/Samsung SSD/hpa-mdo` 下執行：

```bash
uv run --no-project python scripts/direct_dual_beam_inverse_design_feasibility_sweep.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_multiseed_20260419/seed22_frontier_feasible/off \
  --target-masses-kg 22 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode off \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --design-report output/blackcat_004/ansys/crossval_report.txt

uv run --no-project python scripts/direct_dual_beam_inverse_design_feasibility_sweep.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_multiseed_20260419/seed22_frontier_feasible/limited_zonewise \
  --target-masses-kg 22 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode limited_zonewise \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --design-report output/blackcat_004/ansys/crossval_report.txt

uv run --no-project python scripts/direct_dual_beam_inverse_design_feasibility_sweep.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_multiseed_20260419/seed20_clearance_nearfeasible/off \
  --target-masses-kg 20 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode off \
  --main-plateau-grid 0.9966539474376832 \
  --main-taper-fill-grid 0.8713400435486665 \
  --rear-radius-grid 0.8745974048236186 \
  --rear-outboard-grid 0.8534001272911103 \
  --wall-thickness-grid 0.040641153863537643 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --design-report output/blackcat_004/ansys/crossval_report.txt

uv run --no-project python scripts/direct_dual_beam_inverse_design_feasibility_sweep.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_multiseed_20260419/seed20_clearance_nearfeasible/limited_zonewise \
  --target-masses-kg 20 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode limited_zonewise \
  --main-plateau-grid 0.9966539474376832 \
  --main-taper-fill-grid 0.8713400435486665 \
  --rear-radius-grid 0.8745974048236186 \
  --rear-outboard-grid 0.8534001272911103 \
  --wall-thickness-grid 0.040641153863537643 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --design-report output/blackcat_004/ansys/crossval_report.txt

uv run --no-project python scripts/direct_dual_beam_inverse_design_feasibility_sweep.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_multiseed_20260419/seed18_clearance_nearfeasible/off \
  --target-masses-kg 18 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode off \
  --main-plateau-grid 0.978796339113313 \
  --main-taper-fill-grid 0.8013885983756893 \
  --rear-radius-grid 0.9434354419543309 \
  --rear-outboard-grid 0.8797958316475152 \
  --wall-thickness-grid 0.04111455456726137 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --design-report output/blackcat_004/ansys/crossval_report.txt

uv run --no-project python scripts/direct_dual_beam_inverse_design_feasibility_sweep.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_multiseed_20260419/seed18_clearance_nearfeasible/limited_zonewise \
  --target-masses-kg 18 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode limited_zonewise \
  --main-plateau-grid 0.978796339113313 \
  --main-taper-fill-grid 0.8013885983756893 \
  --rear-radius-grid 0.9434354419543309 \
  --rear-outboard-grid 0.8797958316475152 \
  --wall-thickness-grid 0.04111455456726137 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --design-report output/blackcat_004/ansys/crossval_report.txt
```

## 4. 是否真的跑到 `candidate_rerun_vspaero`

有，而且這六組都是**完整跑到** candidate-owned rerun 路徑。

| Seed | `off` 完成 | `limited_zonewise` 完成 | `aero_source_mode` | `baseline_load_source` | `refresh_load_source` | `selected_cruise_aoa_deg` |
| --- | --- | --- | --- | --- | --- | --- |
| `seed22_frontier_feasible` | ✅ | ✅ | `candidate_rerun_vspaero` | `candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun` | `candidate_owned_twist_refresh_from_rerun_sweep` | `4.0` |
| `seed20_clearance_nearfeasible` | ✅ | ✅ | `candidate_rerun_vspaero` | `candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun` | `candidate_owned_twist_refresh_from_rerun_sweep` | `4.0` |
| `seed18_clearance_nearfeasible` | ✅ | ✅ | `candidate_rerun_vspaero` | `candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun` | `candidate_owned_twist_refresh_from_rerun_sweep` | `4.0` |

對應 summary 都在：

- `/private/tmp/hpa_mdo_track_r_multiseed_20260419/seed22_frontier_feasible/`
- `/private/tmp/hpa_mdo_track_r_multiseed_20260419/seed20_clearance_nearfeasible/`
- `/private/tmp/hpa_mdo_track_r_multiseed_20260419/seed18_clearance_nearfeasible/`

## 5. `off` vs `limited_zonewise` 比較表

### 5.1 `seed22_frontier_feasible`

| 欄位 | `rib_zonewise=off` | `rib_zonewise=limited_zonewise` |
| --- | --- | --- |
| `objective_value_kg` | `1000000000000.0` | `1000000000000.0` |
| `total_structural_mass_kg` | `1000000000000.0` | `1000000000000.0` |
| `jig_ground_clearance_min_m` | `-inf` | `-inf` |
| `target_shape_error_max_m` | `inf` | `inf` |
| `loaded_shape_main_z_error_max_m` | `inf` | `inf` |
| `rib_design.design_key` | `legacy_uniform` | `baseline_uniform` |
| `rib_design.effective_warping_knockdown` | `0.5` | `0.5` |
| `rib_design.unique_family_count` | `1` | `1` |
| `rib_design.family_switch_count` | `0` | `0` |
| `rib_design.objective_penalty_kg` | `0.0` | `0.0` |
| sweep `selection_status` | `nearest_candidate` | `nearest_candidate` |
| sweep `reject_reason` | `geometry / discrete boundary` | `geometry / discrete boundary` |
| inner selected message | `Explicit wire truss Newton solve did not converge` | `Explicit wire truss Newton solve did not converge` |

### 5.2 `seed20_clearance_nearfeasible`

| 欄位 | `rib_zonewise=off` | `rib_zonewise=limited_zonewise` |
| --- | --- | --- |
| `objective_value_kg` | `1000000000000.0` | `1000000000000.0` |
| `total_structural_mass_kg` | `1000000000000.0` | `1000000000000.0` |
| `jig_ground_clearance_min_m` | `-inf` | `-inf` |
| `target_shape_error_max_m` | `inf` | `inf` |
| `loaded_shape_main_z_error_max_m` | `inf` | `inf` |
| `rib_design.design_key` | `legacy_uniform` | `baseline_uniform` |
| `rib_design.effective_warping_knockdown` | `0.5` | `0.5` |
| `rib_design.unique_family_count` | `1` | `1` |
| `rib_design.family_switch_count` | `0` | `0` |
| `rib_design.objective_penalty_kg` | `0.0` | `0.0` |
| sweep `selection_status` | `nearest_candidate` | `nearest_candidate` |
| sweep `reject_reason` | `geometry / discrete boundary` | `geometry / discrete boundary` |
| inner selected message | `Explicit wire truss Newton solve did not converge` | `Explicit wire truss Newton solve did not converge` |

### 5.3 `seed18_clearance_nearfeasible`

| 欄位 | `rib_zonewise=off` | `rib_zonewise=limited_zonewise` |
| --- | --- | --- |
| `objective_value_kg` | `1000000000000.0` | `1000000000000.0` |
| `total_structural_mass_kg` | `1000000000000.0` | `1000000000000.0` |
| `jig_ground_clearance_min_m` | `-inf` | `-inf` |
| `target_shape_error_max_m` | `inf` | `inf` |
| `loaded_shape_main_z_error_max_m` | `inf` | `inf` |
| `rib_design.design_key` | `legacy_uniform` | `baseline_uniform` |
| `rib_design.effective_warping_knockdown` | `0.5` | `0.5` |
| `rib_design.unique_family_count` | `1` | `1` |
| `rib_design.family_switch_count` | `0` | `0` |
| `rib_design.objective_penalty_kg` | `0.0` | `0.0` |
| sweep `selection_status` | `nearest_candidate` | `nearest_candidate` |
| sweep `reject_reason` | `geometry / discrete boundary` | `geometry / discrete boundary` |
| inner selected message | `Explicit wire truss Newton solve did not converge` | `Explicit wire truss Newton solve did not converge` |

## 6. 工程判讀

這次 multi-seed 結果支持的結論是：

1. `candidate_rerun_vspaero` 路線本身不是 blocked。
   六組 replay 都有完整走到 candidate-owned geometry rebuild、VSPAero rerun、summary JSON。

2. 目前這個最小 smoke budget 下，**沒有找到任何一組非 sentinel 的可比 selected-case**。
   換句話說，這次 Track R 的核心問題目前答案是：**還沒有找到。**

3. 這一輪看不到 `off` vs `limited_zonewise` 的真正 ranking signal。
   目前看到的只是同一種 sentinel failure 被兩邊重播。

4. 真正更貼近 immediate blocker 的訊息，不像 Track P 那樣只剩模糊的 `geometry / discrete boundary`。
   這次深入看 inner refresh summary，六組都顯示：
   - `RuntimeError: Explicit wire truss Newton solve did not converge.`

所以這份結果**不能**支持下面這些解讀：

- rib penalty 已經該調
- rib ranking 已經 sane
- 可以直接進 finalist local spot-check

它只能支持比較保守的判斷：

**Track R 這一輪已經把「單點 smoke 不夠」往前推到「三個代表 seed 還是不夠」，但仍然沒有拿到可比較的 rib-on vs rib-off selected-case 訊號。**

## 7. Verdict

**SUSPICIOUS**

原因：

- 不是 `BLOCKED`
  - 因為六組 `candidate_rerun_vspaero` replay 都成功跑完並落盤
- 也不是 `SANE`
  - 因為沒有任何一組 selected-case 逃出 sentinel fallback
  - `off` / `limited_zonewise` 的 selected summary 幾乎完全一樣，只差 rib design label

## 8. 下一步建議

這次三選一，我會選：

**維持現狀再補更多 smoke**

不建議現在直接：

- 進 `Track M` 做 tuning
- 進 `Track N` 做 finalist spot-check

比較合理的下一步是：

1. 繼續保留 `candidate_rerun_vspaero`
2. 仍然維持小型 smoke，而不是直接暴力擴大成大 campaign
3. 但下一輪應該至少加一個比這次稍強的搜尋動作，例如：
   - 對 `22 kg` frontier seed 開有限度 local refine
   - 或從這次 candidate-rerun archive 再往外挑 1 到 2 個 seed，而不是只沿用 legacy refresh 時代的 selected point
4. 等真的有至少一組非 sentinel selected-case，再決定：
   - 是不是該進 `Track M`
   - 還是其實已經能進 `Track N`

## 9. 風險與未完成處

- 這次只做了 prompt 要求的最小多-seed smoke，沒有再往上開 local refine。
  所以結論是「在這個最小 budget 下仍無訊號」，不是「所有合理 budget 都無訊號」。

- 目前外層 feasibility sweep 的 `reject_reason` 仍偏粗。
  它把這輪失敗折成 `geometry / discrete boundary`，但內層 selected message 其實比較像 `explicit wire truss` 的收斂問題。

- 因為還沒有拿到任何非 sentinel selected-case，所以：
  - 還不能評估 rib ranking 是不是合理
  - 還不能判斷 tuning 方向
  - 還不能做 finalist handoff 級別的 spot-check
