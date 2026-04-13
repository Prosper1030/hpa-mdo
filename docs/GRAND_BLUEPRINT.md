# HPA-MDO 終極藍圖 (Grand Blueprint)

> **文件性質**：最高指導文件 — 定義專案從求解器核心到全自動化設計 App 的五階段演進路線。  
> **維護者**：總工程師 + AI 架構師  
> **建立日期**：2026-04-09  
> **最後更新**：2026-04-13  
> **狀態**：Phase I-B 氣動彈性逆向設計主線已成立；外圈 Dihedral Sweep MVP-1 已打通，正在強化

---

## 0. 願景宣言

> 讓任何一個想造人力飛行器的團隊，只需用自然語言描述需求，就能在數分鐘內
> 取得經過多學科最佳化、物理驗證的完整設計方案——包含可直接送製造的 STEP 幾何、
> 結構報告、與氣動力特性摘要。

本專案的終極目標不只是一個求解器，而是一個**自主設計引擎**。從底層的有限元素
到頂層的自然語言介面，共分五個演進階段。每個階段都是下一個階段的基礎，不可跳過。

---

## 1. 五階段演進架構

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Phase V   鳥人間全自動化設計 App (The "Birdman" App)         │
│             自然語言 → 完整設計方案                              │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Phase IV  Autoresearch — AI 自主決策與研究引擎                │
│             自動調參、自動驗證、不眠不休設計迴圈                │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Phase III 機器學習代理模型 (ML Surrogate Models)              │
│             萬次模擬 → 神經網路 → 秒級預測                      │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Phase II  混合資料庫大一統 (Unified Knowledge & Data Base)    │
│             結構化材料數據 + 非結構化文獻 RAG                   │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Phase I   多學科基礎求解器 (MDO Solver Core)     ◀ 目前位置  │
│             結構 · 氣動 · FSI · 最佳化 · CAD 匯出              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Phase I — 多學科基礎求解器 (MDO Solver Core)

### 目標

從純結構最佳化逐步擴充氣動力、流固耦合、傳動與控制面，打造出
**不當機、物理正確、極速收斂**的底層計算沙盒。這是所有上層智慧的地基。

### 里程碑地圖

