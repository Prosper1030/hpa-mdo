# AVL Aero Gate Contract

這份文件只講一件事：

`dihedral_sweep_campaign.py` / `multi_wire_sweep_campaign.py` 現在到底用什麼規則做 AVL 外圈 aero screening，以及這套 gate 現在的 code owner 在哪裡。

## 1. 這份 contract 管什麼

目前這份 contract 負責的是 outer-loop candidate screening 的 AVL 氣動 gate：

- 先決定這個 candidate 要 trim 到多少 `CL required`
- 再用 AVL trim 結果判斷：
  - trim AoA 是否過高
  - `L/D` 是否太低
  - 100 kg lift gate 是否有過

它**不**負責：

- Dutch roll / spiral / beta sweep 的側向穩定 gate
- inverse design / structural feasibility
- final release / hi-fi sign-off

## 2. 現在的單一真相在哪裡

目前的 code owner 是：

- [src/hpa_mdo/aero/avl_aero_gates.py](/Volumes/Samsung%20SSD/hpa-mdo/src/hpa_mdo/aero/avl_aero_gates.py)

兩支外圈腳本都接這個模組：

- [scripts/dihedral_sweep_campaign.py](/Volumes/Samsung%20SSD/hpa-mdo/scripts/dihedral_sweep_campaign.py)
- [scripts/multi_wire_sweep_campaign.py](/Volumes/Samsung%20SSD/hpa-mdo/scripts/multi_wire_sweep_campaign.py)

之後如果要改 `CL required`、lift gate、trim AoA gate、metadata 欄位，優先看這個模組，不要再直接在 script 裡找零散公式。

## 3. `CL required` 現在怎麼算

現在的定義是：

`CL required = W_trim / (q * Sref_candidate)`

其中：

- `W_trim = cfg.weight.max_takeoff_kg * 9.81`
- `q = 0.5 * rho * V^2`
- `Sref_candidate = candidate case.avl header 的 Sref`

重點是最後一項：

**現在一律使用 candidate 真正拿去跑 AVL trim 的那份 `case.avl` header `Sref`。**

不再使用：

- `0.5 * span * (root_chord + tip_chord)` 這種 proxy trapezoid area
- 和實際 candidate AVL geometry 脫鉤的固定 reference area

## 4. `trim AoA` 在這裡是什麼意思

這裡的 `trim AoA` 指的是 AVL 在 trim case 裡，為了達到指定 `CL required` 解出來的 aircraft reference `Alpha`。

它的意思比較接近：

- 這個 candidate 相對 freestream 需要多大的整體 reference alpha，才能達到指定 lift coefficient

它**不是**：

- 上反角直接折算成的「等效攻角」
- 每一個 section 的局部有效攻角
- 單純 root section 自己的幾何迎角

所以看到 `trim AoA = 12+ deg` 時，正確解讀應該是：

- 這個 candidate 的整體 trim alpha 很高，值得優先懷疑 gate / reference / geometry contract
- 不能直接說每個翼段都真的在 `12+ deg`

## 5. 現在哪些是 hard gate，哪些只是輔助資訊

目前這個模組直接做的 hard gate 只有三條：

1. `trim_aoa_exceeds_limit`
   - 條件：`aoa_trim_deg > max_trim_aoa_deg`
2. `ld_below_minimum`
   - 條件：`ld_ratio < min_ld_ratio`
3. `insufficient_lift`
   - 條件：`lift_total_n < min_lift_n`

其中：

- `lift_total_n = CL_trim * q * Sref_candidate`
- 所以 lift gate 也和 `CL required` 一樣，用的是同一個 candidate `Sref`

目前仍然只是 telemetry / review context，**不是這個模組內的 hard reject**：

- `soft_trim_aoa_deg`
- `stall_alpha_deg`
- `min_stall_margin_deg`

這些值會跟著 metadata 一起寫出去，方便 review，但現在這個模組本身不會因為它們而直接 fail。

## 6. CLI override 和 config 的關係

`dihedral_sweep_campaign.py` 目前仍保留這兩個 CLI override：

- `--min-lift-kg`
- `--min-ld-ratio`

如果有傳 CLI override，contract 會優先吃 override；沒有的話才吃：

- `cfg.aero_gates.min_lift_kg`
- `cfg.aero_gates.min_ld_ratio`

其他 gate 參數目前仍然從 config 來：

- `cd_profile_estimate`
- `max_trim_aoa_deg`
- `soft_trim_aoa_deg`
- `stall_alpha_deg`
- `min_stall_margin_deg`

## 7. Metadata 現在會寫什麼

`case_metadata.json` / campaign summary 內的 `aero_gate_settings` 現在至少包含：

- `reference_area_source`
- `reference_area_m2`
- `reference_area_case_path`
- `dynamic_pressure_pa`
- `trim_target_weight_kg`
- `trim_target_weight_n`
- `cl_required`
- `min_lift_kg`
- `min_lift_n`
- `min_ld_ratio`
- `cd_profile_estimate`
- `max_trim_aoa_deg`
- `soft_trim_aoa_deg`
- `stall_alpha_deg`
- `min_stall_margin_deg`

所以之後如果又看到 trim regression，先看 metadata 裡這幾個欄位，不要先猜是 geometry 或 airfoil 壞掉。

## 8. 這次修正後的工程判讀

這次 contract 修正代表的是：

- 我們現在用來求 `CL required` 的 reference area
- 和實際拿去跑 candidate AVL trim / lift gate 的 geometry

終於回到同一套 reference。

所以之後如果某個 case 還是卡在 `trim_aoa_exceeds_limit`，比較值得先懷疑的是：

- 幾何本身真的要更高 alpha
- 或 gate 門檻本身要重新定義

而不是先懷疑 `CL required` 公式又偷偷在用另一把尺。
