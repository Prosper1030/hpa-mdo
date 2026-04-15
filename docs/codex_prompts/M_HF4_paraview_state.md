# M-HF4 — ParaView State Generator（一鍵開啟所有驗證結果）

## 前置條件

M-HF2 / M-HF3 已完成。`output/blackcat_004/hifi/` 下至少會有
`static.frd`、`buckle.frd`（或 `.dat`）。

## 背景

驗證跑完後，使用者目前得手動在 ParaView 裡 `File → Open` 每個 `.frd`、
調 colormap、切 displacement warp、疊 undeformed wireframe。流程重複且
容易漏看挫曲模態。本任務做一個 state generator：讀既有的驗證輸出，
吐一個 `.pvsm` 或 `pvpython` 腳本，使用者只要 `paraview state.pvsm`
就看到完整的 dashboard。

## 目標

1. 新增 `src/hpa_mdo/hifi/paraview_state.py`：
   - `def make_pvsm(frd_paths: list[Path], out_pvsm: Path, *,
     warp_scale: float = 1.0, show_modes: int = 3) -> Path`
   - `.pvsm` 是 XML，可以用 string template 拼接（不需 paraview python binding
     就能產生）。範本放在 `src/hpa_mdo/hifi/templates/paraview_state.pvsm.j2`
     用 Jinja2 render。
   - 至少包含：
     - 每個 `.frd` 一個 reader + WarpByVector filter + von Mises colormap。
     - Static step 用第一個 layout；BUCKLE 的前 N 個模態用 Small Multiple
       layout（橫向 3 格）。
     - Camera focal point 設在 `(0, y_mid, 0)`、view up `(0, 0, 1)`，適合
       HPA 長翼展機型。
2. CLI：`scripts/hifi_open_paraview.py`：
   - `--run-dir output/blackcat_004/hifi` 自動找 `static.frd` + `buckle*.frd`，
     呼叫 `make_pvsm`。
   - 若 `cfg.hi_fidelity.paraview.enabled=True` 且 binary 存在，`subprocess.Popen`
     直接打開；否則只印 `open manually: paraview <path>`。

## 驗收標準

- `pytest tests/test_hifi_paraview_state.py`：
  - 在沒有 paraview 的環境下也能 render 出一個合法 XML（用 `xml.etree` parse
    不 raise）。
  - Golden test：把 `make_pvsm([Path("a.frd"), Path("b.frd")], ...)` 產生的
    檔案 hash 過一次存起來，往後 regression。
- 手動驗證：Mac mini 上 `paraview output/blackcat_004/hifi/state.pvsm`
  開得起來，看到 warp、colormap、三個 buckle 模態各自 layout。

## 不要做的事

- 不要 `import paraview`。純字串拼接；ParaView 相容性以 5.11+ 為基準。
- 不要在 state 裡嵌入絕對路徑以外的東西。`.frd` 路徑必須絕對，因為 pvsm
  的相對路徑 resolution 行為不穩定。
- 不要把 pvsm 產生包進 `blackcat_004_optimize.py`；只在 hifi script 裡呼叫。

## 建議 commit 訊息

```
feat(hifi): M-HF4 ParaView state generator + 一鍵開啟腳本

新增 hpa_mdo.hifi.paraview_state 產生 .pvsm XML，涵蓋 static warp +
buckle 前 N 模態 small multiple。scripts/hifi_open_paraview.py 自動
從 run-dir 拼結果並可選擇性地 Popen paraview binary。

Co-Authored-By: Codex 5.4 (Extreme High)
```
