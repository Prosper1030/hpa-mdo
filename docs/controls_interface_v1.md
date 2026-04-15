# 控制組交付介面規範 v1（controls_interface_v1）

本文件定義 HPA-MDO 空氣動力 / 穩定性團隊交付給 **控制組** 的檔案介面。
所有檔案由 `scripts/export_controls_matrix.py` 產生。

---

## 檔案清單

每次執行會在 `output/<stem>/controls/` 目錄產生以下檔案：

| 檔案 | 狀態 | 用途 |
|------|------|------|
| `stability_derivatives.json` | 保證存在 | 全部無因次導數 + 修整狀態 + 質量/慣量 |
| `state_space_A.csv` | 保證存在 | 9×9 狀態矩陣（含表頭） |
| `state_space_B.csv` | 保證存在 | 9×4 輸入矩陣（含表頭） |
| `controls_matrix_report.md` | 保證存在 | 人讀報告（單位、靜穩定判定） |
| `avl_mass.mass` | best effort | 給 AVL 的質量檔（由 M14 產生） |
| `controls_trim.st` | best effort | 原始 AVL `.st` 輸出 |
| `controls_trim_stdout.log` | best effort | AVL subprocess 輸出 |

若 AVL 二進位檔或 `.avl` 幾何缺失，`.st` 與 `.log` 會缺席，但 `A/B/json/md`
仍會以 NaN / 0 佔位值產出，控制組 CI pipeline 不會因此中斷。

---

## 座標系統與符號慣例

- **軸向**：Etkin body axes，`+X forward`, `+Y right`, `+Z down`。
- **原點**：機鼻尖（HPA-MDO 全機 `.avl` 的 `Xref` 定義處）。
- **角度正向**：α pitch-up 為正；β right-yaw-wind 為正；
  `δe` pitch-down 為正（AVL gain=+1 時的 `elevator` 欄位）。
- **單位**：SI。角度導數 `1/rad`；控制面導數 `1/rad`；
  狀態矩陣 A 的對角元素為 `1/s`；B 的元素為「加速度 per rad of deflection」。

---

## `state_space_A.csv` / `state_space_B.csv`

固定欄位順序：

- **狀態向量** `x = [u, w, q, theta, v, p, r, phi, psi]`
  - `u, v, w` = body-frame velocity perturbations [m/s]
  - `p, q, r` = body-frame angular-rate perturbations [rad/s]
  - `theta, phi, psi` = Euler-angle perturbations [rad]
- **輸入向量** `u = [d_elevator, d_aileron, d_rudder, d_throttle]`
  - 全部 rad (pilot-power throttle 目前為 0 佔位欄)

CSV 第一列為欄名、第一行為列名，可直接以 `pandas.read_csv(..., index_col=0)` 讀取。

### 耦合與近似

- 縱向 / 側向-方向解耦；Ixz 交叉慣量忽略（HPA 基線幾乎對稱）。
- `Zq` 保留 `V+Zq` 的完整形式（未做短週期近似）。
- `Xde` 默認為 0（升降舵阻力貢獻可忽略）。

### HPA 基線控制面對應

`data/blackcat_004_full.avl` 僅宣告 `elevator` 與 `rudder`，沒有 `aileron`。
因此 B 矩陣的 `d_aileron` 欄位全部為 0，`Cl_da / Cn_da / CY_da` 在 JSON 內為 `nan`。
要啟用副翼回授，先在 `.avl` 加入 `CONTROL aileron` 區段再重跑。

---

## `stability_derivatives.json` 綱要

```jsonc
{
  "schema_version": "controls_interface_v1",
  "units": { ... },
  "axes": "body (Etkin): +X forward, +Y right, +Z down",
  "trim": {
    "alpha_deg": <float>,
    "beta_deg":  <float>,
    "CL": <float>, "CD": <float>, "Cm": <float>,
    "velocity_mps": <float>,
    "density_kgm3": <float>
  },
  "reference": { "Sref_m2": ..., "bref_m": ..., "cref_m": ..., ... },
  "mass_properties": {
    "mass_kg": <float>,
    "cg_m": [x, y, z],
    "I_principal_kgm2": [Ixx, Iyy, Izz]
  },
  "control_mapping": { "<AVL name>": <d_index>, ... },
  "nondim_derivatives": { "CL_alpha": ..., "Cm_alpha": ..., ... },
  "dim_derivatives_longitudinal": { "Xu": ..., "Zw": ..., "Mq": ..., ... },
  "dim_derivatives_lateral":      { "Yv": ..., "Lp": ..., "Nr": ..., ... },
  "stability_flags": [
    {"name":"Cm_alpha","value": -1.45, "predicate": "<0", "status": "PASS"},
    ...
  ]
}
```

任何 AVL 未輸出的欄位都會以 `NaN`（在 JSON 中為 `NaN` 字面量，解析端請用
`json.loads(..., parse_constant=float)` 或 `math.isnan` 自行篩）。

---

## 靜穩定判定（stability_flags）

| 欄位 | 通過條件 | 意義 |
|------|----------|------|
| `Cm_alpha` | `< 0` | 俯仰靜穩定 |
| `Cn_beta`  | `> 0` | 方向（風標）穩定 |
| `Cl_beta`  | `< 0` | 側向（捲入風）穩定 |
| `Cl_p`     | `< 0` | 滾轉阻尼 |
| `Cn_r`     | `< 0` | 偏航阻尼 |

`controls_matrix_report.md` 內每列會標 `PASS / WARN / UNKNOWN`。
`UNKNOWN` 表示該欄位 AVL 未輸出（通常是舊版或控制面缺失）。

---

## 版本紀錄

- **v1 (2026-04-15)**：初始發佈。含 9-state 解耦縱向 / 側向模型、elevator + rudder 控制、
  M14 質量預算整合。升降舵阻力與 aileron 欄位為 0 / NaN 佔位。
