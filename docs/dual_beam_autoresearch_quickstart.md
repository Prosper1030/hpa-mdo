# Dual-Beam Built-In Autoresearch Quickstart

更新時間：2026-04-12 CST

這份文件是寫給只想 clone `hpa-mdo` 一個 repo、先用第一版 autoresearch consumer 的使用者。

## 1. 這是什麼

現在 `hpa-mdo` 內建一個最小可用的 consumer / autoresearch 入口：

- `python -m hpa_mdo.autoresearch`
- `hpa-autoresearch`

它不是完整的外部 `autoresearch-通用` framework 移植版。

它只是把已驗證成功的最小 consumer 模式正式收進 repo：

1. 呼叫正式 producer `python -m hpa_mdo.producer`
2. parse producer stdout manifest
3. 讀 decision interface v1 JSON
4. 只取 `Primary design`
5. 固定 score：`-Primary.mass_kg`

## 2. 依賴

至少需要安裝 `hpa-mdo` 基本依賴。

如果你是剛 clone repo，推薦：

```bash
uv sync
```

之後用：

```bash
uv run python -m hpa_mdo.autoresearch --output-dir /abs/path/to/run_dir
```

或：

```bash
uv run hpa-autoresearch --output-dir /abs/path/to/run_dir
```

## 3. 會輸出什麼

### stdout

consumer 會輸出：

- producer command
- decision schema / status
- Primary slot status
- Primary fallback reason
- Primary mass
- Primary margin
- decision JSON path
- 最後一行 `分數: ...`

例如：

```text
HPA-MDO autoresearch consumer
Decision status: complete
Primary mass (kg): 10.089649
Primary margin (mm): 59.706287
分數: -10.089649
```

### output dir

`--output-dir` 會直接交給正式 producer，因此該目錄內會有：

- `direct_dual_beam_v2m_joint_material_report.txt`
- `direct_dual_beam_v2m_joint_material_summary.json`
- `direct_dual_beam_v2m_joint_material_decision_interface.json`
- `direct_dual_beam_v2m_joint_material_decision_interface.txt`

### autoresearch run history

現在每次 `python -m hpa_mdo.autoresearch` 跑完，也會自動留下 run record。

預設位置：

- `OUTPUT_DIR/autoresearch_history/autoresearch_run_records.jsonl`
- `OUTPUT_DIR/autoresearch_history/autoresearch_latest_run_record.json`
- `OUTPUT_DIR/autoresearch_history/decision_snapshots/`

其中：

- `autoresearch_run_records.jsonl` 是 append-only ledger
- `autoresearch_latest_run_record.json` 方便快速看最近一次結果
- `decision_snapshots/` 會保存每次 run 的 decision JSON snapshot，避免原 output 被覆寫後記錄失效

如果你想把不同 `output_dir` 的 run 聚合到同一份 history，可以加：

```bash
uv run python -m hpa_mdo.autoresearch \
  --output-dir /abs/path/to/run_dir \
  --history-dir /abs/path/to/shared_history
```

## 4. run record 格式

每筆 run record 固定至少包含：

- `run_id`
- `run_timestamp_utc`
- `status`
- `score_name`
- `score_rule`
- `score`
- `primary_mass_kg`
- `primary_margin_mm`
- `output_dir`
- `decision_json_path`
- `decision_json_snapshot_path`
- `decision_schema_name`
- `decision_schema_version`
- `git_commit_hash`

格式選 JSONL，原因是：

- append 新 run 很便宜，不需要重寫整個 history
- JSON 比 CSV / TSV 更適合 path、nullable 欄位與未來擴欄
- 後續 batch / agent / app / reporting 可以逐行 parse

## 5. compare / summary

現在可以直接讀 history 做最薄比較：

```bash
uv run python -m hpa_mdo.autoresearch summary
```

或指定 history 目錄：

```bash
uv run python -m hpa_mdo.autoresearch summary \
  --history-dir /abs/path/to/shared_history \
  --limit 10
```

它會列出：

- 最近幾次 run
- 成功 / 失敗數
- 最好 score
- 每筆 run 的 primary mass / margin
- 相對最佳 run 的 mass / margin 差值

如果要 machine-readable summary，也可以輸出 JSON：

```bash
uv run python -m hpa_mdo.autoresearch summary \
  --history-dir /abs/path/to/shared_history \
  --json-out /abs/path/to/autoresearch_summary.json
```

## 6. 第一版固定規則

這版 consumer 故意很小，固定如下：

- 只吃 `Primary design`
- 不讀 Balanced / Conservative 做評分
- score 固定為 `-Primary.mass_kg`
- 先檢查 `schema_name` / `schema_version`

## 7. 目前沒有做的事

這版還**沒有**：

- 多目標 score
- Primary / Balanced / Conservative 混合 decision
- 多案例 orchestration
- 自動 agent loop / commit loop
- 更高階 reporting / ranking layer

如果之後要擴，也建議先保持 producer / consumer 邊界，再逐步疊上去。
