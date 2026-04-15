# M-HF1 — Gmsh runner (STEP → CalculiX .inp)

## 背景

Claude 已經在 `docs/hi_fidelity_validation_stack.md` 定下高保真驗證層
藍圖；`configs/blackcat_004.yaml` 已經有 `hi_fidelity.gmsh.*` 區段與
`core.config.GmshConfig` Pydantic 模型（`enabled/binary/mesh_size_m`）。
本任務實作藍圖的 M-HF1：寫一個最小可跑通的 Gmsh runner，吃 STEP
輸出 CalculiX 吃得下的 `.inp` 格式。

**不要嘗試整合到主最佳化迴圈**；此層只在使用者手動觸發的獨立 script
中使用。主 MDO 迴圈絕對不能因為 Gmsh 未安裝就失敗。

## 目標

1. 新增 `src/hpa_mdo/hifi/__init__.py` 與
   `src/hpa_mdo/hifi/gmsh_runner.py`。
2. 在 `gmsh_runner.py` 提供兩個 function：
   - `def find_gmsh(cfg: HPAConfig) -> str | None` —
     先看 `cfg.hi_fidelity.gmsh.binary`，其次 `shutil.which("gmsh")`；
     回傳絕對路徑字串，找不到回 `None`。**不得 raise。**
   - `def mesh_step_to_inp(step_path, out_inp_path, cfg, *, order=1) -> Path | None`
     - 透過 `subprocess.run([gmsh, str(step_path), "-3", "-format", "inp",
       "-clmax", str(cfg.hi_fidelity.gmsh.mesh_size_m), "-o", str(out_inp_path)], check=False, capture_output=True, timeout=600)`
       執行 3D 體網格。
     - Tetra 線性元素即可（`order=1` → Gmsh 預設 `-order 1`）。
     - 成功（returncode==0 且 `out_inp_path` 存在）回 `out_inp_path`，
       否則印出 stderr 並回 `None`。
3. 新增 script：`scripts/hifi_mesh_step.py`，CLI 介面：
   ```
   --config configs/blackcat_004.yaml
   --step output/blackcat_004/wing_cruise.step
   --out  output/blackcat_004/hifi/wing_cruise.inp
   ```
   呼叫 `mesh_step_to_inp`。如 `enabled=False` 或找不到 gmsh，印出
   明確訊息並 `return 0`（**不得 return 非 0**）。
4. 新增測試 `tests/test_hifi_gmsh_runner.py`：
   - `test_find_gmsh_returns_none_when_disabled` — 把
     `cfg.hi_fidelity.gmsh.enabled=False` 並檢查 `find_gmsh` 行為
     （即便 which 找到，也要尊重 enabled flag — 請在 `find_gmsh` 裡加
     `if not cfg.hi_fidelity.gmsh.enabled: return None`）。
   - `test_mesh_step_skips_gracefully_when_gmsh_missing` — 用 monkeypatch
     讓 `find_gmsh` 回 `None`，呼叫 `mesh_step_to_inp` 應回 `None` 且不 raise。
   - Gmsh 實際存在時的 integration test 用 `pytest.importorskip("gmsh")`
     或檢查 `shutil.which("gmsh")`，找不到就 `pytest.skip(...)`。

## 驗收標準

- `pytest tests/test_hifi_gmsh_runner.py` 在 Gmsh 未安裝的機器上全綠。
- 在 Mac mini `brew install gmsh` 後跑
  `python scripts/hifi_mesh_step.py --step output/blackcat_004/spar_jig_shape.step --out output/blackcat_004/hifi/spar_jig.inp`
  應實際產出 `.inp` 檔。
- 主最佳化迴圈 `python examples/blackcat_004_optimize.py` 仍正常輸出
  `val_weight: <float>`；Gmsh runner 不得被主迴圈觸發。

## 不要做的事

- 不要在 `hi_fidelity` 區段加新欄位，若真的需要請先在 prompt 回應
  中提出。
- 不要改 `core/config.py` 的既有欄位型別。
- 不要把 Gmsh 的 Python bindings (`import gmsh`) 當 hard dependency；
  本任務只走 CLI subprocess。

## 建議 commit 訊息

```
feat(hifi): M-HF1 Gmsh runner — STEP → CalculiX .inp via subprocess

新增 hpa_mdo.hifi.gmsh_runner 與 scripts/hifi_mesh_step.py，實作高保真
驗證層藍圖的第一步。遵守「不得影響主 MDO 迴圈」原則：Gmsh 未安裝或
enabled=False 時靜默跳過，不丟 exception，不回非 0 exit code。

Co-Authored-By: Codex 5.4 (Extreme High)
```
