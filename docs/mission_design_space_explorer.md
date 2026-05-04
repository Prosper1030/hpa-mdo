# Mission Design Space Explorer

This tool runs quick-screen sweeps over mission design combinations and outputs CSV tables, summary markdown, and now plot files to help interpret the design envelope quickly.

## Output files

- `full_results.csv`
- `envelope_by_speed.csv`
- `envelope_by_cd0.csv`
- `envelope_by_ar.csv`
- `envelope_by_span.csv`
- `envelope_by_clmax.csv`
- `boundary_speed_cd0.csv`
- `report.md`
- `summary.json` (always generated, includes input/environment/counts/envelopes/plot paths)
- `human_readable_summary.json` (中文/簡報版摘要，給使用者閱讀)
- `optimizer_handoff.json` (pipeline 專用 handoff 合約)
- `candidate_seed_pool.csv` (按 mission-level 分組後的 seed 池)
- `plots/*.png` (when plot generation is enabled)

## Plot outputs generated

The explorer now generates the following PNGs:

1. `robust_cases_by_speed.png`
2. `max_margin_by_speed.png`
3. `feasible_speed_range_by_cd0.png`
4. `feasible_speed_range_by_ar.png`
5. `feasible_speed_range_by_span.png`
6. `robust_cases_by_clmax.png`
7. `robust_count_heatmap_speed_cd0.png`
8. `raw_best_margin_heatmap_speed_cd0.png`
9. `stall_risk_by_speed_clmax.png`
10. `robust_candidates_speed_cd0_scatter.png`

## CLI usage

```bash
python scripts/mission_design_space_explorer.py --config configs/mission_design_space_example.yaml
```

Optional flags:

- `--skip-plots`: skip PNG generation.
- `--output-dir`: override `outputs.output_dir` from config.
- `--dry-run`: print case count only.
- `--limit N`: evaluate only first N cases (for smoke checks).

## Config additions

`outputs` supports:

- `write_full_results_csv`
- `write_envelope_csv`
- `write_markdown_report`
- `write_plots`

Add `plots` block:

```yaml
outputs:
  output_dir: output/mission_design_space
  write_full_results_csv: true
  write_envelope_csv: true
  write_markdown_report: true
  write_plots: true

plots:
  dpi: 160
  format: png
  max_candidate_rows_in_report: 10
```

If `plots` block is omitted, defaults are:

- `dpi: 160`
- `format: png`
- `max_candidate_rows_in_report: 10`
- `write_plots: true` from `outputs` defaults

## Report updates

When plots are available, `report.md` includes a `## Visual Summary` section with all generated image links so the design envelope can be reviewed without opening CSV only.

## Human-facing outputs

- `report.md`
- `plots/*.png`
- `human_readable_summary.json`

以上輸出是給人看與做決策前置判讀的，不是 optimizer 的最終設計輸出：

- `report.md` 提供設計空間、風險、敏感度的可讀化摘要與表格。
- `plots/*.png` 顯示關鍵邊界與風險分布。
- `human_readable_summary.json` 提供前端/簡報可直接引用的 `headline` 與 `risk_summary`。

## Optimizer-facing outputs

以下是 pipeline / optimizer 要讀的輸出：

- `summary.json`（包含 handoff metadata）
- `optimizer_handoff.json`
- `candidate_seed_pool.csv`

它們定義「穩健空間到 seed 搜尋」的階段性交接，不是最終設計選擇：

- `summary.json`：保留高層摘要、`optimizer_handoff` 區塊（含 seed-tier 統計）。
- `candidate_seed_pool.csv`：每個 seed（`speed_mps, span_m, aspect_ratio, cd0_total`）彙整成 `robust_fraction`、功率邊界與 tier。
- `optimizer_handoff.json`：定義 `search_bounds`、`mission_gate`、`seed_policy`、`output_files`。

`summary.json` is written to `output_dir` every run and is intended for automation or quick post-processing. It includes:

- `input_paths`: power csv and metadata yaml paths
- `environments`: `test_environment`, `target_environment`, `heat_derate_factor`
- `counts`: `total_cases`, `power_passed_cases`, `robust_cases`, `margin_ge_min_cases`, `margin_ge_robust_cases`
- `robust_definition`, `robust_speed_envelope`, `cd0_envelope`, `ar_envelope`, `span_envelope`, `clmax_robust_counts`
- `observed_robust_envelope` (full robust case boundary, i.e., all robust cases)
- `suggested_main_design_region` (conservative initial design-search region, not unique optimum)
- `output_files`
- `plot_paths` (empty dict if `--skip-plots` or plots disabled)

`report.md` `## Inputs` adds a `summary.json` path entry for traceability.

`observed_robust_envelope` is the full boundary from all robust cases. `suggested_main_design_region` is a conservative initial region only (for design exploration), not the unique best solution.

## How optimizer should use this

1. 先執行 `scripts/mission_design_space_explorer.py`
2. optimizer 先讀 `optimizer_handoff.json`
3. 用 `search_bounds` 初始化搜尋範圍
4. 用 `candidate_seed_pool.csv` 當初始 seeds
5. 每個 seed 先用 `evaluate_optimizer_mission_gate` 做 pre-gate
6. gate 通過後再接進 AVL / XFOIL / structure / propeller 做更高保真分析

這是 Stage-0 mission feasibility gate：

- 這個輸出不提供 optimizer 最終答案
- 不可取代 AVL / XFOIL / CFD / 試飛分析
- 用於界定可行範圍、節省 optimizer 搜尋成本
