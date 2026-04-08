# 範例輸出快照

本目錄收錄 HPA-MDO 的參考輸出，用於讓新使用者快速比對「執行是否正常」與「欄位單位是否一致」。

目前提供：

- `optimization_summary.txt`：單次結構最佳化的文字摘要（品質分解、結構表現、段參數、計時資訊）。

> 說明：此處為快照範例，不同設定檔、版本或載重條件下，數值可能不同。

## 主要欄位物理意義

| 欄位 | 單位 | 物理意義 | 判讀建議 |
| --- | --- | --- | --- |
| `total_mass_full_kg` | kg | 全翼展總質量（含桁條/接頭等系統懲罰項），為主要最佳化目標。 | 越小通常越好，但需同時滿足強度與撓度約束。 |
| `spar_mass_full_kg` | kg | 全翼展主樑與後樑管材總質量。 | 可用來觀察結構本體重量占比。 |
| `spar_mass_half_kg` | kg | 半翼展樑系質量。 | 通常約為 `spar_mass_full_kg / 2`。 |
| `tip_deflection_m` | m | 翼尖在設計載重下的垂直撓度。 | 需與 `max_tip_deflection_m` 比較，超過上限即不合格。 |
| `max_tip_deflection_m` | m | 設計允許的最大翼尖撓度限制。 | 來自 config，為結構剛性約束門檻。 |
| `twist_max_deg` | deg | 機翼最大扭轉角。 | 反映扭轉剛性，過大可能影響氣動效率與操控。 |
| `failure_index` | 無因次 | KS 聚合失效指標，綜合主/後樑應力裕度。 | `<= 0` 表示 SAFE，`> 0` 表示 VIOLATED。 |
| `max_stress_main_Pa` | Pa | 主樑最大等效應力。 | 應低於 `allowable_stress_main_Pa`。 |
| `max_stress_rear_Pa` | Pa | 後樑最大等效應力。 | 應低於 `allowable_stress_rear_Pa`。 |
| `allowable_stress_main_Pa` | Pa | 主樑材料容許應力（已納入安全係數概念）。 | 與最大應力比較以判定安全裕度。 |
| `allowable_stress_rear_Pa` | Pa | 後樑材料容許應力。 | 與最大應力比較以判定安全裕度。 |
| `main_t_seg_mm` / `rear_t_seg_mm` | mm | 各段樑管壁厚設計變數。 | 用於觀察最佳化後各段厚度分佈。 |
| `main_r_seg_mm` / `rear_r_seg_mm` | mm | 各段外半徑（摘要檔中通常以 `OD [mm]` 呈現外徑）。 | 與壁厚共同決定剛性與重量。 |

## 建議使用方式

1. 執行同一個設定檔（例如 `configs/blackcat_004.yaml`）。
2. 將新產生的 `optimization_summary.txt` 與本目錄快照做文字比對。
3. 優先確認：狀態、單位、量級、SAFE/VIOLATED 判斷是否合理。
