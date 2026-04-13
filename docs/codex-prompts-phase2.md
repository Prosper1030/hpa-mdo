# Codex Prompts — Phase 2 Dihedral Sweep

> 每個 prompt 獨立可執行；目前本文件對應的 Phase 2 主線已完成。
> - Task 1 → Task 7i：全部 ✅
> - Task 8（M8 foundation）：8a-8c ✅，8d 尚待整合進 YAML/runtime schema
> - **建議下一份 prompt：9a fine dihedral sweep（step 0.1，extend to 3.5×）**
> - **可並行補完：8d config schema extension（tail/fin 進 YAML/runtime model）**

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

## Task 6：重跑 Dihedral Sweep（Task 1+2 完成後）— 已完成 ✅

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

## Task 7e：氣動性能門檻檢查（Aero Performance Gates）— 已完成 ✅

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

## Task 7f：Phase-2 Dihedral Sweep Re-run — 已完成 ✅

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

## Task 7g：Progressive Dihedral Scaling（非均勻 Z 縮放）— 已完成 ✅

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

目標：將 dihedral sweep 中的「均勻 Z 縮放」替換為「漸進式 dihedral 縮放」，
讓翼尖段承擔更多 dihedral，翼根段幾乎不動。

### 為什麼需要改

目前程式碼在兩處做均勻 Z 乘法：

1. scripts/dihedral_sweep_campaign.py 的 scale_avl_dihedral_text():
   values[2] *= float(multiplier)   # 所有 section 的 Zle 乘以相同倍率

2. src/hpa_mdo/structure/inverse_design.py 的 build_target_loaded_shape():
   main_nodes_m[:, 2] *= scale       # 所有結構節點的 Z 乘以相同倍率

物理上 dihedral 是角度，不是位移。均勻 Z 乘法等於把翼根也抬高，
但 HPA（包括 Daedalus）的翼根段幾乎水平，dihedral 集中在外段。

### 正確做法

用 span-weighted scaling function：

  Z_new(η) = Z_base(η) × [1 + (multiplier - 1) × η^p]

其中：
  η = y / half_span（0 at root, 1 at tip）
  p = dihedral_exponent（config 參數，default = 1.0）
  - p = 0: 均勻（舊行為）
  - p = 1: 線性漸進（翼根不動，翼尖效果 = multiplier）
  - p = 2: 二次漸進（翼尖更強調）

### 具體修改

1. **configs/blackcat_004.yaml** — 在 wing: 區塊加入：
   ```yaml
   dihedral_scaling_exponent: 1.0  # progressive dihedral: 0=uniform, 1=linear, 2=quadratic
   ```

2. **core/config.py** — 在 WingConfig 加入：
   ```python
   dihedral_scaling_exponent: float = 1.0
   ```

3. **src/hpa_mdo/structure/inverse_design.py** — 修改 build_target_loaded_shape():

   目前簽名：
   def build_target_loaded_shape(*, model, z_scale=1.0) -> StructuralNodeShape

   改為：
   def build_target_loaded_shape(
       *, model, z_scale=1.0, dihedral_exponent=1.0,
   ) -> StructuralNodeShape

   內部邏輯從：
     main_nodes_m[:, 2] *= scale
     rear_nodes_m[:, 2] *= scale

   改為：
     half_span = float(model.nodes_main_m[-1, 1])  # 最外側 Y 座標
     if half_span > 0:
         eta_main = np.clip(model.nodes_main_m[:, 1] / half_span, 0.0, 1.0)
         eta_rear = np.clip(model.nodes_rear_m[:, 1] / half_span, 0.0, 1.0)
     else:
         eta_main = np.zeros(len(model.nodes_main_m))
         eta_rear = np.zeros(len(model.nodes_rear_m))

     exp = float(dihedral_exponent)
     factor_main = 1.0 + (scale - 1.0) * eta_main ** exp
     factor_rear = 1.0 + (scale - 1.0) * eta_rear ** exp
     main_nodes_m[:, 2] *= factor_main
     rear_nodes_m[:, 2] *= factor_rear

   當 scale=1.0 時 factor=1.0（不變），行為完全向後相容。
   當 exponent=0 時退化為 factor = scale（舊的均勻行為）。

4. **scripts/dihedral_sweep_campaign.py** — 修改 scale_avl_dihedral_text():

   目前簽名：
   def scale_avl_dihedral_text(text, *, multiplier, target_surface_names=("wing",))

   改為：
   def scale_avl_dihedral_text(
       text, *, multiplier, target_surface_names=("wing",),
       half_span=16.5, dihedral_exponent=1.0,
   )

   內部邏輯從：
     values[2] *= float(multiplier)

   改為：
     y_section = abs(values[1])  # AVL section 的 Yle
     eta = min(y_section / half_span, 1.0) if half_span > 0 else 0.0
     local_factor = 1.0 + (float(multiplier) - 1.0) * eta ** dihedral_exponent
     values[2] *= local_factor

   注意：AVL section data 行格式是 Xle Yle Zle Chord Ainc，
   所以 values[1] 是 Yle（span position），values[2] 是 Zle。

