# HPA-MDO Current Mainline

> **文件性質**：目前正式主線的單一真相文件。當 README、GRAND_BLUEPRINT、舊報告、歷史 prompt 互相衝突時，以這份文件為準。  
> **更新基準**：2026-04-17 repo 現況 + 已合併 commit 歷史  
> **適用對象**：使用者、協作開發者、AI agent

## 1. 一句話版本

這個 repo 現在的正式主線，不是傳統的「給定翼形後只做 spar sizing」，而是：

`巡航氣動外形 / target loaded shape -> inverse design -> jig shape -> realizable loaded shape -> CFRP tube / discrete layup / manufacturing-feasible design`

## 2. 目前主線到底在解什麼

目前主線的核心問題是：

- 給定一個巡航目標外形，先把它投影到目前 dual-beam 結構可表示的 beam-line target shape。
- 用 inverse design 反推出能飛到這個 target 的 `jig shape`。
- 再檢查這個 `jig shape` 是否可行：結構、wire、clearance、manufacturing、離散複材疊層。
- 如果 target cruise shape 不好實現，就回頭調整外形倍率/上反角等低維 shape 參數，再重新 inverse design。

這裡有三個要明確分開的 shape：

1. `requested cruise shape`
   你想要的巡航氣動外形 / target loaded shape。
2. `realizable cruise shape`
   經過結構與 inverse design 後，真正可實現的 loaded shape。
3. `jig shape`
   為了實現該 loaded shape 所需製造出的幾何。

目前 repo 的方向，不應再假設這三者永遠完全重合。

## 3. 正式主線的 canonical workflow

以 repo 現況來說，應把主線理解成下面這條：

1. 輸入巡航氣動外形 / 參考 `.vsp3`
2. 產生或調整 beam-line `target loaded shape`
3. 用 inverse design 求 `jig shape`
4. 用結構主線重新預測 `realizable loaded shape`
5. 檢查 wire / clearance / manufacturing / active-wall / load-refresh
6. 把結構結果往 CFRP tube + discrete layup 收斂
7. 輸出 `jig shape`、`loaded shape`、結構/疊層/診斷 artifacts

如果要用一句較口語的版本：

`VSP -> jig shape -> 調整上反角/倍率 -> cruise VSP -> jig shape -> CFRP -> 離散疊層`

## 4. 正式入口與各自角色

### A. Generic VSP intake

- 入口：`scripts/analyze_vsp.py`
- 角色：讀 `.vsp3`、抽幾何、產 `resolved_config.yaml`
- 注意：它目前預設接到 `examples/blackcat_004_optimize.py`，不是單一命令直通 inverse-design 主線

### B. Inverse-design 主線

- 入口：`scripts/direct_dual_beam_inverse_design.py`
- 角色：從 beam-line target loaded shape 反推 jig shape，並輸出：
  - `jig_shape.step`
  - `loaded_shape.step`
  - target/jig/loaded CSV
  - diagnostics / wire rigging artifacts
- 目前已具備的 shape knob：
  - `--target-shape-z-scale`
  - `--dihedral-exponent`

### C. CFRP / 離散 layup realization

- 入口：`examples/blackcat_004_optimize.py --discrete-layup`
- 角色：把連續 thickness / 結構結果往 discrete CFRP layup 收斂，並做 Tsai-Wu 與 manufacturability 檢查
- 重要定位：**離散 layup 是正式主線，不是附屬 post-process**

### D. Producer / decision interface

- 入口：`python -m hpa_mdo.producer`
- 角色：提供外部 consumer / automation 用的 machine-readable contract
- 重要定位：它是 integration boundary，不是主 physics 問題本身

### E. Drawing-ready baseline package

- 入口：`scripts/export_drawing_ready_package.py`
- 角色：把 `output/blackcat_004/` 裡目前真正要拿去畫圖與 handoff 的 artifact 收成單一 package
- 預設輸出：
  - `output/blackcat_004/drawing_ready_package/geometry/spar_jig_shape.step`
  - `output/blackcat_004/drawing_ready_package/design/discrete_layup_final_design.json`
  - `output/blackcat_004/drawing_ready_package/design/optimization_summary.txt`
  - `output/blackcat_004/drawing_ready_package/data/spar_data.csv`
- 重要定位：它是 **drawing handoff boundary**，不是 external validation boundary

## 5. 目前哪些能力已經是主線的一部分

- dual-beam production mainline
- inverse design（含 exact-nodal / low-dim descriptor matching）
- light load refresh / dynamic design space / higher-fidelity load coupling
- wire / rigging / pretension / tension limit / explicit truss 幾何
- generic VSP intake + VSP -> AVL pipeline
- cruise VSP builder
- dihedral / target-shape scaling 類低維 outer knobs
- CLT / PlyMaterial / discrete layup / Tsai-Wu / ply-drop / layup manufacturability
- drawing-ready baseline package（正式畫圖 / handoff artifact 收斂）

## 6. 目前哪些東西不該再當成主線敘事

- `equivalent_beam` 作為正式 structural truth
- 「這只是一個基於 OpenMDAO 的 6-DOF Timoshenko 梁 FEM solver」這種單層描述
- 把連續 wall-thickness optimum 直接當 final manufacturable answer
- 把 producer / decision interface 當成 physics 主線本體

## 7. 目前專案做到什麼程度

可以做到：

- 從 `.vsp3` 讀幾何並建立可執行配置
- 以 beam-line target loaded shape 做 inverse design，輸出 jig / loaded artifacts
- 用低維 shape knob 掃上反角 / target Z scaling 對結構與可行性的影響
- 將結構結果往 wire / rigging / clearance / manufacturing 可行性收斂
- 將結果往 discrete CFRP / layup / Tsai-Wu 可製造設計收斂

尚未完全收成單一一鍵流程的地方：

- `generic VSP intake -> inverse design -> discrete layup final design`
  目前概念上是同一條主線，但操作上仍分散在多個入口
- 真正 mission-driven 的 `pilot power + weight -> 最佳 cruise shape`
  還是未來演進方向，不是目前已完成的一鍵功能

## 8. 未來演進方向

未來要往這個方向走：

`mission / pilot power / pilot weight`
-> `outer-loop cruise shape design`
-> `inverse design`
-> `realizable loaded shape`
-> `jig shape`
-> `CFRP tube + discrete layup`
-> `manufacturable final design`

換句話說，長期目標不是只做「給定 cruise shape 求 jig」，而是讓系統自己決定最好的 cruise shape，而且保證它最後能被 inverse design 成可製造的 jig / CFRP 設計。

## 9. 對未來 AI agent 的工作規則

如果你是 AI agent，進 repo 後請先遵守以下順序：

1. 先讀這份 `CURRENT_MAINLINE.md`
2. 再讀 [project_state.yaml](project_state.yaml)
3. 再讀 [README.md](README.md)
4. 再讀 [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md)
5. 如果是多人或多 agent 並行，優先看 [docs/task_packs/current_parallel_work/README.md](docs/task_packs/current_parallel_work/README.md)
6. 只有在需要長期脈絡時，才讀 [docs/GRAND_BLUEPRINT.md](docs/GRAND_BLUEPRINT.md)

若上述文件與舊報告/舊 prompt 衝突，以這份文件為準。
