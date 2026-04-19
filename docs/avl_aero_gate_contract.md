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

這裡要特別分兩層看：

1. 這份文件前半段主要在講 `avl_aero_gates.py` 這個 trim / lift / L/D 子模組
2. `dihedral_sweep_campaign.py` 這個 campaign 主流程，另外還有接上穩定性與結構 gate

所以如果你問「現在的穩定條件判斷有沒有寫進去」：

**有，寫在 campaign 主流程裡。**

目前 campaign-level reject logic 還會另外檢查：

- `aero_status`
  - Dutch roll / least-damped lateral mode 是否穩定
- `beta_sweep_directional_stable`
  - `Cn_beta` 的方向穩定性
- `beta_sweep_sideslip_feasible`
  - beta sweep 到目標角度時 trim 是否收斂
- `spiral_check_ok`
  - spiral mode 的 time-to-double / stable 判定
- inverse-design subprocess / structural feasibility
- `max_tube_mass_kg`
  - spar tube mass 的 campaign-level hard gate

唯一要注意的是：

- `--skip-beta-sweep` 會暫時跳過 `beta_sideslip` 這條 gate
- 這通常只適合 smoke / bounded search，不應該拿來當最終穩定 verdict

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

## 4.1 `Ainc` 到底是什麼

`Ainc` 是 AVL `SECTION` 資料行裡的 section incidence angle。

在 AVL 手冊裡，它的意思是：

- 一個 section 相對 surface reference 的 incidence / setting angle
- 以該 section 的 spanwise axis 為基準，影響 airfoil camber line 的 flow tangency boundary condition

最重要的點是：

**AVL 的 `Ainc` 不是把那個 section 的幾何真的整塊旋轉過去。**

AVL 手冊原文就有講：

- `Ainc` 用來修改 airfoil camber line 的 boundary condition
- 不直接旋轉 section geometry

所以如果你在 `.ft` 檔裡看到：

- `Alpha = -5 deg`
- 但主翼 section `Ainc = +3 deg`

正確解讀不是：

- 飛機真的必須整架以 `-5 deg` 幾何姿態巡航

而是比較接近：

- 這個 case 的 body/reference alpha 是 `-5 deg`
- 但主翼 section 本身還帶有 `+3 deg` 的 incidence 定義
- 再加上 cambered airfoil 的零升力角偏移，整機相對 body axis 的 `CL-alpha` 曲線就會整體左移

## 4.2 `blackcat_004` 的 `Ainc = +3 deg` 依據是什麼

目前 `blackcat_004` baseline 的主翼 `Ainc = +3 deg`，不是 AVL exporter 自己憑空加的。

它的來源是 canonical reference `.vsp3`：

- [blackcat_004_origin.vsp3](/Volumes/Samsung%20SSD/hpa-mdo/data/blackcat_004_origin.vsp3)

這份 `.vsp3` 的 `Main Wing` `XForm` 內目前有：

- `Y_Rel_Rotation = 3.0`
- `Y_Rotation = 3.0`

repo 現在的 VSP-first export contract 是：

1. `summarize_vsp_surfaces()` 從 `.vsp3` 讀出 `y_rotation_deg`
2. [vsp_geometry_parser.py](/Volumes/Samsung%20SSD/hpa-mdo/src/hpa_mdo/aero/vsp_geometry_parser.py) 目前把這個值視為 whole-surface incidence
3. `export_avl()` 再把它寫進各 section 的 `Ainc`

所以如果 canonical `.vsp3` 不變，重生出來的 baseline AVL 也會維持：

- `Main Wing` 各 section `Ainc = 3.0 deg`

## 4.3 之後看到 `Ainc` 時應該怎麼判斷

先分三層，不要混在一起看：

1. `body/reference Alpha`
   - 這是 AVL trim / fixed-alpha case 的整機 reference alpha
2. `section Ainc`
   - 這是 AVL section incidence 定義，不是實體幾何必然真的旋轉同樣角度