```
  Milestone 1 (✅ DONE)                 Milestone B (✅ DONE)
  ┌─────────────────────┐               ┌─────────────────────┐
  │ OpenMDAO topology   │               │ Production path     │
  │ Multi-case branch   │               │ method="auto"       │
  │ check_totals        │               │ 21.57→13.91 kg      │
  │ M2-M6 code hygiene  │               │ 5× speedup          │
  │ STEP/ANSYS export   │               │ Cache fix + counters│
  └────────┬────────────┘               └────────┬────────────┘
           │                                      │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 2 — Physics Hardening      │
           │                                       │
           │ Phase 1 (✅ DONE):                    │
           │   F13 壓縮強度 allowable              │
           │   F9  warping knockdown 0.5           │
           │                                       │
           │ Phase 2 (✅ DONE):                    │
           │   F6  壁厚平滑約束 (buckling=-0.70)  │
           │   F8  扭矩剪力 buckling → 延後 M4    │
           │       （margin 充裕，buckling_idx < -0.3）
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 3 — MDO Integration ✅     │
           │                                       │
           │ 3a ✅ FSI one-way in production      │
           │       blackcat_004_fsi.py, 13.91 kg  │
           │ 3b ✅ Multi-load-case example        │
           │       blackcat_004_multi_case.py     │
           │       (cruise+pullup_2g, 40.28 kg)   │
           │ 3c ✅ STEP deformed shape export     │
           │       compute_deformed_nodes()        │
           │       jig-shape + flight-shape .step  │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 4 — Design Fidelity  ✅     │
           │                                       │
           │ 4a ✅ 升力鋼索壓縮效應 (F10)         │
           │      wire_precompression.py + 11.3°  │
           │ 4b ✅ 離散 OD post-processing (F11)  │
           │      tube_catalog 12–120mm, snap-up  │
           │ 4c ✅ 副梁重力力矩 (F12)             │
           │      q_torque = m_rear × g × d_chord │
           │ 4d ✅ 扭矩剪力 buckling (F8)         │
           │      torsion-shear interaction       │
           │ 4e ✅ equivalent-beam ANSYS  │
           │      validation PASS          │
           │ 4f. dual-spar adequacy        │
           │      spot-check        ◀ NEXT │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 5 — Advanced Capabilities  │
           │      暫不正式啟動，等 4f 後決定     │
           │                                       │
           │ 5a. Two-way FSI + OpenVSP API        │
           │ 5b. Flutter / aeroelastic stability  │
           │ 5c. Gust loads / load envelope       │
           │ 5d. Ply-level composite design       │
           │ 5e. Control surface coupling         │
           │ 5f. Drivetrain / propeller sizing    │
           └──────────────────────────────────────┘

  ═══════════════════════════════════════════════════════════

  Phase I-B — 氣動彈性逆向設計主線（2026-04 新增）

           ┌──────────────────────────────────────┐
           │ Milestone 6 — Inverse Design  ✅     │
           │                                       │
           │ 6a ✅ dual-beam production mainline  │
           │      builder/solver/recovery/optview │
           │ 6b ✅ 離散 geometry + decision layer │
           │      Primary/Balanced/Conservative   │
           │ 6c ✅ 材料 proxy 家族               │
           │      main_spar_family / rear_pkg     │
           │ 6d ✅ producer / autoresearch /      │
           │      campaign framework              │
           │ 6e ✅ exact-nodal inverse design MVP │
           │      jig = target - ΔU              │
           │ 6f ✅ light load refresh (1-2 iter) │
           │ 6g ✅ active-wall diagnostics       │
           │ 6h ✅ clearance-aware ranking       │
           │ 6i ✅ wire / rigging minimal output │
           │ 6j ✅ STEP export (jig + decisions) │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 7 — Outer-Loop Campaign    │
           │                                       │
           │ 7a ✅ dihedral sweep MVP-1           │
           │      AVL→stability→inner loop→CSV   │
           │ 7b ✅ wire material upgrade          │
           │      steel_4130→dyneema_sk75        │
           │ 7c ✅ full-body AVL model            │
           │      wing+elevator+fin              │
           │ 7d ✅ sweep error handling           │
           │      per-case collection + --strict  │
           │ 7e ⏭️ aero performance gates        │
           │      min_lift≥100kg, L/D check      │
           │      AVL trim → CL/CD/L/D extract   │
           │                          ◀ NEXT     │
           │ 7f ⏭️ phase-2 sweep re-run          │
           │      (stability + aero gates)       │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 8 — VSP→AVL Pipeline  ✅   │
           │      (full-aircraft geometry flow)    │
           │                                       │
           │ 8a ✅ VSP3 XML parser                │
           │      vsp_geometry_parser.py          │
           │ 8b ✅ AVL exporter                   │
           │      avl_exporter.py                 │
           │ 8c ✅ CLI utility                    │
           │      scripts/vsp_to_avl.py           │
           │ 8d. Config schema extension          │
           │     tail/fin sections in YAML        │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 9 — Design Space Maturity  │
           │                                       │
           │ 9a. fine dihedral sweep (0.1 step)   │
           │ 9b. multi-objective Pareto front     │
           │     (mass × stability × wire ×       │
           │      aero performance)               │
           │ 9c. vendor-aware tube catalog        │
           │ 9d. full wire/rigging system         │
           │ 9e. dynamic design space             │
           │ 9f. higher-fidelity load coupling    │
           └──────────────┬───────────────────────┘
                          │
           ┌──────────────▼───────────────────────┐
           │ Milestone 10 — ASWING Integration    │
           │      (nonlinear aeroelastic solver)  │
           │                                       │
           │ 10a. ASWING binary install/build     │
           │ 10b. .asw geometry generator         │
           │      from config + VSP geometry      │
           │ 10c. ASWING subprocess wrapper       │
           │      trim → eigenmode → parse output │
           │ 10d. Cross-validation vs internal FEM│
           │      deflection/stress/flutter       │
           │ 10e. ASWING-in-the-loop campaign     │
           │      replace AVL stability filter    │
           └──────────────────────────────────────┘
```

### Phase I 完成判準

