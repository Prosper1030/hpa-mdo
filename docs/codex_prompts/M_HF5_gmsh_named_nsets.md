# M-HF5 — Gmsh Physical Groups → CalculiX NSET 命名

## 前置條件

M-HF1（`hpa_mdo.hifi.gmsh_runner`）已存在，可以把 STEP → `.inp`。

## 背景

現在 `mesh_from_step()` 吐出的 `.inp` 只有 `NALL`、`EALL` 兩個集合，
M-HF2 的 `prepare_static_inp()` 得靠「y 最大節點」硬算 root/tip。
當幾何變複雜（雙翼梁 + 升力鋼索接點）時，靠 y 坐標篩選會誤抓。

解法：在 Gmsh 階段就用 Physical Group 把 root / tip / wire 接點封好，
`.inp` 裡直接出現 `NSET=ROOT`、`NSET=TIP`、`NSET=WIRE_1` …，
CalculiX 可以直接 `*BOUNDARY, ROOT` / `*CLOAD, TIP, 3, -100.`。

## 目標

1. 擴充 `hpa_mdo.hifi.gmsh_runner`：
   - 新增 `NamedPoint`（`{name: str, xyz: tuple[float, float, float], tol_m: float}`）
     dataclass。
   - `mesh_from_step(step_path, cfg, *, named_points: list[NamedPoint] | None=None)`：
     - 在 Gmsh 腳本裡對每個 NamedPoint，找最近節點（`gmsh.model.mesh.getNodes()`
       vs 座標 kdtree），打成 Physical Point / Physical Group。
     - 寫 `.inp` 時 Gmsh 會自動吐 `*NSET, NSET=<NAME>`。
2. 在 `scripts/hifi_structural_check.py`（由 M-HF2 / M-HF3 的 runner 改名或
   合併而成）自動從 `cfg.main_spar.segments` 與 `cfg.lift_wire.joint_y`
   算出 NamedPoints，傳給 `mesh_from_step`。
3. 改 `prepare_static_inp` / `prepare_buckle_inp`：
   - 優先用 `NSET=ROOT` / `NSET=TIP` 做 boundary / load；找不到時才 fallback
     到舊的 y-max 啟發式，但印 WARN。

## 驗收標準

- `tests/test_hifi_gmsh_runner.py` 加 golden：對固定的 STEP + NamedPoints
  輸入，產出的 `.inp` 開頭 200 行 hash 固定。
- `.inp` 裡看得到 `*NSET, NSET=ROOT` / `NSET=TIP` / `NSET=WIRE_1` …。
- 手動驗證：M-HF2 的 tip deflection 數值沒變（±0.5% 以內）。

## 不要做的事

- 不要把 NamedPoint 的 tolerance 硬寫死；用 `cfg.hi_fidelity.gmsh.point_tol_m`
  預設 1e-3 m。
- 不要在 gmsh_runner 裡 import optimizer 模組。runner 必須是單向依賴
  （optimizer → hifi，不能反向）。

## 建議 commit 訊息

```
feat(hifi): M-HF5 Gmsh Physical Group → CalculiX NSET 命名

擴 mesh_from_step 接受 NamedPoint list，把 root / tip / wire 接點封成
Physical Group，.inp 自動吐 *NSET。prepare_static_inp 優先用 NSET 而
不是 y-max 啟發式。主迴圈 tip defl 無變化。

Co-Authored-By: Codex 5.4 (Extreme High)
```