5. **呼叫端更新** — 在 dihedral_sweep_campaign.py 的 main loop 中：
   - 從 config 讀取 cfg.wing.dihedral_scaling_exponent
   - 傳給 scale_avl_dihedral_text() 的 dihedral_exponent 參數
   - 傳給 inverse design subprocess 的 --z-scale 和 --dihedral-exponent 參數

   在 direct_dual_beam_inverse_design.py 中：
   - 加 CLI 參數 --dihedral-exponent (default 1.0)
   - 傳給 build_target_loaded_shape() 的 dihedral_exponent 參數

6. **在 scale_avl_dihedral_text 呼叫處傳入 half_span**:
   half_span 應從 config 計算：cfg.wing.span / 2.0

### 驗證

- 用 multiplier=1.0 跑：結果必須和修改前完全一致（factor=1.0）
- 用 multiplier=2.0, exponent=0 跑：結果必須和舊的均勻縮放一致
- 用 multiplier=2.0, exponent=1 跑：翼根 Z 不變，翼尖 Z ≈ 2× 原值
- 印出 3-5 個 section 的 (y, Z_old, Z_new, local_factor) 供人工核對

### 注意事項

- 遵守 CLAUDE.md：新參數必須同時進 YAML + Pydantic model
- from __future__ import annotations
- 行長度 <= 100 字元
- 不要改動 AVL stability parsing、trim 邏輯、或 wire 計算
- half_span 如果從 config 來，用 cfg.wing.span / 2.0
- build_target_loaded_shape 的 model.nodes_main_m 是 (n_nodes, 3) ndarray，
  column 1 是 Y（展向位置），column 2 是 Z（vertical）

