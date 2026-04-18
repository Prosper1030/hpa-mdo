# Benchmark Contract Draft

## Purpose

這份文件的目的只有一個：把「最小可行外部基準」先鎖成一個可執行的合約，避免驗證範圍繼續膨脹。

這份合約目前服務的是：

- external benchmark case definition
- solver-to-solver / solver-to-test 的 apples-to-apples 對照
- 與目前已拍板決策相容

這份合約**不**服務的是：

- 把 Track C 升格成 external validation truth
- 重新開啟 ASWING / SHARPy / 自研 trim solver 研究分支
- 取代 drawing-ready baseline package

## Project Decisions Already Locked

- `drawing-ready baseline package` 已正式承認為 `done enough`
- `Track C` 正式停在 `local structural spot-check`
- `ASWING / SHARPy / 自研替代方案` 全部延後到 benchmark contract 凍結之後
- 目前先採 `defensive design`
- 建議目前版主承力結構靜態安全係數：`FoS = 2.0`

## Case ID

- `BC004-BMK-001`

## Scope

### Geometry Scope

第一版 benchmark case 只取：

- `單側半翼承力總成`
- `主梁 + 後梁`
- `必要 root 約束區`
- `必要 wire support / attachment 對照點`

第一版 benchmark case 明確**不包含**：

- skin
- ribs
- fairing
- 非承力外形件
- 未在主線模型中被正式承認為 stiffness / mass truth 的局部補強細節
- 工廠層級 ply drop-off / overlap / splice 細節

幾何 authority 建議先鎖為：

- `drawing-ready baseline package` 的 `spar_jig_shape.step`

也就是說，第一版 benchmark 不追 full-aircraft，也不追 full composite detail，只追：

- 同一份半翼承力幾何
- 同一份主 / 後梁 load path

### Section / Material Scope

第一版 benchmark 先鎖在「結構等效層」，不要直接跳到完整複材製程層。

建議鎖定：

- section representation: `equivalent shell / beam structural contract`
- material representation: `同一組等效材料常數`
- wall / section authority: `以 current release baseline 為準`

建議值：

- `E = 230 GPa`
- `nu = 0.27`
- `rho = 1600 kg/m^3`

若 benchmark case 要直接對 discrete baseline：

- 建議把 `wall thickness authority` 鎖成 current release baseline 的值
- 目前建議值：`1.0 mm`

如果第一版只想先用最小可行 case 跑通，也可暫時允許：

- `0.8 mm` shell inspection deck 作為 pre-freeze local rehearsal

但正式 external benchmark 凍結後，建議不要再混用不同 thickness contract。

## Boundary Condition Scope

第一版 BC 必須明確、可重播、不可各自解讀。

建議鎖定如下：

- `ROOT clamp patch`
  - 位置：`y = 0` 根部截面
  - 自由度：`Ux = 0, Uy = 0, Uz = 0`
  - 若 solver 有 rotation DOF，第一版不額外加 rotation gate；只要求 translation BC ownership 一致

- `WIRE support patch`
  - 位置：`y = 7.550847 m`
  - 自由度：`Uz = 0`
  - 第一版不引入 pretension、不引入 cable geometric nonlinearity

第一版 benchmark 的 BC 原則：

- 先做 `prescribed support contract`
- 不做 free-trim
- 不做 solver 自己猜的 support interpretation

## Load Scope

第一版 load case 先鎖成一個最單純、最可比較的代表性靜態載重。

建議 case：

- `1G cruise representative static load`
- `prescribed nodal / distributed vertical load`
- `不包含 trim solver ownership`
- `不包含自由氣彈耦合`

建議 load ownership：

- main spar 與 rear spar 的展向 vertical load 必須分開提供
- 由同一份 frozen load file 統一供應
- total vertical load 以該 load file 積分 / 加總為 authority

建議 frozen load file schema：

```csv
y_m,main_x_m,main_z_m,main_fz_n,rear_x_m,rear_z_m,rear_fz_n
```

建議第一版 total half-wing vertical load authority：

- `|Total Fz| = 817.782 N`

第一版 benchmark 明確**不包含**：

- free-trim
- dynamic load
- gust
- nonlinear cable pretension solve
- distributed torque ownership 爭議