- [x] 所有 physics review Category A findings 已修（F1–F5）
- [x] 所有 physics review Category B findings 已修或已評估（F6–F13 全數完成）
- [x] FSI one-way 可在 production pipeline 一鍵執行（`blackcat_004_fsi.py`）
- [x] Multi-load-case 有 production example（cruise + pullup_2g，4G 等效已記錄）
- [x] check_totals 全模型 + 多工況 RE < 1e-5
- [x] Golden regression test 守住所有 production config（11.954 kg baseline）
- [x] STEP export 包含變形後幾何（jig + flight shape）
- [x] equivalent-beam ANSYS validation 對內部 FEM 結果交叉驗證通過（正式 Phase I gate）
- [ ] dual-spar high-fidelity adequacy spot-check（非 gate，用於模型形式風險判斷）

### Phase I 目前狀態明細

| 項目 | 狀態 | 備註 |
|------|------|------|
| OpenMDAO structural topology | ✅ | Shared backbone + per-case branches |
| Dual-spar Timoshenko FEM | ✅ | Parallel-axis EI/GJ, independent Iz |
| Analytic + CS partials | ✅ | check_totals 全模型 + multi-case 通過 |
| Production optimizer path | ✅ | `method="auto"`, OpenMDAO driver, 13.91 kg |
| Physics F1-F13 全數 | ✅ | VM/Buckling/Taper/Iz/Dominance/Warping/Compression/Smooth/Torsion/Wire/OD/Torque |
| FSI one-way | ✅ | `blackcat_004_fsi.py`, 13.91 kg |
| ANSYS 4e gate | ✅ | equivalent-beam validation PASS |
| STEP + ANSYS export | ✅ | cadquery/build123d, APDL/BDF/CSV |
| API server (REST + MCP) | ✅ | FastAPI + MCP, shared helpers |

### Phase I-B 目前狀態明細

| 項目 | 狀態 | 備註 |
|------|------|------|
| dual-beam production mainline | ✅ | builder/solver/recovery/optimizer_view |
| 離散 geometry + decision layer | ✅ | Primary/Balanced/Conservative |
| 材料 proxy 家族 | ✅ | main_spar_family / rear_outboard_reinforcement_pkg |
| producer / autoresearch / campaign | ✅ | history/compare/provenance/fingerprint/lineage |
| exact-nodal inverse design | ✅ | frozen-load MVP + light load refresh |
| active-wall diagnostics | ✅ | ground clearance 確認為主瓶頸 |
| clearance-aware ranking | ✅ | 解從擦地 → 可行但更重 |
| wire / rigging minimal output | ✅ | L_flight/ΔL/L_cut/tension/margin |
| wire material upgrade | ✅ | dyneema_sk75, allowable ≈ 6872N |
| dihedral sweep MVP-1 | ✅ | AVL→stability→inner loop→CSV 流程打通 |
| full-body AVL model | ✅ | wing+elevator+fin，data/blackcat_004_full.avl |
| sweep error handling | ✅ | per-case collection + --strict flag |
| VSP3→AVL pipeline | ✅ | vsp_geometry_parser + avl_exporter + CLI |
| aero performance gates | ⏭️ | min lift ≥ 100kg + L/D 檢查，**當前最高優先** |
| 穩定性濾網（真正啟用） | ⏭️ | 需 aero gates 後一起 re-run |

---

## 3. Phase II — 混合資料庫大一統 (Unified Knowledge & Data Base)

### 目標

整合團隊極度分散的工程知識與材料數據，建立**結構化 + 非結構化**的混合資料庫，
為 ML 訓練（Phase III）和 AI 自主研究（Phase IV）提供資料燃料。

### 核心組件

