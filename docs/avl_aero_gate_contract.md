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
- [src/hpa_mdo/aero/avl_exporter.py](/Volumes/Samsung%20SSD/hpa-mdo/src/hpa_mdo/aero/avl_exporter.py)
  - `stage_avl_airfoil_files()`

兩支外圈腳本都接這個模組：

- [scripts/dihedral_sweep_campaign.py](/Volumes/Samsung%20SSD/hpa-mdo/scripts/dihedral_sweep_campaign.py)
- [scripts/multi_wire_sweep_campaign.py](/Volumes/Samsung%20SSD/hpa-mdo/scripts/multi_wire_sweep_campaign.py)

之後如果要改 `CL required`、lift gate、trim AoA gate、metadata 欄位，優先看這個模組，不要再直接在 script 裡找零散公式。

如果要改「generated `case.avl` 執行時到底會不會真的吃到 airfoil coordinates」，優先看：

- `stage_avl_airfoil_files()`

不要只看 parser / builder，因為這次踩到的不是名字讀錯，而是 runtime working directory 沒有 `.dat`。

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

## 9. `blackcat_004` 這次踩到的 VSP parser / builder 問題

這次最容易誤會的地方是：

- **不是** `vsp_introspect` 把 root / tip 直接讀反
- 真實 reference `.vsp3` 本來就會讀出：
  - `y = 0.0, 4.5, 7.5, 10.5, 13.5 m` -> `fx76mp140`
  - `y = 16.5 m` -> `clarkysm`

真正的問題是三件事同時漂掉：

1. config 的 `airfoil_root / airfoil_tip` 一度和 reference `.vsp3` 不一致
2. baseline [blackcat_004_full.avl](/Volumes/Samsung%20SSD/hpa-mdo/data/blackcat_004_full.avl) 的主翼 airfoil source 一度也不一致
3. [vsp_builder.py](/Volumes/Samsung%20SSD/hpa-mdo/src/hpa_mdo/aero/vsp_builder.py) 在建 reference schedule 時，一度先用 `_airfoil_for_eta()` 的簡化 fallback，再補 VSP airfoil

所以之後看到 airfoil mapping 很奇怪時，優先判斷應該是：

- 是不是 reference `.vsp3` truth 和 config / baseline AVL / builder schedule 沒對齊

不要第一時間就假設是 `vsp_introspect` 把 root / tip 讀壞。

## 10. `.vsp3` 能不能直接拿來給 AVL 用？

可以分成兩層看：

### 10.1 可以直接從 `.vsp3` 得到什麼

reference `.vsp3` 可以直接告訴你：

- 這個 station 用的是哪個 airfoil name
- section schedule / station ordering 是什麼
- 我們現在應該把 root / tip / 中間站位認成哪一顆翼型

這就是為什麼：

- `summarize_vsp_surfaces()`
- `VSPBuilder._extract_reference_wing_schedule()`

對齊之後，可以把 airfoil identity 釘清楚。

### 10.2 `.vsp3` 現在可以直接驅動 baseline AVL，但 candidate runtime 還是要分清楚 contract

現在 repo 的 baseline [blackcat_004_full.avl](/Volumes/Samsung%20SSD/hpa-mdo/data/blackcat_004_full.avl) 已經可以由：

- 同一份 reference `.vsp3`
- `openvsp` introspection
- inline `AIRFOIL` coordinates

直接重生，所以 **baseline 這條路徑不再依賴外部 `.dat` 才能跑主翼**。

但 AVL 其他 candidate / campaign runtime 如果仍然輸出 `AFILE`，它需要的還是：

- 可被當前 working directory 讀到的 `.dat` 座標檔
- 或者像 baseline 這樣，另外生成 inline `AIRFOIL` coordinates

單靠 `.vsp3` 檔案本身，AVL 仍然不會自動去「從 `.vsp3` 讀 section coordinates 再拿來算」；
是 repo 現在這條 `vsp_to_avl.py -> export_avl()` 路徑把這件事補起來了。

所以目前 repo 的推薦 contract 是：

1. `.vsp3` 負責 origin geometry / airfoil identity / section schedule truth
2. baseline export 優先用 inline `AIRFOIL`
3. candidate campaign 若仍輸出 `AFILE`，就由 `data/airfoils/*.dat` + `stage_avl_airfoil_files()` 負責 runtime contract

### 10.3 未來能不能做成「只靠 `.vsp3`」？

理論上可以，但那會是另一條明確的新功能：

- 不是單純 parser 讀 name
- 而是要把 VSP section airfoil geometry 額外 export / synthesize 成 AVL 可用的 `AFILE` 或 inline `AIRFOIL`

目前這個 repo **還沒有把 `.vsp3` 直接當成 AVL runtime airfoil source**。
所以現在最穩定、最省心的做法還是：