commit message: "feat: progressive dihedral scaling with span-weighted exponent (Task 7g)"
```

---

## Task 7h：Loaded Shape STEP Export + Per-Node Deflection Output — 已完成 ✅

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

目標：在 inverse design 的輸出中加入兩項目前缺少的產物：
(A) loaded shape 的 STEP 幾何檔案（與現有 jig_shape.step 對應）
(B) 每個節點的撓度 CSV 檔案

### 背景

目前 scripts/direct_dual_beam_inverse_design.py 的 _export_artifacts() 函式
（約 L2470-2530）已經做了：
  ✅ target_shape_spar_data.csv（target loaded shape 的 beam CSV）
  ✅ jig_shape_spar_data.csv（jig shape 的 beam CSV）
  ✅ jig_shape.step（jig shape 的 STEP 幾何）
  ❌ loaded_shape.step（缺！）
  ❌ deflection.csv（缺！）

所有需要的資料都已在記憶體中：
- candidate.inverse_result.predicted_loaded_shape（StructuralNodeShape）
- candidate.inverse_result.displacement_main_m（np.ndarray, shape (n_nodes, 6)）
- candidate.inverse_result.displacement_rear_m（np.ndarray, shape (n_nodes, 6)）
- candidate.inverse_result.jig_shape（StructuralNodeShape）

### 具體修改

1. **在 _export_artifacts() 中，jig STEP export 之後加入 loaded shape STEP export**

   已有的 jig STEP block（約 L2482-2491）：
   ```python
   if not skip_step_export:
       try:
           resolved_engine = export_step_from_csv(
               jig_csv_path,
               output_dir / "jig_shape.step",
               engine=step_engine,
           )
   ```

   在這之後加入：
   ```python
   loaded_csv_path = output_dir / "loaded_shape_spar_data.csv"
   write_shape_csv_from_template(
       template_csv_path=target_csv_path,
       output_csv_path=loaded_csv_path,
       shape=candidate.inverse_result.predicted_loaded_shape,
   )
   loaded_step_path: str | None = None
   loaded_step_error: str | None = None
   if not skip_step_export:
       try:
           export_step_from_csv(
               loaded_csv_path,
               output_dir / "loaded_shape.step",
               engine=step_engine,
           )
           loaded_step_path = str(
               (output_dir / "loaded_shape.step").resolve()
           )
       except Exception as exc:
           loaded_step_error = f"{type(exc).__name__}: {exc}"
   ```

2. **在 _export_artifacts() 中寫出 deflection CSV**

   在 wire rigging export 之前加入：
   ```python
   _write_deflection_csv(
       output_dir / "node_deflections.csv",
       candidate=candidate,
       model=model,   # 需要從上層傳入或從 candidate 取得
   )
   ```

   新增 helper 函式 _write_deflection_csv():
   ```python
   def _write_deflection_csv(
       path: Path,
       *,
       candidate,   # 你的 candidate type
       model,       # DualBeamMainlineModel
   ) -> None:
       """Write per-node deflection data for both spars."""
       inv = candidate.inverse_result
       disp_main = np.asarray(inv.displacement_main_m)
       disp_rear = np.asarray(inv.displacement_rear_m)
       y_main = model.nodes_main_m[:, 1]
       y_rear = model.nodes_rear_m[:, 1]

       with path.open("w", encoding="utf-8", newline="") as f:
           writer = csv.writer(f)
           writer.writerow([
               "spar", "node_index", "y_m",
               "ux_m", "uy_m", "uz_m",
               "theta_x_rad", "theta_y_rad", "theta_z_rad",
           ])
           for i in range(len(y_main)):
               row = ["main", i, f"{y_main[i]:.6f}"]
               for j in range(min(6, disp_main.shape[1])):
                   row.append(f"{disp_main[i, j]:.8e}")
               # 如果 displacement 少於 6 columns，補零
               for _ in range(6 - min(6, disp_main.shape[1])):
                   row.append("0.0")
               writer.writerow(row)
           for i in range(len(y_rear)):
               row = ["rear", i, f"{y_rear[i]:.6f}"]
               for j in range(min(6, disp_rear.shape[1])):
                   row.append(f"{disp_rear[i, j]:.8e}")
               for _ in range(6 - min(6, disp_rear.shape[1])):
                   row.append("0.0")
               writer.writerow(row)
   ```

3. **更新 ArtifactBundle dataclass** — 加入新欄位：
   ```python
   loaded_shape_csv: str | None = None
   loaded_step_path: str | None = None
   loaded_step_error: str | None = None
   deflection_csv: str | None = None
   ```

4. **更新 summary JSON** — 確保新檔案路徑出現在最終的 summary JSON 中

5. **確保 model 可在 _export_artifacts 中取得**
   如果 _export_artifacts() 的現有簽名沒有 model 參數，
   需要加入或從 candidate 中取得（看現有程式碼結構決定最好的方式）。

### 驗證

- 跑一次 inverse design，確認輸出目錄中出現：
  - jig_shape.step（已有，不能壞）
  - loaded_shape.step（新增）
  - loaded_shape_spar_data.csv（新增）
  - node_deflections.csv（新增）
- node_deflections.csv 的 uz_m column 應全部 ≥ 0（向上撓曲）
- loaded_shape.step 的管材形狀應與 jig_shape.step 不同（loaded 向上彎更多）

### 注意事項

- 遵守 CLAUDE.md：不硬編碼，路徑用 pathlib.Path
- from __future__ import annotations
- 行長度 <= 100 字元
- 不要修改任何計算邏輯，這是純 I/O 改動
- export_step_from_csv 和 write_shape_csv_from_template 已在 import 中
- 如果 CAD engine 不可用（cadquery/build123d 未安裝），STEP export 應
  gracefully fail 並記錄 error，不影響其他輸出

commit message: "feat: add loaded shape STEP export and per-node deflection CSV (Task 7h)"
```

---

## Task 7i：Monotonic Deflection Diagnostic Check — 已完成 ✅

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

目標：加入一個 diagnostic check，驗證 FEM 計算的垂直撓度 uz
在每個無支撐段內是否單調遞增（從翼根到翼尖方向）。

### 物理背景

對懸臂梁（固定端在翼根），在向上的分佈升力下，垂直撓度 uz(y)
必須沿展向單調遞增。如果有 wire support 在某個 y 位置：
- 0 → wire 段：uz 從 0（root BC）到 ≈0（wire constraint），可能微微正
- wire → tip 段：uz 從 ≈0（wire constraint）到 max（tip）

在每個段內，uz 應該是單調的。非單調意味著數值問題或載荷映射錯誤。

### 具體修改

1. **在 src/hpa_mdo/structure/inverse_design.py 新增函式：**

   ```python
   @dataclass(frozen=True)
   class MonotonicDeflectionCheck:
       """Diagnostic: per-segment monotonicity of vertical deflection."""
       segments_checked: int
       segments_monotonic: int
       worst_violation_m: float
       worst_violation_node_y_m: float
       passed: bool
       details: tuple[str, ...]

   def check_monotonic_deflection(
       *,
       y_nodes_m: np.ndarray,
       uz_m: np.ndarray,
       wire_y_positions: tuple[float, ...] = (),
       tolerance_m: float = 1.0e-4,
   ) -> MonotonicDeflectionCheck:
       """Check that uz increases monotonically within each span segment."""
   ```

   邏輯：
   - 將展向分段：[0, wire_1_y, wire_2_y, ..., tip_y]
   - 在每段內，檢查 uz[i+1] >= uz[i] - tolerance_m
   - 如果有違反，記錄位置和大小
   - passed = all segments monotonic