```
┌─────────────────────────────────────────────────────┐
│              Unified Knowledge Base                  │
│                                                      │
│  ┌──────────────────┐    ┌────────────────────────┐ │
│  │ Structured DB    │    │ Unstructured Corpus    │ │
│  │                  │    │                        │ │
│  │ • materials.yaml │    │ • 競賽報告 PDF         │ │
│  │   擴充：發泡材、 │    │ • 日本團隊技術文件     │ │
│  │   Kevlar、接著劑 │    │ • Daedalus/Musculair  │ │
│  │ • tube_catalog   │    │   設計文獻             │ │
│  │   商用碳管規格庫 │    │ • 風洞試驗數據         │ │
│  │ • airfoil_db     │    │ • 團隊內部設計筆記     │ │
│  │   翼型幾何+極曲線│    │ • 歷年鳥人間參賽紀錄  │ │
│  │ • joint_catalog  │    │                        │ │
│  │   接頭型式+重量  │    │  ── RAG Pipeline ──   │ │
│  │ • rib_properties │    │  Embedding → Vector DB │ │
│  │   肋材剛度資料   │    │  → LLM Query Engine   │ │
│  └──────────────────┘    └────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 里程碑

| # | 交付物 | 說明 |
|---|--------|------|
| **II-1** | 擴充 `data/materials.yaml` | 加入發泡材（Rohacell, balsa）、Kevlar、接著劑、預浸布等完整力學性質 |
| **II-2** | `data/tube_catalog.yaml` | 商用碳管規格庫（OD, ID, 層數, 供應商, 價格），供離散 OD 最佳化使用 |
| **II-3** | `data/airfoil_db/` | 翼型幾何 `.dat` + 極曲線 `.csv`，統一格式，可被 aero solver 自動載入 |
| **II-4** | `data/rib_properties.yaml` | 肋材型式、間距、剪力剛度 → 自動計算 `warping_knockdown`（取代手動 config） |
| **II-5** | RAG Pipeline MVP | 非結構化文獻 → embedding → 向量資料庫 → LLM 可查詢的知識引擎 |
| **II-6** | `data/joint_catalog.yaml` | 接頭型式（telescoping sleeve, pin joint）含重量、強度、相容 OD 範圍 |

### Phase II 完成判準

- [ ] `MaterialDB` 可載入所有材料（不只碳纖 + 鋁合金）
- [ ] 離散 OD 最佳化可從 `tube_catalog.yaml` 讀取可用規格
- [ ] `warping_knockdown` 可由 `rib_properties.yaml` 自動計算
- [ ] RAG pipeline 可回答「日本 Team Aeroscepsy 的主梁用什麼碳管？」
- [ ] 所有結構化資料有 Pydantic schema 驗證

### 與 Phase I 的介面

Phase II 的結構化資料直接被 Phase I 的求解器消費：
- `MaterialDB` ← `materials.yaml`（已存在，擴充）
- `compute_outer_radius_from_wing()` ← `tube_catalog.yaml`（新）
- `DualSparPropertiesComp` ← `rib_properties.yaml` → `warping_knockdown`（新）

Phase II 的非結構化資料被 Phase IV 的 Autoresearch Agent 消費。

---

## 4. Phase III — 機器學習代理模型 (ML Surrogate Models)

### 目標

利用 Phase I 的高精度求解器產生大量設計空間樣本，訓練**神經網路代理模型**，
實現從「分鐘級 FEM」到「毫秒級預測」的降維打擊。

### 架構

```
┌──────────────────────────────────────────────────────┐
│                ML Surrogate Pipeline                  │
│                                                       │
│  ┌───────────┐     ┌──────────────┐    ┌──────────┐ │
│  │ Phase I   │     │ Training     │    │ Surrogate│ │
│  │ MDO Solver│────▶│ Data Gen     │───▶│ Model    │ │
│  │ (72s/eval)│     │ (10k-100k   │    │ (ms/eval)│ │
│  │           │     │  samples)    │    │          │ │
│  └───────────┘     └──────────────┘    └────┬─────┘ │
│                                              │       │
│  ┌───────────────────────────────────────────▼─────┐ │
│  │ Validation Loop                                 │ │
│  │ Surrogate prediction → Phase I verification     │ │
│  │ at promising points → Retrain if error > 5%     │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 里程碑

| # | 交付物 | 說明 |
|---|--------|------|
| **III-1** | DOE 取樣器 | Latin Hypercube / Sobol 序列取樣 24 個設計變數空間 |
| **III-2** | 批次求解 runner | 平行呼叫 Phase I solver，產出 `(x, y)` 訓練資料集 |
| **III-3** | Surrogate v1 | 全連接 NN 或 Gaussian Process，輸入 24 DV → 輸出 mass + constraints |
| **III-4** | 主動學習迴圈 | Surrogate 預測 → 高不確定度點送回 Phase I → 增量訓練 |
| **III-5** | Surrogate-in-the-loop optimizer | DE 或 Bayesian Optimization 在 surrogate 上跑百萬次，Phase I 只驗證 top-K |