3. `local effective alpha`
   - 真正 section 感受到的有效攻角，還會受 downwash / induced angle / camber / 3D loading 影響

所以如果你之後看到 `CL(alpha=0)` 比直覺高很多，先檢查：

- baseline 是否帶了非零 `Ainc`
- airfoil 是否是高 camber low-Re section
- 你現在比較的是 `body alpha`，還是 2D section polar 的 `alpha`

不要直接把 AVL 的 `body alpha = 0` 當成：

- 2D airfoil polar 的 `alpha = 0`
- 或「主翼 chord line 正對來流」

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
    Path('/Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_origin.vsp3'),
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

## 13. 新增的 fixed-alpha hybrid screening mode

現在 coarse screening 多了一條明確的新路徑：

- `origin_vsp_fixed_alpha_corrector`

它的定位不是取代 AVL，也不是取代 finalist 的 VSPAERO panel confirm。
它的目的是：

- 用 origin `.vsp3` 跑一次 **fixed design alpha** 的 VSPAERO panel baseline
- 不為每個 dihedral candidate 重建 VSP 實體
- 直接用數學修正器估新的半翼載荷分佈
- 讓 jig shape / 結構主線可以先往下走

## 13.1 這條 mode 的角色分工

這條 mode 現在的分工是：

1. origin geometry truth
   - 一律用 [blackcat_004_origin.vsp3](/Volumes/Samsung%20SSD/hpa-mdo/data/blackcat_004_origin.vsp3)
2. baseline load owner
   - VSPAERO `panel`，固定 design alpha
3. candidate aerodynamic load owner
   - 不重建 candidate VSP
   - 改用 dihedral corrector 直接修正 origin baseline 的 `lift_per_span`
4. stability gate
   - 仍然由 AVL 快速做 Dutch roll / beta / spiral 類檢查
5. finalist confirm
   - shortlist 之後再走 candidate-owned VSP / VSPAERO rerun

所以這條 mode 的正確理解是：

- `VSPAERO panel` 給 baseline truth
- `dihedral corrector` 給 coarse structural loads
- `AVL` 給快速穩定性

不是：

- 用 AVL 直接給最終 drag truth
- 或讓每個 candidate 都先重建一份 VSP 幾何

## 13.1.1 fixed-alpha mode 下穩定性怎麼處理

即使 `origin_vsp_fixed_alpha_corrector` 不再為每個 candidate 反解 `L=W`，
穩定性檢查也**沒有拿掉**。

現在的 owner 分工是：

1. origin VSP panel baseline
   - 固定 design alpha
   - 給 baseline `lift_per_span`
2. dihedral corrector
   - 估 candidate 的 corrected structural load state
3. AVL
   - 仍然生成 candidate `.avl`
   - 仍然跑：
     - Dutch roll / `aero_status`
     - beta sweep (`Cn_beta`, `Cl_beta`, trim-at-beta)
     - spiral mode

所以 fixed-alpha mode 不是「只剩載荷，不看穩定性」；
它是：

- **氣動載荷 owner 換成 origin panel + 數學修正器**
- **穩定性 owner 保留在 AVL**

## 13.2 這條 mode 的數學 contract

目前這個 corrector 在固定 design alpha 下，只做一階的上反角垂直載荷修正：

`q_new(y) = q_origin(y) * [cos(gamma_new(y)) / cos(gamma_origin(y))]^2`

其中：

- `q_origin(y)` 來自 origin `.vsp3` 的 fixed-alpha panel baseline
- `gamma_origin(y)` 來自 origin baseline AVL 的主翼 section / segment slope
- `gamma_new(y)` 來自 candidate AVL 的主翼 section / segment slope

目前這條 contract **只修正**：

- `lift_per_span`
- 對應的 `cl`

目前這條 contract **不重新估**：

- `drag_per_span`
- `cd`
- `cm`

這三個量暫時保留在 origin fixed-alpha baseline 的 owner 上。

所以它的工程定位很清楚：