2. **在 FrozenLoadInverseDesignResult dataclass 加入新欄位：**
   ```python
   monotonic_deflection: MonotonicDeflectionCheck | None = None
   ```
   （用 None 是為了向後相容，不影響既有的 dataclass 實例化）

   注意：FrozenLoadInverseDesignResult 是 frozen=True 的 dataclass。
   如果加入 default=None 的欄位，它必須放在已有無 default 欄位的後面。
   如果 dataclass 的所有現有欄位都沒有 default，那在最後加即可。

3. **在 build_frozen_load_inverse_design_from_mainline() 中呼叫 check：**

   找到組裝 FrozenLoadInverseDesignResult 的位置，在那之前加入：
   ```python
   wire_y = tuple(
       float(a.y) for a in cfg.lift_wires.attachments
   ) if cfg.lift_wires.enabled else ()

   monotonic_check = check_monotonic_deflection(
       y_nodes_m=model.nodes_main_m[:, 1],
       uz_m=disp_main_m[:, 2],  # column 2 = uz
       wire_y_positions=wire_y,
   )
   ```
   然後傳入 result dataclass。

   如果 build_frozen_load_inverse_design_from_mainline() 目前沒有
   接收 cfg 參數，需要加入或從外部傳入 wire positions。
   （看現有簽名決定最好的方式。如果加參數不方便，
    可以讓 wire_y_positions 由呼叫端傳入。）

4. **在 summary JSON 中輸出 check 結果：**
   在 direct_dual_beam_inverse_design.py 的 summary payload 中加入：
   ```python
   "monotonic_deflection": asdict(result.monotonic_deflection)
       if result.monotonic_deflection is not None
       else None,
   ```

5. **如果 check 失敗，印出 WARNING（不影響 feasibility）：**
   ```python
   if not monotonic_check.passed:
       logger.warning(
           "Non-monotonic deflection detected: "
           "worst violation %.4f m at y=%.2f m",
           monotonic_check.worst_violation_m,
           monotonic_check.worst_violation_node_y_m,
       )
   ```

### 重要：這是 diagnostic，不是 constraint

- 不影響 feasibility 判斷（不加入 InverseDesignFeasibility）
- 不影響 val_weight 輸出
- 只在 summary JSON 和 log 中出現
- 如果某天想升級為 constraint，只需在 feasibility check 中加一行

### 驗證

- 正常 case 應通過（passed=True）
- 可以用一個假的 uz 陣列（人為加入 dip）測試 check 函式本身
- wire 分段應正確：wire at y=7.5 → 兩段 [0, 7.5] 和 [7.5, 16.5]

### 注意事項

- 遵守 CLAUDE.md
- from __future__ import annotations
- 行長度 <= 100 字元
- frozen dataclass 不能用 mutable default（用 tuple 不用 list）
- np.ndarray 的 column indexing：[:, 1] = Y, [:, 2] = Z