### Phase III 完成判準

- [ ] Surrogate 在測試集上 mass 預測 RMSE < 0.5 kg
- [ ] Surrogate 約束預測 F1-score > 0.95（feasible/infeasible 分類）
- [ ] 端對端：surrogate-guided search 找到的設計，Phase I 驗證後 mass ≤ Phase I 直接最佳化的 102%
- [ ] 單次 surrogate 評估 < 10 ms

---

## 5. Phase IV — Autoresearch (AI 自主決策與研究引擎)

### 目標

建構在 Phase I（精確求解）與 Phase III（快速預測）之上的
**AI 自主設計迴圈**：給定高階目標（「重量最輕」「成本最低」「疲勞壽命最長」），
AI Agent 自動調用演算法或代理模型，不眠不休地進行設計探索、參數調整與驗證。

### 架構

```
┌────────────────────────────────────────────────────────────┐
│                  Autoresearch Engine                        │
│                                                            │
│  ┌──────────────┐                                          │
│  │ Objective    │  "minimize mass, satisfy all constraints, │
│  │ Specification│   budget ≤ ¥500,000, timeline 3 months"  │
│  └──────┬───────┘                                          │
│         │                                                  │
│  ┌──────▼───────┐    ┌──────────────┐   ┌──────────────┐  │
│  │ Strategy     │    │ Surrogate    │   │ Phase I      │  │
│  │ Planner      │───▶│ Scout        │──▶│ Validator    │  │
│  │ (LLM-based) │    │ (Phase III)  │   │ (precise)    │  │
│  └──────┬───────┘    └──────────────┘   └──────┬───────┘  │
│         │                                       │          │
│  ┌──────▼───────────────────────────────────────▼───────┐  │
│  │ Knowledge Retriever (Phase II RAG)                   │  │
│  │ "How did Daedalus solve this?" → context for Planner │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  Output: Pareto front of designs + engineering rationale   │
│          val_weight: <float> per design (machine-readable) │
└────────────────────────────────────────────────────────────┘
```

### 里程碑

| # | 交付物 | 說明 |
|---|--------|------|
| **IV-1** | Agent-Solver API | 標準化介面：Agent 送 config YAML → Solver 回 `val_weight` + constraints + STEP |
| **IV-2** | Strategy Planner v1 | LLM Agent 解讀目標、決定搜尋策略（grid/random/Bayesian/surrogate-guided） |
| **IV-3** | RAG 整合 | Planner 可查詢 Phase II 知識庫取得設計靈感與歷史參考 |
| **IV-4** | Overnight Runner | 無人值守批次執行，自動紀錄、自動比較、自動產出 Pareto front |
| **IV-5** | Self-Correcting Loop | Agent 偵測到 `val_weight: 99999` → 自動診斷失敗原因 → 調整策略重試 |

### Phase IV 完成判準

- [ ] 給定 "minimize mass for blackcat_004"，Agent 在 8 小時內自動產出 ≥ 10 個 Pareto-optimal designs
- [ ] Agent 可自動處理 `val_weight: 99999`（config 錯誤 vs 求解失敗的區別，參見 audit O10）
- [ ] 每個 design 附有 Agent 生成的工程決策理由（traceability）
- [ ] Agent 可跨 config（不同翼展、不同飛行員體重）自主探索

### 與現有架構的介面

Phase IV 的 Agent-Solver API 實質上已經存在：
- `api/server.py`（FastAPI REST）
- `api/mcp_server.py`（MCP Server）
- `val_weight: <float>` 輸出協定（CLAUDE.md iron rule #7）

這些都是 Milestone 1 就建好的基礎設施，Phase IV 直接站在上面。

---

## 6. Phase V — 鳥人間全自動化設計 App (The "Birdman" App)

### 目標

終極使用者介面。非工程師也能使用。自然語言輸入需求，底層大腦、資料庫與求解器
自動協同，產出包含 STEP 幾何、結構報告、與氣動力特性摘要的完整設計方案。