如果後續要擴大，應該另開下一版 contract，不要在 `BC004-BMK-001` 裡偷加。

## Compare Metrics

第一版只看 4 個量：

1. `Mass (half-wing structural mass)`
2. `Total Reaction |Fz|`
3. `Tip Deflection`
4. `Tip Twist`

### Metric Definitions

#### 1. Mass

定義：

- AI side：`half-wing structural mass`
- CalculiX side：由 benchmark deck 幾何 + section + density 計算出的 `half-wing structural mass`

建議比較量：

- `mass_half_wing_kg`

#### 2. Total Reaction

定義：

- 所有 benchmark 支撐點的 `|Fz|` 總和
- 以 frozen load contract 的總載重為 AI / reference authority

建議比較量：

- `total_reaction_fz_n`

#### 3. Tip Deflection

定義：

- `main spar tip probe` 的 `|Uz|`

建議 probe 位置先鎖為：

- `main_tip_probe_m = [0.12375, 16.50000, 0.891232]`

建議比較量：

- `tip_deflection_m`

#### 4. Tip Twist

定義：

- 在同一個 tip station，用 `main tip probe` 與 `rear tip probe` 的垂直位移差估算局部截面 twist
- 計算式：

```text
tip_twist_deg = atan2(uz_rear - uz_main, x_rear - x_main) * 180 / pi
```

建議 rear probe 位置先鎖為：

- `rear_tip_probe_m = [0.31450, 16.50000, 0.890333]`

建議比較量：

- `tip_twist_deg`

## Pass Line

第一版建議 pass line 如下：

| Metric | Pass Line | Note |
|---|---:|---|
| Mass (half-wing) | `<= 5.0%` | 先看 structural mass，不看全機 operating mass |
| Total Reaction \|Fz\| | `<= 1.0%` | 這是最硬的 contract 指標 |
| Tip Deflection | `<= 5.0%` | 以 main tip probe 的 `|Uz|` 為準 |
| Tip Twist | `<= 10.0%` 或 `<= 0.20 deg` | 兩者取較寬者，避免小角度百分比失真 |

第一版總判定建議：

- 4 項全部過線：`PASS`
- 任 1 項未過線：`FAIL`

## Required Artifacts

建議第一版 benchmark case package 至少包含：

- `geometry/spar_jig_shape.step`
- `loads/half_wing_1g.csv`
- `ai_metrics/discrete_layup_final_design.json`
- `ccx/spar_jig_shape_static.inp`
- `ccx/spar_jig_shape_static.dat`
- `ccx/spar_jig_shape_static.frd`

## Validation Script Contract

配套腳本建議讀以下資訊：

- AI metrics：
  - `discrete_layup_final_design.json`
  - 讀取：
    - `discrete_full_wing_mass_kg`
    - `structural_recheck.tip_deflection_m`
    - `structural_recheck.twist_max_deg`

- CalculiX metrics：
  - `.inp`：計算 half-wing structural mass
  - `.dat`：讀取 total support reaction
  - `.frd`：讀取 tip deflection 與 tip twist probes

## Recommended Initial CLI

```bash
python scripts/validate_benchmark_contract.py \
  --ai-json output/blackcat_004/discrete_layup_final_design.json \
  --ccx-inp output/blackcat_004/hifi_support_reaction_rerun_20260418/spar_jig_shape_static.inp \
  --ccx-dat output/blackcat_004/hifi_support_reaction_rerun_20260418/spar_jig_shape_static.dat \
  --ccx-frd output/blackcat_004/hifi_support_reaction_rerun_20260418/spar_jig_shape_static.frd \
  --reaction-reference-n 817.782 \
  --main-tip-probe 0.12375,16.50000,0.891232 \
  --rear-tip-probe 0.31450,16.50000,0.890333
```

## Stop Rule

`BC004-BMK-001` 一旦凍結後，就不要再做下面這些事：

- 偷換 geometry
- 偷換 BC
- 偷換 load ownership
- 一邊改 solver deck，一邊還拿同一份 pass line 說它是同一個 case

任何新增內容都應該：

- 另開 `BC004-BMK-002`

這樣 external benchmark 才會是 contract，不會又變成 moving target。
