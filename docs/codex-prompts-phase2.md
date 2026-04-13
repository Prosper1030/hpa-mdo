# Codex Prompts — Phase 2 Dihedral Sweep

> 每個 prompt 獨立可執行。
> - Task 1 ✅ 已完成（wire 升級 dyneema_sk75）
> - Task 2 → Task 6 是主線 blocking chain
> - Task 3/4/5 可並行
> - Task 7 是新增的 VSP→AVL pipeline（非 blocking，為 M8 鋪路）

---

## Task 1：Wire 材料升級

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

目標：將升力鋼線材料從 steel_4130 升級為 dyneema_sk75。

背景：
- 目前 configs/blackcat_004.yaml 的 lift_wires.cable_material = "steel_4130"
- steel_4130 的 tensile_strength = 670 MPa，配上 2mm cable_diameter + 0.5 max_tension_fraction，allowable 只有 ~1052N
- 這遠低於真實 HPA 團隊使用的鋼線強度
- data/materials.yaml 已經有 dyneema_sk75（tensile_strength: 3500 MPa, tension_only: true）

具體修改：

1. configs/blackcat_004.yaml:
   - lift_wires.cable_material: "dyneema_sk75"
   - lift_wires.cable_diameter: 2.5e-3  （2.5mm Dyneema SK75 繩索）
   - lift_wires.max_tension_fraction: 0.40  （Dyneema 長期負載建議用 40% UTS）
   
2. configs/blackcat_004_multi.yaml:
   - 同上修改（如果有 lift_wires 區塊的話）

3. 另外，在 data/materials.yaml 新增一條 piano_wire 材料供未來選用：
   piano_wire_swpb:
     description: "High-carbon piano wire (SWP-B/JIS G3522) — flying wire"
     E: 206.0e9
     G: 79.3e9
     density: 7850.0
     tensile_strength: 2000.0e6
     yield_strength: 1700.0e6
     tension_only: true

不要修改任何 Python 程式碼。這是純 config 修改。

驗證：
- 確認 allowable tension 計算：π × (1.25e-3)² × 3500e6 × 0.40 ≈ 6872N
- 這遠大於 smoke test 中最大的 wire tension 3875N，margin 應為正