### 使用者體驗

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   🛩️  Birdman Design Studio                            │
│                                                         │
│   ┌───────────────────────────────────────────────────┐ │
│   │ 飛行員 65kg，逆風 3m/s，翼展限制 25m，           │ │
│   │ 預算 50 萬日圓，用碳纖管 + balsa 肋材，          │ │
│   │ 目標：琵琶湖飛最遠                                │ │
│   └───────────────────────────────────────────────────┘ │
│                                                         │
│   [開始設計]                                            │
│                                                         │
│   ┌─ 設計進度 ──────────────────────────────────────┐  │
│   │ ✅ 解析需求：巡航速度 8.5 m/s，升力 637.6 N    │  │
│   │ ✅ 選定翼型：DAE-31 (低 Re 高 L/D)             │  │
│   │ ✅ 氣動力分析：VSPAero 3 工況完成               │  │
│   │ ⏳ 結構最佳化：iteration 12/50, mass = 14.2 kg  │  │
│   │ ⬜ 生成 STEP 幾何                               │  │
│   │ ⬜ 產出報告                                      │  │
│   └──────────────────────────────────────────────────┘  │
│                                                         │
│   ┌─ 設計決策（需要你確認）────────────────────────┐   │
│   │ 主梁 OD 建議 30mm（目錄最近規格），             │   │
│   │ 但 28mm 可省 ¥12,000，重量增加 0.3 kg。        │   │
│   │ 你要選哪個？ [30mm] [28mm] [讓 AI 決定]        │   │
│   └──────────────────────────────────────────────────┘  │
│                                                         │
│   [下載 STEP]  [下載報告 PDF]  [分享給隊友]            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 技術堆疊

```
Frontend:  Next.js / React + 3D viewer (Three.js)
Backend:   Phase IV Autoresearch Engine
           ├── Phase III Surrogate (快速初篩)
           ├── Phase I  MDO Solver (精確驗證)
           └── Phase II Knowledge Base (RAG 輔助決策)
API:       Phase IV Agent-Solver API (已存在 REST + MCP)
Auth:      團隊帳號制（鳥人間參賽隊伍為單位）
```

### 里程碑

| # | 交付物 | 說明 |
|---|--------|------|
| **V-1** | NL → Config 轉譯器 | LLM 把自然語言需求轉成 `blackcat_xxx.yaml` |
| **V-2** | Web UI MVP | 上傳需求 → 看到即時進度 → 下載 STEP + 報告 |
| **V-3** | 3D 預覽 | Three.js 即時顯示 STEP 幾何 + 應力/撓度雲圖 |
| **V-4** | 設計決策介面 | 當 AI 遇到需要人類判斷的 trade-off，暫停並詢問 |
| **V-5** | 團隊協作 | 多人共享設計、版本比較、歷史紀錄 |
| **V-6** | 成本估算整合 | Phase II 材料價格 + 加工費 → 自動報價 |

### Phase V 完成判準

- [ ] 非工程師使用者可在 5 分鐘內從自然語言描述得到可製造的設計方案
- [ ] STEP 檔可直接送 CNC 或手積層報價，無需人工後處理
- [ ] 設計方案附帶完整工程報告（PDF），包含所有假設、約束、安全係數
- [ ] 3 個以上鳥人間參賽隊伍使用並回饋

---

## 7. 跨階段依賴關係

```
Phase I ──────────────────────────────────────────────────▶ 全部
Phase II ─────────────────────────▶ Phase III (訓練資料)
                                   Phase IV (RAG 知識)
                                   Phase V  (材料/成本)
Phase III ────────────────────────▶ Phase IV (快速評估)
                                   Phase V  (即時預測)
Phase IV ─────────────────────────▶ Phase V  (後端引擎)
```

**關鍵路徑**：Phase I → Phase III → Phase IV → Phase V  
**平行路徑**：Phase II 可與 Phase I 後半段同步進行

---

## 8. 當前位置與下一步

### 已完成