commit message: "feat: add monotonic deflection diagnostic check (Task 7i)"
```

---

## Task 8：VSP3→AVL 自動化 Pipeline（M8 foundation）— 8a-c 已完成 ✅

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
| 6 | Re-run dihedral sweep（Task 1+2） | ✅ |
| 7e | Aero performance gates | ✅ |
| 7f | Phase-2 sweep re-run | ✅ |
| 7g | Progressive dihedral scaling | ✅ |
| 7h | Loaded STEP + deflection CSV | ✅ |
| 7i | Monotonic deflection diagnostic | ✅ |
| 8 (M8) | VSP→AVL pipeline foundation | ✅（8a-c） |
| 8d | Config schema extension | ⏭️ backlog |

## 下一階段：Phase 3 — M11 CLT 疊層 + M12 控制β約束

> M9 全數完成。下一步分三條主線：
> - **M11 CLT composite layup** — 離散疊層最佳化（最高優先）
> - **M12 control & β constraint** — AVL 側滑分析
> - **M10 ASWING** — 非線性氣彈（較長期）
>
> M11 建議拆為 11a→11b→11c→11d 順序執行（blocking chain）
> M12 建議 12a→12b→12c 順序執行
> M11 與 M12 可並行

---

## Task 11a：PlyMaterial Dataclass + YAML Entries

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

目標：為 CLT（Classical Lamination Theory）疊層計算建立材料基礎設施。

### 背景

目前的材料系統（data/materials.yaml + core/materials.py）只有等向性管材屬性
（E, G, density, tensile_strength）。為了做複合材料疊層最佳化，需要
單層（lamina/ply）級的正交異向性屬性。

### 具體修改

1. **在 data/materials.yaml 新增 ply-level 材料條目：**

   ```yaml
   cfrp_ply_hm:
     description: "HM CFRP UD ply (M46J/epoxy equivalent)"
     material_type: "composite_ply"
     E1: 230.0e9          # fiber-direction modulus [Pa]
     E2: 8.0e9            # transverse modulus [Pa]
     G12: 5.0e9           # in-plane shear modulus [Pa]
     nu12: 0.27           # major Poisson's ratio
     t_ply: 0.125e-3      # cured ply thickness [m]
     density: 1600.0      # [kg/m3]
     F1t: 2500.0e6        # tensile strength, fiber direction [Pa]
     F1c: 1500.0e6        # compressive strength, fiber direction [Pa]
     F2t: 50.0e6          # tensile strength, transverse [Pa]
     F2c: 200.0e6         # compressive strength, transverse [Pa]
     F6: 100.0e6          # in-plane shear strength [Pa]

   cfrp_ply_sm:
     description: "SM CFRP UD ply (T300/epoxy equivalent)"
     material_type: "composite_ply"
     E1: 130.0e9
     E2: 10.0e9
     G12: 5.5e9
     nu12: 0.28
     t_ply: 0.125e-3
     density: 1550.0
     F1t: 1800.0e6
     F1c: 1200.0e6
     F2t: 60.0e6
     F2c: 180.0e6
     F6: 90.0e6
   ```

2. **在 src/hpa_mdo/core/materials.py 新增 PlyMaterial dataclass：**

   ```python
   @dataclass(frozen=True)
   class PlyMaterial:
       """Single ply (lamina) properties for CLT."""
       name: str
       E1: float        # fiber-direction Young's modulus [Pa]
       E2: float        # transverse Young's modulus [Pa]
       G12: float       # in-plane shear modulus [Pa]
       nu12: float      # major Poisson's ratio
       t_ply: float     # cured ply thickness [m]
       density: float   # [kg/m3]
       F1t: float       # tensile strength fiber-dir [Pa]
       F1c: float       # compressive strength fiber-dir [Pa]
       F2t: float       # tensile strength transverse [Pa]
       F2c: float       # compressive strength transverse [Pa]
       F6: float        # in-plane shear strength [Pa]

       @property
       def nu21(self) -> float:
           return self.nu12 * self.E2 / self.E1
   ```

3. **在 MaterialDB 中加入 ply material loader：**

   在 MaterialDB class 新增方法：
   ```python
   def get_ply(self, key: str) -> PlyMaterial:
       """Load a composite ply material by key."""
   ```
   辨識方式：檢查 material_type == "composite_ply"
   或檢查是否有 E1 欄位（backward-compatible）

4. **在 core/config.py 的 SparConfig 加入 layup 相關欄位：**
   ```python
   layup_mode: str = "isotropic"     # "isotropic" | "discrete_clt"
   ply_material: str | None = None   # key in materials.yaml
   min_plies_0: int = 1              # minimum 0° plies per half-layup
   min_plies_45_pairs: int = 1       # minimum ±45° ply pairs
   min_plies_90: int = 0             # minimum 90° plies
   max_total_plies: int = 14         # maximum total plies (full symmetric)
   ```

5. **在 configs/blackcat_004.yaml 的 main_spar 和 rear_spar 加入：**
   ```yaml
   layup_mode: "isotropic"           # default: use existing E/G scalar
   ply_material: "cfrp_ply_hm"       # ready for CLT when switched
   ```
   注意：layup_mode 保持 "isotropic" 以確保現有功能不受影響。

6. **單元測試：**
   - test_materials.py: 驗證 PlyMaterial 載入
   - 驗證 nu21 計算正確
   - 驗證 E1/E2/G12/strengths 數值合理
   - 驗證 isotropic 材料仍正常工作（不 break 現有行為）

### 注意事項

- 遵守 CLAUDE.md：新參數必須同時進 YAML + Pydantic model
- from __future__ import annotations
- 行長度 <= 100 字元
- 不要修改現有 Material dataclass（它是 isotropic 的，保持原樣）
- PlyMaterial 是新的 class，與 Material 平行存在
- 不改動任何求解器或最佳化器邏輯

commit message: "feat: add PlyMaterial dataclass and ply-level YAML entries for CLT (M11a)"
```

---

## Task 11b：CLT Engine — laminate.py

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

前置條件：Task 11a（PlyMaterial + YAML）已完成。

目標：建立 Classical Lamination Theory (CLT) 計算引擎，
從離散疊層定義計算管材的等效梁屬性。

### 物理推導

CLT 把多層複合材料的行為濃縮成 ABD 矩陣。對圓管梁，
我們只需要 A 矩陣（membrane stiffness）來算等效 E 和 G：

1. 每層的 Q 矩陣（3×3 reduced stiffness）從 E1, E2, G12, nu12 計算
2. 旋轉 Q 到任意角度 θ 得到 Q_bar(θ)
3. 積分所有層得到 A, B, D 矩陣（symmetric layup → B=0）
4. 等效管材屬性：
   - E_axial = A_11 / h（h = total wall thickness）
   - G_shear = A_66 / h
   - EI = π × R³ × A_11（thin-wall tube）
   - GJ = 4π × R³ × A_66（Bredt formula）