commit message: "feat: upgrade wire material from steel_4130 to dyneema_sk75 (6872N allowable)"
```

---

## Task 2：建立完整機體 AVL 模型

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

目標：建立一份包含 Wing + Elevator + Fin 的完整機體 AVL 模型檔案，讓 dihedral_sweep_campaign.py 能做真正的 Dutch Roll 穩定性分析。

背景：
- 目前的 dihedral sweep 用的是 wing-only fallback AVL，無法評估橫向穩定性
- VSP 檔案 (blackcat 004 wing only.vsp3) 其實包含三個元件：Main Wing、Elevator、Fin
- AVL binary 在 /usr/local/bin/avl (v3.40)

### 從 VSP 提取的幾何參數

**Main Wing（來自 configs/blackcat_004.yaml + VSP）：**
- full span: 33.0 m
- root chord: 1.39 m, tip chord: 0.47 m（線性漸縮）
- dihedral: root 0°, tip 6°（漸進式）
- spar at 25% chord
- 翼剖面：root Clark Y SM (t/c 11.7%), tip FX 76-MP-140 (t/c 14.0%)
- 對 AVL 用 NACA 2412（root, 近似 Clark Y）和 NACA 4414（tip, 近似 FX76）
  或直接用 flat plate（AVL 的氣動計算不太依賴翼形厚度，camber 比較重要）
  建議用 NACA camber line: root NACA 2412, tip NACA 2412（統一簡化）

**Elevator（水平尾翼）：**
- X_Location: 4.0 m（從機鼻）
- Y_Location: 0.0 m（對稱）
- Z_Location: 0.0 m
- 半翼展: 1.5 m（全展 3.0 m）
- chord: 0.8 m（root = tip，矩形）
- 左右對稱（VSP Sym_Planar_Flag = 2 = XZ plane）
- 翼形: NACA 0009（對稱翼形，用於尾翼）
- 有 elevator control surface（whole chord flap, ±20°）

**Fin（垂直尾翼）：**
- X_Location: 5.0 m
- Y_Location: 0.0 m
- Z_Location: -0.7 m（低於機身中心線）
- span: 2.4 m（向上延伸）
- root chord: 0.7 m（root = tip 近似，微漸縮）
- 繞 X 軸旋轉 90°（垂直面）
- 無左右對稱（單一垂直尾翼）
- 翼形: NACA 0009
- 有 rudder control surface（whole chord flap, ±25°）

### 飛行條件（AVL header 參數）：
- Sref = 33.0 × (1.39 + 0.47) / 2 ≈ 30.69 m²（或用 VSP 的 35.17 m²）
  → 用 config 的幾何算：wing.span × (root_chord + tip_chord) / 2 = 33.0 × 0.93 = 30.69
- Cref = MAC ≈ 0.98 m（梯形翼 MAC 公式）
- Bref = 33.0 m
- Xref, Yref, Zref = 0.25 × Cref, 0.0, 0.0（CG at quarter-MAC）

### Wing section 定義
用 7 個 section 來捕捉漸縮和 dihedral 漸變：
  y=0.0:   chord=1.39, Zle=0.0
  y=1.5:   chord=1.27, Zle=0.0  (dihedral ≈ 0°)
  y=4.5:   chord=1.05, Zle=0.12
  y=7.5:   chord=0.82, Zle=0.38
  y=10.5:  chord=0.68, Zle=0.77
  y=13.5:  chord=0.55, Zle=1.31
  y=16.5:  chord=0.47, Zle=1.73
  
  chord 按線性插值：chord(y) = 1.39 - (1.39-0.47)/16.5 × y
  Zle 按 progressive dihedral：大約 dihedral(y) = 6° × (y/16.5)，
  所以 Zle(y) ≈ ∫₀ʸ tan(6° × s/16.5) ds
  （你可以用離散累積計算，不需要精確到解析解）

### 具體要求

1. 建立 `data/blackcat_004_full.avl`
   - YSYM = 1（左右對稱，只定義右半 wing 和 elevator）
   - Wing: COMPONENT 1, 7 sections as above, Nchord=12, Nspan=30
   - Elevator: COMPONENT 2, 2 sections (root/tip), Nchord=8, Nspan=12
   - Fin: COMPONENT 3, 2 sections (root/tip), Nchord=8, Nspan=12
   - 對 Elevator 加 CONTROL 行：elevator deflection, 全弦
   - 對 Fin 加 CONTROL 行：rudder deflection, 全弦

2. 修改 `scripts/dihedral_sweep_campaign.py`:
   - 加一個 CLI 選項 `--base-avl` 預設值改為 `data/blackcat_004_full.avl`
   - 當 `--base-avl` 指向這個完整模型時，不再觸發 `--generate-wing-only-avl-fallback`
   - dihedral scaling 邏輯只修改 Wing surface 的 SECTION Zle，不動 Elevator 和 Fin
     → 需要在 scaling 函式中識別當前在哪個 SURFACE，只對 Wing surface 做 Z 乘法

3. 驗證：
   - 用 AVL 手動載入 data/blackcat_004_full.avl 確認可以跑 mode analysis
   - 跑一次 `avl` 確認能輸出有 lateral oscillatory mode 的 .st 檔案
   - 至少能看到非零 dutch_roll_imag

注意事項：
- 遵守 CLAUDE.md 規則：所有工程參數從 config 讀取
- AVL 的 section 資料行格式：Xle  Yle  Zle  Chord  Ainc
- Wing 的 SECTION 之間 dihedral 由 Zle 的差異隱含定義（AVL 不用 dihedral 關鍵字）
- 所有路徑使用 pathlib.Path
- 行長度 <= 100 字元

commit message: "feat: add full-body AVL model with elevator and fin for Dutch Roll analysis"
```