| 里程碑 | 狀態 | 關鍵成就 |
|--------|------|----------|
| Phase I — Milestone 1 | ✅ | OpenMDAO topology, multi-case, check_totals, M2-M6 |
| Phase I — Milestone B | ✅ | Production → `method="auto"`, 21.57→13.91 kg (−35%), 5× speedup |
| Phase I — Milestone 2 | ✅ | F13 compressive / F9 warping / F6 壁厚平滑 / F8 torsion-shear |
| Phase I — Milestone 3 | ✅ | FSI one-way, multi-case, STEP deformed shape |
| Phase I — Milestone 4 | ✅ | F10 wire precomp / F11 discrete OD / F12 gravity torque / 4e ANSYS PASS |
| Phase I-B — Milestone 6 | ✅ | dual-beam mainline, inverse design MVP, discrete geometry, decision layer |
| Phase I-B — Milestone 7a-d | ✅ | dihedral sweep MVP-1, wire 升級, full-body AVL, error handling |
| Phase I-B — Milestone 8a-c | ✅ | VSP3 XML parser, AVL exporter, CLI utility |
| Phase II — II-1 | ✅ | 17 materials（含 dyneema_sk75, piano_wire_swpb） |

### 目前 Inverse Design 指標（dihedral sweep smoke）

```
Dihedral ×1.0:  mass=23.1 kg, clearance=9.4 mm, wire=3244 N
Dihedral ×1.5:  mass=19.7 kg, clearance=2.4 mm, wire=3335 N
Dihedral ×2.0:  mass=14.6 kg, clearance=4.7 mm, wire=3716 N
Dihedral ×2.5:  mass=13.1 kg, clearance=8.4 mm, wire=3875 N

Wire allowable (dyneema_sk75, 2.5mm, 40%):  ≈6872 N  ← 全部 feasible
Stability filter:  尚未啟用（需完整機體 .avl）
```

### 已驗證的工程結論

| 結論 | 來源 |
|------|------|
| 13-15 kg 主翼重量合理 | 日本團隊實績（CHicK-2000: 15.44 kg, Windnauts: ~12-14 kg） |
| 3000-4000 N wire tension 可行 | Dyneema SK75 2.5mm ≈ 6872N allowable, 鋼琴線 2.0mm ≈ 6280N |
| 21-22 kg floor 非 search/coupling 問題 | 驗證過 shape matching 放鬆無效，瓶頸在 ground clearance |
| target dihedral 是核心設計變數 | 增大 dihedral → mass 大幅下降，wire margin 在升級後 OK |

### 下一步（優先順序）

| 優先序 | 任務 | Milestone | 負責 | 狀態 |
|--------|------|-----------|------|------|
| **1** | 7e: 氣動性能門檻（min lift ≥ 100kg + L/D） | M7 | Codex | ⏭️ **NEXT** |
| **2** | 7f: phase-2 sweep re-run（stability + aero gates） | M7 | Codex | ⏭️ 等 7e |
| **3** | 9a: fine dihedral sweep（step 0.1） | M9 | Codex | ❌ 等 7f |
| **4** | 9b: multi-objective Pareto front | M9 | 規劃中 | ❌ |
| **5** | 10a-b: ASWING 安裝 + .asw 產生器 | M10 | 評估中 | ❌ |

### 已完成（本輪）

| 任務 | Milestone | 結果 |
|------|-----------|------|
| wire 材料升級 | M7 | ✅ dyneema_sk75, allowable ≈ 6872N |
| full-body AVL | M7 | ✅ wing + elevator + fin |
| sweep error handling | M7 | ✅ per-case collection + --strict |
| tolerance 進 config | M7 | ✅ Pydantic + YAML + CLI |
| .lod component filter | M7 | ✅ optional component_ids + WARNING |
| VSP3→AVL pipeline | M8 | ✅ parser + exporter + CLI + tests |

### 關鍵路徑

```
7e (aero gates) → 7f (re-run sweep) → 真正的多維 feasibility 數據
   min lift ≥ 100kg                    stability + mass + wire +
   L/D ≥ 25 (pilot power budget)      aero performance 一起看
                                     → 決定最佳 dihedral 範圍
                                     → 9a (fine sweep) → 9b (Pareto)

未來：10a-e (ASWING) — 非線性氣動彈性驗證，取代/補強 AVL
```

### Daedalus 參考數據（來自文獻，用於交叉驗證）