### 具體要求

1. **新建 src/hpa_mdo/structure/laminate.py**

   內含以下核心元件：

   a) **PlyStack dataclass（frozen=True）**
   ```python
   @dataclass(frozen=True)
   class PlyStack:
       """Discrete ply schedule: half-layup, symmetric assumed."""
       n_0: int      # number of 0° plies in half-layup
       n_45: int     # number of ±45° ply PAIRS in half-layup
       n_90: int     # number of 90° plies in half-layup
   ```
   
   Properties:
   - total_half_plies() = n_0 + 2*n_45 + n_90
   - total_plies() = 2 * total_half_plies()
   - wall_thickness(t_ply) = total_plies() * t_ply
   - angle_sequence_half() → list: [90°s at core, 0°s middle, ±45°s outside]
   - validate() → list[str]: check min plies, structural integrity
   
   製造約束：
   - n_0 >= 1（需要 bending stiffness）
   - n_45 >= 1（需要 torsional stiffness）
   - total_plies >= 4（結構最小值）
   - 90° plies NOT at outermost position（buckling rule）

   b) **ply_Q_matrix(E1, E2, G12, nu12) → ndarray (3,3)**
   On-axis reduced stiffness matrix.

   c) **rotated_Q(Q, theta_deg) → ndarray (3,3)**
   Transform Q to off-axis angle using standard rotation.
   Use Tsai convention: T matrix based on cos/sin of theta.

   d) **compute_ABD(ply_angles_deg, t_ply, Q, symmetric=True)**
   → tuple[A, B, D]
   For symmetric layup: B should be zeros (verify with assertion).

   e) **TubeEquivalentProperties dataclass（frozen=True）**
   ```python
   @dataclass(frozen=True)
   class TubeEquivalentProperties:
       E_axial: float       # effective axial modulus [Pa]
       G_shear: float       # effective shear modulus [Pa]
       wall_thickness: float # total wall [m]
       density: float       # composite density [kg/m3]
       A11: float           # membrane axial stiffness [N/m]
       A66: float           # membrane shear stiffness [N/m]
   ```

   f) **tube_equivalent_from_layup(stack, ply_mat, R_outer)**
   → TubeEquivalentProperties
   Main entry point：給一個 PlyStack + PlyMaterial + 外徑，
   回傳等效管材屬性。

2. **驗證用 unit tests（tests/test_laminate.py）：**

   a) **Q matrix 驗證**：用已知 E1=230 GPa, E2=8 GPa 計算，
      Q11 ≈ 230.2 GPa, Q22 ≈ 8.0 GPa, Q12 ≈ 2.16 GPa

   b) **旋轉驗證**：θ=0° 時 Q_bar == Q；θ=90° 時 Q_bar[0,0] ≈ Q[1,1]

   c) **ABD symmetric 驗證**：symmetric layup → B 矩陣全為零

   d) **管材等效驗證**：
      [0/±45/0]_s (8 plies, h=1.0mm) 的 E_axial 應在 100-160 GPa 之間
      （混合 0° 和 ±45° 的效果，不可能等於純 E1=230 GPa）

   e) **退化驗證**：純 [0]_s (全 0°) 的 E_axial 應 ≈ E1

3. **不需要的東西（在後續 Task 做）：**
   - OpenMDAO component（11c 以後）
   - 最佳化邏輯
   - Tsai-Wu failure（11e）
   - 與現有求解器的整合

### 數學細節

Q matrix:
```
nu21 = nu12 * E2 / E1
denom = 1 - nu12 * nu21
Q11 = E1 / denom
Q22 = E2 / denom
Q12 = nu12 * E2 / denom
Q66 = G12
```

Rotation (Tsai convention):
```
c = cos(θ), s = sin(θ)
T = [[c², s², 2cs], [s², c², -2cs], [-cs, cs, c²-s²]]
Q_bar = T_inv @ Q @ T_inv.T
```

ABD integration:
```
for each ply k with angle θ_k:
    z_bot = -h/2 + k*t_ply
    z_top = z_bot + t_ply
    Q_bar_k = rotated_Q(Q, θ_k)
    A += Q_bar_k * (z_top - z_bot)
    B += 0.5 * Q_bar_k * (z_top² - z_bot²)
    D += (1/3) * Q_bar_k * (z_top³ - z_bot³)
```

### 注意事項

- 遵守 CLAUDE.md
- from __future__ import annotations
- 行長度 <= 100 字元
- 純 numpy 實作，不引入外部依賴
- 所有角度函式用 degrees 輸入（內部轉 radians）
- frozen dataclass，tuple 取代 list