---

## Task 3：Sweep Error Handling 改善

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

目標：讓 dihedral_sweep_campaign.py 在單一 case 的 inverse-design subprocess 失敗時，不中斷整個 sweep。

目前行為（約 L484）：
if proc.returncode != 0 or not summary_path.exists():
    raise RuntimeError(...)

這導致一個 multiplier 炸掉就全停。

修改為：
1. catch subprocess 失敗，記錄錯誤到 SweepResult dataclass 的新欄位（例如 error_message: str | None）
2. 在 summary CSV/JSON 中標記該 case 為 "structural_failed"
3. 繼續跑剩餘 multiplier
4. sweep 結束後，如果有失敗 case，印出 WARNING 彙總（哪些 multiplier 失敗、原因）
5. 加一個 --strict 旗標：若設定，則保持原本的「一個炸全停」行為

不要改動 inverse-design 內圈本身。只改 dihedral_sweep_campaign.py 的外圈呼叫邏輯。

commit message: "fix: collect per-case errors in dihedral sweep instead of aborting"
```

---

## Task 4：Loaded-Shape Tolerance 進 Config

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

目標：把 inverse_design.py 中硬編碼的 loaded-shape 容差移到 config。

目前（inverse_design.py 約 L476-477）：
loaded_shape_main_z_tol_m: float = 0.025   # 25 mm
loaded_shape_twist_tol_deg: float = 0.15    # 0.15 degrees

修改：

1. 在 core/config.py 的適當位置（可能在 SolverConfig 或新建一個 InverseDesignConfig）
   加入：
   loaded_shape_z_tol_m: float = 0.025
   loaded_shape_twist_tol_deg: float = 0.15

2. 在 configs/blackcat_004.yaml 的 solver: 區塊（或新建 inverse_design: 區塊）
   加入對應欄位（用相同的預設值）

3. 在 configs/blackcat_004_multi.yaml 做同樣修改（如果有相關區塊）

4. 修改 inverse_design.py 讓它從 config 讀取，而不是用 hardcoded default

5. 在 scripts/direct_dual_beam_inverse_design.py 如果有 CLI override，
   也加 --loaded-shape-z-tol 和 --loaded-shape-twist-tol 參數

不改預設值，只改數值的來源。

commit message: "refactor: move loaded-shape tolerances from hardcode to config"
```

---

## Task 5：.lod Parser Component Filter

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

目標：在 VSPAeroParser 加入 optional component filter。

背景：
- 目前 src/hpa_mdo/aero/vsp_aero.py 的 _parse_one_case() 讀取所有 strip 不分 component
- .lod 檔案的第一欄（index 0）是 component ID（例如 "1" = Wing）
- 目前的 .lod 只有 wing strips 所以沒問題，但如果未來跑多元件 VSP 會出錯

修改：

1. VSPAeroParser.__init__() 加一個 optional 參數：
   component_ids: list[int] | None = None

2. 在 _parse_one_case() 中，parse 完 DataFrame 後：
   - 如果 component_ids is not None，filter rows where column 0 in component_ids
   - 如果 component_ids is None，保持原行為（全部讀取）

3. 加一個 WARNING log：
   - 當 component_ids is None 且偵測到多個不同的 component ID 時
   - 警告使用者載荷可能混合了多個元件

4. 在 tests/test_vsp_aero.py（或新建）加一個簡單的 unit test：
   - 用 mock .lod 資料驗證 filter 行為

不要修改現有的呼叫端（呼叫端不傳 component_ids 就是 None = 原行為）。