- 適合 jig shape / 結構載荷粗篩
- 不適合當 final drag / L/D truth

## 13.3 fixed alpha 的意思

這條 mode 的核心前提是：

- **design alpha 固定**
- **不反解 `L=W`**

也就是說，這裡的 pass / fail 條件不是：

- 為了撐起 `W`，candidate 最後 trim 到幾度

而是：

- 在你指定的 fixed design alpha 下
- 經過 dihedral corrector 後
- `total_lift >= W` 就算過

repo 目前預設的 CLI 入口是：

- `--fixed-design-alpha-deg 0.0`

但真正重點不是這個預設值，而是：

- 這條 mode 的 alpha 是使用者明確指定的設計條件
- 不是 outer loop 自己再去動它

## 13.3.1 自動 first-pass boundary refine

現在 `dihedral_sweep_campaign.py` 也支援：

- `--auto-first-pass-refine`

它的用途是：

- 先跑你給的 coarse multipliers
- 找第一個 `fail -> pass` 的 multiplier 區間
- 再自動在那段區間做 midpoint refine
- 直到：
  - 區間寬度小於 `--first-pass-refine-target-width`
  - 或到達 `--first-pass-refine-max-rounds`

這個功能判斷 `pass / fail` 用的是 **campaign 最終 gate**，
不是只看單一升力條件。

也就是說，它會一起尊重：

- aero stability
- aero performance
- beta / directional
- spiral
- inverse-design subprocess
- structural feasible / infeasible
- `max_tube_mass_kg`

所以這個 refine 找到的 boundary，語意上是：

**「在目前整個 campaign gate contract 下，第一個 pass 區間」**

## 13.4 和 `candidate_avl_spanwise` 的差異

`candidate_avl_spanwise`：

- 仍然是 AVL trim / outer-loop gate owner
- 需要 candidate-owned AVL AoA sweep
- `selected_cruise_aoa_deg` 仍然代表 outer-loop 選到的 load state

`origin_vsp_fixed_alpha_corrector`：

- 不解 outer-loop trim alpha
- `selected_cruise_aoa_deg` 只是沿用既有欄位名，實際上代表 **fixed design alpha**
- 只持有一個 fixed-alpha corrected load state

所以之後如果看到 summary / JSON 裡面：

- `source_mode = origin_vsp_fixed_alpha_corrector`

就要直接理解成：

- 這不是 trim-selected cruise AoA
- 這是 fixed design alpha contract

## 14. 這條 mode 目前的限制

這條 mode 故意保持保守：

1. 它是 screening surrogate，不是 final aerodynamic truth
2. 它只把 dihedral 對垂直升力的第一階影響帶進來
3. 它不會自動把 profile drag / viscous drag / trim drag 補真
4. 它不會為每個 candidate 解新的 VSPAERO alpha-CL

另外，因為這條 mode 本來就只有單一 fixed-alpha case，
direct inverse design 裡的 lightweight refresh 現在會進入：

- `single-case frozen refresh`

也就是：

- refresh step 仍可跑
- 但不再要求至少兩個 AoA case 做插值
- structural twist 也不會再把 alpha 當成自由度去回推新的 aero state

這是故意的，因為它比較符合這條 mode 的 fixed-alpha contract。

## 15. 實務上什麼時候用哪條線

如果你的目標是：

- 快速看上反角改動後，jig shape / 結構還有沒有戲
- 不想每個 candidate 都先重建 VSP

優先考慮：

- `origin_vsp_fixed_alpha_corrector`

如果你的目標是：

- 真的要看 candidate-owned geometry 在 VSPAERO 下的 aero case
- 要做 shortlist / finalist confirm

優先考慮：

- `candidate_rerun_vspaero`

如果你的目標是：

- 只想快速看 candidate 的 AVL spanwise lift shape 怎麼變
- 並且接受它還是跟 AVL trim / gate 綁在一起

可以考慮：

- `candidate_avl_spanwise`