commit message: "feat: add CLT engine with PlyStack and tube equivalent properties (M11b)"
```

---

## Task 11c：PlyStack Catalog + Snap-to-Stack Post-Processor

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

前置條件：Task 11a + 11b 已完成。

目標：建立離散疊層目錄（enumerate valid PlyStacks）和
snap-to-stack post-processor（把連續最佳化結果對應到最近的可行疊層）。

### 背景

目前的最佳化器輸出每個 segment 的連續壁厚（如 0.87 mm）。
我們需要把它轉換成實際的疊層設計：
  "Segment 3: [0/±45/0/90/0/±45/0]_s, 10 plies total, h=1.25 mm"

這跟現有的 discrete_od.py（外徑離散化 snap-up）是完全相同的模式。

### 具體要求

1. **新建 src/hpa_mdo/utils/discrete_layup.py**

   a) **enumerate_valid_stacks(config) → list[PlyStack]**
   
   根據 config 的 min_plies_0, min_plies_45_pairs, min_plies_90,
   max_total_plies 枚舉所有有效的 PlyStack 組合。
   
   典型參數：
   - n_0 ∈ {1, 2, 3, 4, 5, 6, 7}
   - n_45 ∈ {1, 2, 3}
   - n_90 ∈ {0, 1, 2}
   - total_plies ≤ max_total_plies (14)
   - validate() 通過
   
   預期結果：約 30-40 個有效 PlyStack
   
   按 wall_thickness 排序（ascending）。

   b) **snap_to_nearest_stack(target_thickness, stacks, ply_mat) → PlyStack**
   
   找到 wall_thickness >= target_thickness 的最薄 PlyStack（snap-up）。
   如果沒有足夠厚的 stack，回傳最厚的並 log warning。

   c) **discretize_layup_per_segment(
         continuous_thicknesses, R_outer_per_seg,
         stacks, ply_mat,
         ply_drop_limit=2,
       ) → list[PlyStack]**
   
   對每個 segment 做 snap-to-stack，同時滿足 ply-drop constraint：
   相鄰 segment 的 total_plies 差異 ≤ ply_drop_limit。
   
   從翼根往翼尖掃：
   - Segment 0 先 snap
   - Segment 1 的選擇不能超過 Segment 0 的 total_plies + ply_drop_limit
   - ...以此類推
   
   如果 ply-drop 約束導致某 segment 需要比 snap 結果更厚，向上調整。

   d) **format_layup_report(segments_stacks, ply_mat) → str**
   
   格式化輸出，例如：
   ```
   Segment 1 (y=0.0-1.5m): [90/0/0/0/+45/-45/0/0/0/90]_s
     14 plies, h=1.750 mm, E_eff=168.2 GPa, G_eff=18.4 GPa
   Segment 2 (y=1.5-4.5m): [90/0/0/+45/-45/0/0/90]_s
     12 plies, h=1.500 mm, E_eff=152.7 GPa, G_eff=20.1 GPa
   ...
   ```

2. **新建 scripts/discrete_layup_postprocess.py**

   CLI script 讀取已有的 inverse design 結果（summary JSON），
   提取每 segment 的最佳壁厚，然後 discretize：
   
   ```
   python scripts/discrete_layup_postprocess.py \
     --summary output/path/inverse_design_summary.json \
     --ply-material cfrp_ply_hm \
     --output output/path/layup_report.txt
   ```
   
   輸出：
   - layup_report.txt（人可讀的疊層報告）
   - layup_schedule.json（machine-readable）
   - 連續 vs 離散的 mass penalty 比較

3. **單元測試 tests/test_discrete_layup.py：**
   - enumerate_valid_stacks 回傳數量合理（25-50）
   - snap_to_nearest_stack 正確 snap-up
   - ply-drop constraint 正確執行
   - format_layup_report 輸出格式正確

### 注意事項

- 遵守 CLAUDE.md
- 現有的 utils/discrete_od.py 是很好的參考模式
- from __future__ import annotations
- 行長度 <= 100 字元
- 不改動任何求解器或最佳化器
- 這是純 post-processing，不影響最佳化流程

commit message: "feat: add discrete layup catalog and snap-to-stack post-processor (M11c)"
```

---

## Task 12a：AVL β-Sweep Trim Analysis

### Prompt

```
你在 /Volumes/Samsung SSD/hpa-mdo 工作。
完成後請 push 到 main。

目標：在 dihedral sweep campaign 中加入 AVL 側滑角（β）掃掠分析，
評估每個 dihedral multiplier 在不同 β 下的方向穩定性和控制力矩。

### 背景

目前 AVL trim 分析只在 β=0° 執行。然而根據 MIT Daedalus 飛測報告
（docs/research/MIT 人力飛機 HPA 控制系統深度研究報告.md），
穩態轉彎時側滑角會累積到 ~12°，直接壓縮方向舵控制裕度。

HPA 沒有副翼，必須靠方向舵+上反角耦合做橫向控制。
因此 β ≠ 0 下的方向穩定性是設計可行性的一級約束。

### AVL 命令序列

在現有 trim 之後，加入 β sweep：

```text
PLOP
G