commit message: "feat: add optional component filter to VSPAeroParser"
```

---

## Task 6：重跑 Dihedral Sweep（Task 1+2 完成後）

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

前置條件：Task 1（wire 材料升級）和 Task 2（完整 .avl）已完成。

目標：用升級後的設定重跑 dihedral sweep campaign，產出有工程意義的結果。

步驟：

1. 確認 wire 設定：
   - configs/blackcat_004.yaml 的 lift_wires.cable_material 應為 "dyneema_sk75"
   - cable_diameter 應為 2.5e-3
   
2. 確認 AVL 模型：
   - data/blackcat_004_full.avl 存在且包含 Wing + Elevator + Fin

3. 跑 sweep：
   ./.venv/bin/python scripts/dihedral_sweep_campaign.py \
     --config configs/blackcat_004.yaml \
     --base-avl data/blackcat_004_full.avl \
     --multipliers 1.0 1.25 1.5 1.75 2.0 2.25 2.5 \
     --output-dir output/dihedral_sweep_phase2

   （如果 CLI 參數名稱不完全一樣，請根據實際程式碼調整）

4. 檢查結果：
   a. dutch_roll_found 是否為 true（至少部分 case）
   b. wire margin 是否翻正
   c. mass vs multiplier 趨勢
   d. 是否有任何 case 被標記 aero-infeasible

5. 輸出：
   - 把 dihedral_sweep_summary.csv 的關鍵欄位整理成表格
   - 特別標出：
     - 最輕且 aero-feasible 的 case
     - wire margin 最大的 case
     - Dutch Roll damping 最強的 case
   - 如果有任何 case 失敗，說明原因

6. 如果 AVL mode parsing 仍然找不到 Dutch Roll：
   - 檢查 AVL stdout log，看 mode 輸出格式
   - 可能需要調整 parsing regex 或 inertia 參數
   - 報告問題但不要自行大改 parser

不要修改核心程式碼。只跑 sweep 並報告結果。

如果跑不過，報告卡在哪裡、錯誤訊息是什麼。
```

---

---

## Task 7e：氣動性能門檻檢查（Aero Performance Gates）

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

目標：在 dihedral_sweep_campaign.py 的外圈加入氣動性能門檻檢查，
確保每個 dihedral multiplier 對應的翼面仍能產生足夠升力並維持合理 L/D。

背景：
- 目前 dihedral sweep 只做穩定性濾網（Dutch Roll），沒有檢查氣動性能
- 增大 dihedral 可能降低有效投影面積、改變 span loading、降低 L/D
- 最小升力門檻：100 kg × 9.81 = 981 N（全機重量）
- L/D 門檻：≥ 25（飛行員持續輸出功率 ~250W，P = W×V/L/D）
- 飛行條件：V = 6.5 m/s，ρ = 1.225 kg/m³（來自 config）

### 物理推導

在巡航速度 V 下，所需 CL：
  CL_required = W / (0.5 × ρ × V² × S_ref)
  W = 100 kg × 9.81 = 981 N
  q = 0.5 × 1.225 × 6.5² ≈ 25.88 Pa
  S_ref ≈ 30.69 m²
  CL_required ≈ 1.24

對 AVL trim 來說，如果 AVL 能找到 trim 解（AoA 使 CL = CL_required），
就代表飛機能飛。如果 CL_required 超過 CL_max（失速），就不行。

AVL 能做的：
1. 跑 trim case：指定 CL，讓 AVL 解出 AoA 和 CD
2. 從輸出提取：CL, CDi (induced drag), AoA, span efficiency e
3. 計算：L/D_inviscid = CL / CDi（保守估計，不含 profile drag）
4. 或加估計 profile drag：CD_total ≈ CDi + CD_profile（~0.008-0.012 for HPA）

### 實作要求

