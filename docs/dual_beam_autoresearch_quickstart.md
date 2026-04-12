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

## 4. 第一版固定規則

這版 consumer 故意很小，固定如下：

- 只吃 `Primary design`
- 不讀 Balanced / Conservative 做評分
- score 固定為 `-Primary.mass_kg`
- 先檢查 `schema_name` / `schema_version`

## 5. 目前沒有做的事

這版還**沒有**：

- 多目標 score
- Primary / Balanced / Conservative 混合 decision
- 多案例 orchestration
- 自動 agent loop / commit loop
- 更高階 reporting / ranking layer

如果之後要擴，也建議先保持 producer / consumer 邊界，再逐步疊上去。