LOAD case.avl
OPER
C1
{cl_required}
B B {beta_deg}
X
FT
{beta_trim_file}

QUIT
```

注意：AVL 的 OPER 模式中，`B B {value}` 設定 sideslip angle beta。
或者可能需要用 `A B {value}` 來設定 beta constraint。
請查看 AVL documentation 確認正確語法。

如果無法確定 AVL 的 beta 命令語法，可以用以下替代方式：
- 在 .run file 中寫入 `beta {value}`
- 或者修改 AVL case file 的 `Beta = {value}` 行

### 具體修改

1. **在 dihedral_sweep_campaign.py 新增函式：**

   ```python
   def run_avl_beta_sweep(
       *,
       avl_bin: str | Path,
       case_avl_path: Path,
       case_dir: Path,
       cl_required: float,
       beta_values_deg: tuple[float, ...] = (0.0, 5.0, 10.0, 12.0),
       mode_params: AvlModeParameters,
   ) -> list[BetaSweepPoint]:
   ```

2. **新增 dataclass：**

   ```python
   @dataclass(frozen=True)
   class BetaSweepPoint:
       beta_deg: float
       cl_trim: float | None
       cd_induced: float | None
       aoa_trim_deg: float | None
       cn_total: float | None       # yaw moment coefficient
       cl_roll_total: float | None  # roll moment coefficient
       trim_converged: bool

   @dataclass(frozen=True)
   class BetaSweepEvaluation:
       beta_values_deg: tuple[float, ...]
       points: tuple[BetaSweepPoint, ...]
       max_trimmed_beta_deg: float | None
       directional_stable: bool
       sideslip_feasible: bool
       sideslip_reason: str
   ```

3. **在 AVL force output 中解析新欄位：**

   AVL 的 FT output 包含：
   - CLtot（已有 parser）
   - CDind（已有）
   - Cltot（roll moment coefficient — 注意大小寫：CL=lift, Cl=roll）
   - Cmtot（pitch moment）
   - Cntot（yaw moment）
   
   需要擴展 parse_avl_force_totals() 來提取 Cltot 和 Cntot。

4. **在 SweepResult 加入 β sweep 結果：**

   ```python
   beta_sweep_max_beta_deg: float | None = None
   beta_sweep_directional_stable: bool | None = None
   beta_sweep_sideslip_feasible: bool | None = None
   ```

5. **在 sweep main loop 中呼叫 β sweep：**

   在現有 trim 之後，如果 trim 成功，加入：
   ```python
   beta_eval = run_avl_beta_sweep(
       avl_bin=avl_bin,
       case_avl_path=case_avl_path,
       case_dir=case_dir,
       cl_required=cl_required,
       beta_values_deg=(0.0, 5.0, 10.0, 12.0),
       mode_params=mode_params,
   )
   ```

6. **Gate 邏輯：**
   - 如果在 β=12° 時 AVL trim 不收斂 → sideslip_feasible = False
   - 如果 Cn 在 β 增加時不是反向恢復（Cn_β > 0 = 不穩定）→ directional_stable = False
   - Gate 結果加入 summary CSV/JSON

7. **Config 參數：**
   ```yaml
   aero_gates:
     max_sideslip_deg: 12.0        # Daedalus flight test limit
     beta_sweep_values: [0, 5, 10, 12]
   ```

8. **CLI 參數：**
   ```
   --skip-beta-sweep        跳過 β 分析（加速測試）
   --max-sideslip-deg 12.0  覆寫 config
   ```

### 注意事項

- 遵守 CLAUDE.md：門檻值從 config 讀取
- from __future__ import annotations
- 行長度 <= 100 字元
- β sweep 是 optional（--skip-beta-sweep），不 break 現有流程
- AVL 的 Cl (roll) 和 CL (lift) 大小寫不同，parsing 要注意
- 每個 β 值會跑一次 AVL trim，所以會增加執行時間
  （4 beta × 每次 ~2s = ~8s extra per dihedral case）

commit message: "feat: add AVL beta-sweep trim analysis for sideslip constraint (M12a)"
```

---

## 下一步執行順序（Phase 3）

```
並行軌道 A：M11 CLT 疊層
  Task 11a (PlyMaterial + YAML)
  → Task 11b (CLT engine)
  → Task 11c (catalog + snap-to-stack + layup report)
  → [後續] 11d Tsai-Wu failure
  → [後續] 11e ply-drop constraint in optimizer

並行軌道 B：M12 控制與 β 約束
  Task 12a (AVL β-sweep)
  → [後續] 12b directional stability derivatives
  → [後續] 12c spiral stability check

獨立：M10 ASWING（較長期，需安裝 binary）
```

M11a/11b/11c 與 12a 無程式碼交集，可完全並行給 Codex。