1. **在 dihedral_sweep_campaign.py 加入 AVL trim 分析**

   在現有的 AVL stability 分析之後（或同時），加一個 AVL trim run：
   
   AVL 命令序列（trim at specified CL）：
   ```
   OPER
   A A {alpha}      ! 或用 C1 設定 CL constraint
   X                ! execute
   ST               ! print total forces
   ```
   
   或更好的方法：用 AVL 的 constraint 系統：
   ```
   OPER
   C1               ! constrain CL
   {CL_required}    ! target CL value
   X                ! execute — AVL 會自動找到對應的 AoA
   FT               ! print total forces to file
   ```

   從 AVL 輸出解析：
   - CLtot (total lift coefficient)
   - CDind (induced drag coefficient)  
   - e (Oswald/span efficiency)
   - Alpha (trim angle of attack)

2. **計算 aero performance metrics**

   在 SweepResult dataclass 加入新欄位：
   - cl_trim: float | None      # trim CL
   - cd_induced: float | None   # induced drag coeff
   - cd_total_est: float | None # estimated total CD (CDi + CD_profile)
   - ld_ratio: float | None     # L/D = CL / CD_total_est
   - aoa_trim_deg: float | None # trim AoA
   - span_efficiency: float | None
   - lift_total_n: float | None  # actual lift at cruise
   - aero_power_w: float | None  # P = D × V = W × V / (L/D)

3. **新增 config 參數**

   在 configs/blackcat_004.yaml 加入：
   ```yaml
   # ── Aero Performance Gates ──────────────────────────
   aero_gates:
     min_lift_kg: 100.0           # minimum total lift [kg]
     min_ld_ratio: 25.0           # minimum L/D ratio
     cd_profile_estimate: 0.010   # estimated profile drag coefficient
     max_trim_aoa_deg: 12.0       # maximum trim AoA (near stall)
   ```

   在 core/config.py 加對應的 Pydantic model：
   ```python
   class AeroGatesConfig(BaseModel):
       min_lift_kg: float = 100.0
       min_ld_ratio: float = 25.0
       cd_profile_estimate: float = 0.010
       max_trim_aoa_deg: float = 12.0
   ```

4. **在 sweep 邏輯中加入 gate 判斷**

   在穩定性檢查之後，加入：
   ```
   if aoa_trim > max_trim_aoa_deg:
       aero_feasible = False
       reason = "trim_aoa_exceeds_limit"
   if ld_ratio < min_ld_ratio:
       aero_feasible = False
       reason = "ld_below_minimum"
   if lift_total < min_lift_kg * 9.81:
       aero_feasible = False  
       reason = "insufficient_lift"
   ```

5. **更新 summary CSV/JSON**

   在輸出中加入所有新欄位：
   - cl_trim, cd_induced, cd_total_est, ld_ratio
   - aoa_trim_deg, span_efficiency
   - lift_total_n, aero_power_w
   - aero_performance_feasible (bool)
   - aero_performance_reason (string)

6. **CLI 參數**

   加入：
   --min-lift-kg (default from config)
   --min-ld-ratio (default from config)
   --skip-aero-gates (跳過性能檢查，只做穩定性)

### AVL trim 命令的具體寫法

用 subprocess 跟 AVL 互動的命令序列（pipe stdin）：
```
OPER
!
C1  {cl_required}
!
X
FT
{trim_output_file}

QUIT
```

或者更穩健的方法：
用 .run 檔案（batch mode）寫好所有命令，然後：
```
avl < commands.run > avl_trim_stdout.log
```

解析 FT 輸出（force totals）：
- 找 "CLtot" 行 → 提取數值
- 找 "CDind" 行 → 提取數值
- 找 "e" 行 → 提取 span efficiency
- 找 "Alpha" 行 → 提取 trim AoA

### 注意事項

- 遵守 CLAUDE.md：所有門檻值從 config 讀取，不硬編碼
- CL_required 用 config 的 weight.max_takeoff_kg 和 flight 條件計算
- 如果 AVL trim 不收斂（AoA > 15° 還沒 converge），標記為 infeasible
- profile drag 估計值 0.010 是 HPA 的典型值（Drela 論文）
- L/D gate 的物理意義：飛行員持續功率 250W，V=6.5 m/s，
  P = W×V/(L/D) → L/D_min = 981×6.5/250 ≈ 25.5
