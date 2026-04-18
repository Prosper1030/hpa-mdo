# Drawing-Ready Baseline Package

> **文件性質**：畫設計圖 / 做 drawing handoff 時的最短入口。
> **適用情境**：你現在不是要研究 solver，而是要知道「哪個檔可以拿去畫、哪個檔只是參考」。
> **預設位置**：`output/blackcat_004/drawing_ready_package/`

## 1. 一句話版本

如果你現在要開始畫設計圖，先不要自己在 `output/blackcat_004/` 裡找檔案。

請直接用這個 package：

- 主幾何：`geometry/spar_jig_shape.step`
- 設計依據：`design/discrete_layup_final_design.json`
- 人類摘要：`design/optimization_summary.txt`
- 表格幾何：`data/spar_data.csv`
- drawing checklist：`DRAWING_CHECKLIST.md`
- drawing release：`DRAWING_RELEASE.json`
- drafting station table：`data/drawing_station_table.csv`
- segment schedule：`data/drawing_segment_schedule.csv`

## 2. 你應該先看什麼

| 你要做的事 | 先看哪個檔 | 為什麼 |
|---|---|---|
| 畫 spar 主圖 | `geometry/spar_jig_shape.step` | 這是目前 primary spar drawing truth |
| 確認 discrete layup / final design verdict | `design/discrete_layup_final_design.json` | 這是 machine-readable final design basis |
| 先快速理解整體狀態 | `design/optimization_summary.txt` | 這是人類最容易讀的總結 |
| 照 checklist 出圖 | `DRAWING_CHECKLIST.md` | 這裡把主尺寸、特殊站位、segment layup 摘成出圖清單 |
| 做正式交接 / 給其他 agent | `DRAWING_RELEASE.json` | 這裡把 drawing truth、gate、特殊站位、主要交付檔整理成 machine-readable release |
| 直接拉 drafting 尺寸表 | `data/drawing_station_table.csv` | 這裡是已整理好的 station / OD / wall thickness 表 |
| 直接看每段規格 | `data/drawing_segment_schedule.csv` | 這裡是每段 span、OD、壁厚、layup 的表 |
| 拉尺寸 / 讀展向表格 | `data/spar_data.csv` | 這裡有 spanwise station 與 export-contract tabular values |
| 看 loaded shape 或 cruise 參考 | `references/*` | 這些只是參考，不是主 drawing truth |

## 3. 哪些東西不能混用

- 不要把 `references/spar_flight_shape.step` 當成製造 jig 主幾何。
- 不要把 `references/wing_cruise.vsp3` 當成 spar drawing truth。
- 不要把 `crossval_report.txt` 當成 drawing truth。
- 也不要把 `crossval_report.txt` 當成 validation truth；它最多只是 internal inspection reference / export contract。

## 4. 怎麼重建 package

如果 `output/blackcat_004/drawing_ready_package/` 還沒生成，直接跑：

```bash
uv run python scripts/export_drawing_ready_package.py --output-dir output/blackcat_004
```

如果你已經在跑主線最佳化：

```bash
uv run python examples/blackcat_004_optimize.py
```

現在主線結束時也會自動匯出這個 package。

## 5. 這個 package 的定位

這個 package 解決的是「drawing handoff / artifact ambiguity」，不是 external validation。

它的意思是：

- 你現在知道哪個檔是正式畫圖入口。
- 你現在知道哪些檔只是參考。
- 你現在不用再從一堆 output 裡猜哪個是主版本。

它不代表：

- external benchmark 已完成
- hi-fi validation 已完成
- 所有 flight-state / composite 細節都已成為 drawing truth

## 6. 建議工作順序

如果你現在的目標真的是出圖，我建議照這個順序：

1. 先打開 `geometry/spar_jig_shape.step`
2. 再對照 `design/discrete_layup_final_design.json`
3. 再讀 `design/optimization_summary.txt`
4. 需要尺寸表時再看 `data/spar_data.csv`
5. 只有在需要理解 loaded/cruise 差異時才看 `references/*`
