# Codex 任務：清理低優先警告與統一 KS ρ 設定

## 背景

Finding 1/2/3 與 P4#16 屈曲約束都已完成（46 tests passing）。
這是一個**純清理任務**，沒有物理/數學變動，適合一次處理完三個小項目。

## 必讀

- `/Volumes/Samsung SSD/hpa-mdo/CLAUDE.md`
- `/Volumes/Samsung SSD/hpa-mdo/docs/codex_tasks.md`（「已知小問題」區塊）

## 任務清單

### 任務 1：修正 `optimizer.py` 的 `ndim>0 array→scalar` DeprecationWarning

**位置**：`src/hpa_mdo/structure/optimizer.py` 第 275-276 行附近

**現象**：用 `float(prob.get_val("..."))` 在 OpenMDAO 3.28+ 會報 deprecation，因為 `get_val` 回傳 shape=(1,) 或 (n,) 的陣列。

**修法**：改用 `float(np.asarray(prob.get_val("...")).item())` 或 `float(prob.get_val("...")[0])`。與 `test_twist_constraint.py` 裡 `_get_scalar` 輔助函式的寫法一致。

**驗收**：
- `python -W error::DeprecationWarning examples/blackcat_004_optimize.py` 不再觸發此類警告
- 功能不變，`val_weight` 數值維持一致

---

### 任務 2：修正剩餘的 `np.trapz` DeprecationWarning

**範圍**：整個 repo（含 `tests/` 與 `src/`），用 grep 找所有 `np.trapz` 呼叫。

**修法**：全部改為 `np.trapezoid`（NumPy 2.0+ 的新名，向後相容）。

**驗收**：
- `grep -rn "np.trapz" src/ tests/ examples/ scripts/` 回傳 0 筆
- `pytest tests/ -W error::DeprecationWarning -q --ignore=tests/test_blackcat_pipeline.py` 通過

---

### 任務 3：統一 `BucklingComp` 與 `TwistConstraintComp` 的 KS ρ 參數（從 config 讀）

**現況不一致**：
- `BucklingComp`：`ks_rho=50.0`（硬編碼 default）
- `TwistConstraintComp`：`rho=100.0`（硬編碼在 compute 裡）

**修法**：
1. 在 `src/hpa_mdo/core/config.py` 的 `SafetyConfig` 加入：
   ```python
   ks_rho_stress: float = Field(100.0, description="KS aggregation sharpness for stress constraint")
   ks_rho_buckling: float = Field(50.0, description="KS aggregation sharpness for buckling constraint")
   ks_rho_twist: float = Field(100.0, description="KS aggregation sharpness for twist constraint")
   ```
2. 在 `configs/blackcat_004.yaml` 的 `safety:` 區塊加入對應三行（可省略，會用 default）
3. 修改 `oas_structural.py`：
   - `BucklingComp` 傳入 `ks_rho=cfg.safety.ks_rho_buckling`
   - `TwistConstraintComp` 初始化加入 `ks_rho` option，從 `cfg.safety.ks_rho_twist` 傳入
   - `KSFailureComp` 如果有 rho 參數也順便統一
4. `TwistConstraintComp.compute` 的 `rho = 100.0` 改為 `self.options["ks_rho"]`

**⚠️ 重要**：
- **不要改預設數值**（twist 維持 100、buckling 維持 50），只是把它們搬到 config 變成可調參數
- 維持目前的無因次化邏輯（twist 的 theta_scale 正規化、buckling 的 max-shift）不要動

**驗收**：
- `pytest tests/ -q --ignore=tests/test_blackcat_pipeline.py` → 46 tests 全過
- `python examples/blackcat_004_optimize.py` → `val_weight` 與先前 (14.3579) 差異 < 0.01%
- `test_buckling_comp_check_partials` 與 `test_twist_max_uses_all_nodes_not_just_tip` 都還通過

---

## Git 工作流

**每個任務一個 commit**（共 3 個），commit 訊息使用繁體中文：

1. `fix: optimizer.py 修正 get_val array→scalar DeprecationWarning`
2. `fix: 全面改用 np.trapezoid 取代 np.trapz`
3. `refactor: KS aggregation ρ 參數統一從 config.safety 讀取`

完成後執行：
```bash
git pull --rebase --autostash origin main
git push origin main
```

## 不要做的事

- ❌ 不要改 KS ρ 的預設數值
- ❌ 不要動 buckling 公式或 twist 的無因次化邏輯
- ❌ 不要動 Finding 1/2/3 或 P4#16 剛修好的程式
- ❌ 不要 refactor 其他看起來「可以改進」的東西