- 所有路徑用 pathlib.Path
- 行長度 <= 100 字元

commit message: "feat: add aero performance gates (min lift, L/D) to dihedral sweep"
```

---

## Task 7f：Phase-2 Dihedral Sweep Re-run

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

前置條件：Task 7e（aero performance gates）已完成。

目標：用完整設定（full-body AVL + dyneema wire + aero gates）重跑 sweep，
產出第一份真正有工程意義的多維 feasibility 報告。

步驟：

1. 跑 sweep：
   ./.venv/bin/python scripts/dihedral_sweep_campaign.py \
     --config configs/blackcat_004.yaml \
     --base-avl data/blackcat_004_full.avl \
     --multipliers 1.0 1.25 1.5 1.75 2.0 2.25 2.5 \
     --output-dir output/dihedral_sweep_phase2

2. 檢查結果，特別關注：
   a. dutch_roll_found — 至少部分 case 應為 true
   b. wire margin — 應全部為正（dyneema allowable ≈ 6872N）
   c. aero_performance_feasible — 是否有 case 被 L/D 或 lift 淘汰
   d. mass vs multiplier 趨勢
   e. L/D vs multiplier 趨勢
   f. stability damping vs multiplier 趨勢

3. 輸出分析表格：

   | multiplier | mass_kg | wire_margin | dutch_roll_damping |
   |            | cl_trim | ld_ratio | aero_feasible | overall |

4. 標出：
   - 最輕且所有 gates 都通過的 case
   - L/D 最高的 case
   - Dutch Roll damping 最強的 case
   - 如果有 trade-off（例如最輕但 L/D 邊界），明確標示

5. 如果有任何 gate 失敗，說明原因和物理解釋

不要修改核心程式碼。如果跑不過，報告卡在哪裡。

commit message: "chore: phase-2 dihedral sweep with full aero gates"
```

---

## Task 8：VSP3→AVL 自動化 Pipeline（M8）— 已完成 ✅

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。

目標：建立一個可以從 VSP3 XML 檔案自動提取幾何、產生 AVL 模型的 pipeline。
這是 Milestone 8 的基礎設施，讓未來不需要手動建 .avl 檔案。

背景：
- VSP3 檔案是 XML 格式，包含所有飛機元件的幾何定義
- 目前 repo 中沒有任何 VSP3 XML parser
- 目前的 vsp_aero.py 只讀 .lod/.polar（VSPAero 輸出），不讀 .vsp3 本身
- 目前 Aircraft dataclass（core/aircraft.py）只有 WingGeometry，沒有 tail/fin
- 目前的 vsp_builder.py 只寫 VSP 檔案（透過 openvsp API），不讀

已知 VSP3 檔案結構（從 blackcat 004 wing only.vsp3）：
- <Name>Main Wing</Name> — 主翼，6 個 XSec sections
- <Name>Elevator</Name> — 水平尾翼，X=4.0m, Y=0, Z=0, span=3.0m, chord=0.8m
- <Name>Fin</Name> — 垂直尾翼，X=5.0m, Y=0, Z=-0.7m, X_Rotation=90°, span=2.4m, chord=0.7m

### 實作要求