| 參數 | 數值 | 來源 |
|------|------|------|
| 巡航速度 | 6.7 m/s | Sullivan & Zerweckh |
| 失速速度 | 5.9 m/s | Cruz & Drela |
| 設計載荷係數 | 1.75 g | Cruz & Drela |
| 機動速度 | 7.8 m/s | Cruz & Drela |
| 翼尖撓度 | 2.0 m | Cruz & Drela |
| 空機重 | 41.7 kg (92 lb) | Sullivan & Zerweckh |
| 設計 CL | 0.8-1.2 | Drela |
| 最大側滑角 | 30° | Cruz & Drela |

---

## 9. 命名慣例與文件規範

| 項目 | 規範 |
|------|------|
| 高階文件（本文件、README、操作手冊） | 繁體中文（CLAUDE.md iron rule #8） |
| 程式碼註解、log、.txt 報告 | 英文 |
| Commit message | 英文，Conventional Commits 格式 |
| Config / YAML | 英文 key，中文 comment 可選 |
| Codex prompt | 英文（Codex 執行效率考量） |
| Phase / Milestone 編號 | `Phase I-V`、`Milestone 1-5`、`M2P1` = Milestone 2 Phase 1 |

---

## 10. 風險與緩解

| 風險 | 影響 | 緩解 |
|------|------|------|
| Phase I FEM 精度不足以訓練 Phase III surrogate | III 預測垃圾 | M4 + M5 完成所有 physics findings 後再開始 III |
| Phase II 非結構化文獻品質參差 | RAG 給出錯誤建議 | Embedding 前人工審查，RAG 回答附引用來源 |
| Phase III surrogate 外推失敗 | IV 探索到 surrogate 未見過的設計空間 | 主動學習迴圈 + Phase I 驗證閘門 |
| Phase IV Agent 過度自信 | 產出不可行設計 | `_is_raw_feasible` 作為硬閘門，val_weight 協定不可繞過 |
| Phase V 使用者信任過度 | 非工程師直接送製造 | 報告必須標示所有假設與限制，STEP 附安全警語 |
| dihedral sweep 載荷不一致 | mass 偏樂觀 | 目前用 ×1.0 載荷算所有 dihedral；M9 補 AVL/VSPAero load refresh |
| AVL 穩定性假陽性/假陰性 | 錯誤篩選 | 慣量參數需從 config 讀取；full-body .avl 是最低門檻 |
| .lod parser 無 component filter | 多元件 VSP 載荷汙染 | 已列入 Task 5；目前 .lod 只有 wing 所以安全 |

---

## 11. 設計防線（Design Guardrails）

以下結論已由系統性實驗驗證，**不可在未有新證據的情況下重新質疑**：

1. **inverse-design 方向正確** — loaded shape → jig shape 是主線
2. **shape matching 放鬆無效** — 已測試低維匹配，mass 無明顯改善，mismatch 變大
3. **不急著擴設計空間** — 先用外圈確認 target dihedral
4. **wire margin 是硬約束** — 不是裝飾輸出，已是實際瓶頸之一
5. **23 kg 是診斷結果不是設計答案** — 原因是 target dihedral 太小
6. **wire allowable 1052N 是錯的** — 已修正為 dyneema_sk75 ≈ 6872N
7. **氣動性能必須檢查** — 高 dihedral 可能降低有效升力和 L/D，min lift ≥ 100kg 是硬門檻
8. **ASWING 是終極驗證工具** — Drela 的非線性氣動彈性求解器，支援柔性翼+鋼索+flutter

---

## 12. 團隊分工

| 角色 | 負責人 | 職責 |
|------|--------|------|
| 總工程師 | 使用者 | 工程判斷、domain knowledge、最終拍板 |
| 技術主管 | Claude | 規劃、審查、物理 sanity check、架構決策 |
| 實作工程師 | Codex (5.4/5.3 xhigh) | 寫 code、跑測試、修 bug |

原則：
- Claude 不主動寫 code，除非是一行改動或時間緊迫
- Codex 收到完整 prompt 後獨立執行，交付後由 Claude 審查
- 所有設計方向變更由總工程師拍板

---

*本文件為活文件，每個 Milestone 完成後由總工程師與 AI 架構師共同更新。*