- 維護 canonical `data/airfoils/*.dat`
- 讓 campaign 在 runtime 自動 stage 進去

## 11. 這次之後要特別注意的幾個點

### 11.1 `summarize_vsp_surfaces()` 的回傳是 dict，不是物件樹

這個 helper 回來的是 dict，主翼通常在：

- `summary["main_wing"]`

不是：

- `summary.surfaces`

如果 ad-hoc smoke 直接用錯資料型別，很容易誤以為 parser 壞掉。

### 11.2 ad-hoc smoke 時要確認 `cfg.io.vsp_model` / `io.airfoil_dir` 已經 resolve

如果臨時在 REPL / one-off script 裡直接 load config，但沒有讓：

- `cfg.io.vsp_model`
- `cfg.io.airfoil_dir`

指到真實可讀的絕對路徑，builder 可能退回 config fallback，這時你看到的 airfoil schedule 不一定是 reference `.vsp3` truth。

### 11.3 future check 要同時看四層

只看一層不夠，最少一起看：

1. reference `.vsp3` introspection
2. current baseline / generated `case.avl`
3. case working directory 內實際存在的 `.dat`
4. `aero_gate_settings`

因為這次真正出問題的，不只是前三層的 identity / geometry drift，還多了一個 runtime `.dat` staging contract。

### 11.4 每次驗證時都要順手 grep AVL stdout

這次最有用的直接證據其實不是 summary，而是 AVL 自己吐的 log：

- `Airfoil file not found`
- `Using default zero-camber airfoil`

所以如果要最快排除 runtime airfoil 問題，直接做：

```bash
rg -n "Airfoil file not found|Using default zero-camber airfoil" /path/to/case_dir -S
```

如果有命中，就先不要解釋 AoA / CL / drag，因為 solver 根本還沒吃到你以為的 airfoil。

### 11.5 lift gate 要容忍 AVL 輸出四捨五入

AVL `case_trim.ft` 裡的 `CLtot` 會被列印成有限小數位。
如果 trim target 剛好就是 `100 kg` 對應的精準 `CL required`，拿印出來的 `CLtot` 回算 `lift_total_n` 時，可能會出現像：

- `980.9996 N` vs `981.0 N`

這種接近 machine / print roundoff 的差距。

現在 gate 已經對這種 near-equality 補了容差；下次如果再看到「差不到千分之一牛頓卻 fail lift gate」，先懷疑數值比較，不要先懷疑整個 aero model。

## 12. 最快確認流程

如果之後你只想最快確認「VSP parser / baseline AVL / gate contract 現在是不是一致」，最省時間的順序是：

1. 先看 reference `.vsp3` 真相

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path
from hpa_mdo.aero.vsp_introspect import summarize_vsp_surfaces

summary = summarize_vsp_surfaces(
    Path('/Volumes/Samsung SSD/SyncFile/Aerodynamics/black cat 004 wing only/blackcat 004 wing only.vsp3'),
    airfoil_dir=Path('/Volumes/Samsung SSD/SyncFile/Aerodynamics/airfoil'),
)
for ref in summary["main_wing"]["airfoils"]:
    print(ref["station_y"], ref["name"])
PY
```

預期 `blackcat_004` 主翼是：

- `0.0, 4.5, 7.5, 10.5, 13.5 -> fx76mp140`
- `16.5 -> clarkysm`

2. 再看 current AVL baseline header / gate area

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path
from hpa_mdo.aero import parse_avl, build_avl_aero_gate_settings
from hpa_mdo.core import load_config

cfg = load_config(Path('configs/blackcat_004.yaml'))
avl = Path('data/blackcat_004_full.avl').resolve()
model = parse_avl(avl)
gate = build_avl_aero_gate_settings(cfg=cfg, case_avl_path=avl)
print('sref', model.sref)
print('cl_required', gate.cl_required)
print('reference_area_source', gate.reference_area_source)
PY
```

目前 `blackcat_004` 預期是：

- `sref = 35.175`
- `cl_required ≈ 1.07771045`
- `reference_area_source = generated_avl_sref`

3. 再確認 runtime `.dat` 真的有進 case working directory

最少看：

- `mult_*/case.avl`
- `mult_*/*.dat`
- `mult_*/candidate_avl_spanwise/*.dat`
- `mult_*/avl_*_stdout.log`
- `mult_*/candidate_avl_spanwise/avl_*_stdout.log`

最快檢查是：

```bash
rg -n "Airfoil file not found|Using default zero-camber airfoil" /path/to/mult_4p000 -S
```

沒有命中，才代表 runtime airfoil contract 沒破。

4. 最後再看單點 rerun summary

最少看：

- `case_trim.ft`
- `dihedral_sweep_summary.json`
- `case_metadata.json`

如果這三步都對得起來，就不用再先懷疑 parser / builder / gate contract。