1. **新建 `src/hpa_mdo/aero/vsp_geometry_parser.py`**

   class VSPGeometryParser:
       """Parse OpenVSP .vsp3 XML files to extract all surface geometry."""
       
       def __init__(self, vsp3_path: Path):
           ...
       
       def parse(self) -> VSPGeometryModel:
           """Parse all wing/tail/fin surfaces from the XML."""
           ...

   @dataclass
   class VSPSurface:
       name: str                    # e.g., "Main Wing", "Elevator", "Fin"
       surface_type: str            # "wing", "h_stab", "v_fin"
       origin: tuple[float, float, float]  # X, Y, Z location
       rotation: tuple[float, float, float]  # X, Y, Z rotation [deg]
       symmetry: str                # "xz" (左右對稱) or "none"
       sections: list[VSPSection]   # ordered root→tip
   
   @dataclass
   class VSPSection:
       x_le: float                  # leading edge X (local)
       y_le: float                  # leading edge Y (local)
       z_le: float                  # leading edge Z (local)
       chord: float
       twist: float                 # incidence [deg]
       airfoil: str                 # e.g., "NACA 2412" or name
   
   @dataclass
   class VSPGeometryModel:
       surfaces: list[VSPSurface]
       
       def get_wing(self) -> VSPSurface | None: ...
       def get_h_stab(self) -> VSPSurface | None: ...
       def get_v_fin(self) -> VSPSurface | None: ...

   VSP3 XML 中，每個元件的結構大致是：
   - <ParmContainer> → <Name> = component name
   - <XForm> → X/Y/Z_Location, X/Y/Z_Rotation
   - <Sym> → Sym_Planar_Flag (2 = XZ plane symmetry)
   - <WingGeom> → section data 在 <XSec_Surf> 下的多個 <XSec> 裡
   - 每個 <XSec> 有 span, chord, twist, sweep, dihedral 等參數
   
   用 xml.etree.ElementTree 解析。

2. **新建 `src/hpa_mdo/aero/avl_exporter.py`**

   def export_avl(
       geometry: VSPGeometryModel,
       output_path: Path,
       *,
       sref: float | None = None,
       cref: float | None = None,
       bref: float | None = None,
       xref: float = 0.0,
       yref: float = 0.0,
       zref: float = 0.0,
       mach: float = 0.0,
   ) -> Path:
       """Export VSPGeometryModel to AVL format .avl file."""

   功能：
   - 對每個 VSPSurface 產生一個 SURFACE block
   - 每個 VSPSection 產生一個 SECTION block
   - 處理 symmetry（YSYM=1 for XZ plane）
   - 對 h_stab 加 CONTROL elevator（full-chord, ±20°）
   - 對 v_fin 加 CONTROL rudder（full-chord, ±25°）
   - 自動計算 Sref/Cref/Bref 如果未提供

3. **在 `scripts/` 加一個 utility script `vsp_to_avl.py`**

   用法：
   python scripts/vsp_to_avl.py \
     --vsp3 "/path/to/model.vsp3" \
     --output data/blackcat_004_full.avl

4. **單元測試 `tests/test_vsp_geometry_parser.py`**
   - 用一個小型 mock VSP3 XML 測試 parser
   - 驗證 surface 數量、座標、chord 等

注意事項：
- 遵守 CLAUDE.md 規則
- from __future__ import annotations
- 所有路徑用 pathlib.Path
- 行長度 <= 100 字元
- 不需要跟現有 vsp_builder.py 整合（那是 write，這是 read）
- 不改動現有的任何 code，純新增

commit message: "feat: add VSP3 XML geometry parser and AVL exporter (M8 foundation)"
```

---

## 任務完成狀態

| Task | 說明 | 狀態 |
|------|------|------|
| 1 | Wire 材料升級 | ✅ |
| 2 | Full-body AVL | ✅ |
| 3 | Error handling | ✅ |
| 4 | Tolerance 進 config | ✅ |
| 5 | .lod component filter | ✅ |
| 7 (M8) | VSP→AVL pipeline | ✅ |
| **7e** | **Aero performance gates** | **⏭️ NEXT** |
| **7f** | **Phase-2 sweep re-run** | **⏭️ 等 7e** |

## 下一步執行順序

```
Task 7e (aero gates) → Task 7f (re-run sweep) → 分析結果 → 決策
```

Task 7e 是當前唯一 blocker。完成後直接跑 7f。
