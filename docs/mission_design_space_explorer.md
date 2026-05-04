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
- `summary.json` (if already exists, this tool will inject `plot_paths`)
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

