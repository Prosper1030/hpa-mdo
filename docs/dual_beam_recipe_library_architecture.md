# Dual-Beam Recipe Library 與離散搜尋架構

> **文件性質**：正式主線架構文件。  
> **來源背景**：這份文件把 [docs/research/架構設計分析.md](/Volumes/Samsung SSD/hpa-mdo/docs/research/架構設計分析.md) 的審查結論，轉成 repo 的正式實作方向。  
> **目的**：回答兩件事：
> 1. 這份審查結果應該落在哪裡實作。
> 2. 近期應該先做哪一段，才會真正讓主線更接近目標流程標準。

## 1. 標準結論

這份審查結果應該落在：

`discrete layup / material recipe library`
-> `property-based selector`
-> `spanwise discrete search`
-> `zone-dependent thinning / ply-drop rules`

它**不應該**優先落在 `Track C / hi-fi spot-check`。

原因很簡單：

- 它在修正的是 **設計空間與選擇邏輯**
- 不是在修正 **高保真驗證工具**

所以這份文件屬於目標流程標準中的 **Stage E / Stage F**，也就是：

`discrete CFRP layup`
-> `best design selection`

不是 Stage G 的 hi-fi validation。

## 2. 目前架構問題

目前 repo 的主線雖然已經把 discrete layup 接回 final design layer，但核心架構仍偏向：

`continuous equivalent thickness`
-> `固定 balanced / symmetric catalog round-up`
-> `laminate / failure post-check`

這種做法可以當中期 baseline，但不應該被當成最終架構。

主要原因：

- 真正重要的自由度仍然被鎖在 fixed family 裡
- selector 邏輯還偏向「找到第一個夠厚的解」
- spanwise 離散分佈還沒有被當成正式搜尋問題
- thickness floor 與 ply-drop rule 還太像全翼一刀切

## 3. 正式實作落點

### A. Recipe library foundation

這一層是第一優先。

應放在：

- [src/hpa_mdo/structure/material_proxy_catalog.py](/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/material_proxy_catalog.py)
- [docs/dual_beam_preliminary_material_packages.md](/Volumes/Samsung SSD/hpa-mdo/docs/dual_beam_preliminary_material_packages.md)
- [tests/test_material_proxy_catalog.py](/Volumes/Samsung SSD/hpa-mdo/tests/test_material_proxy_catalog.py)

這一層的目標不是直接做 full optimization，而是先把 catalog 從「固定比例族」升成「功能型 recipe 庫」。

最低限度應能表達：

- bending-dominant recipes
- balanced torsion recipes
- joint / hoop-rich local recipes

### B. Property-based selector

這一層與 recipe library 緊密相連，但應在 foundation 穩住後接進 discrete layup selector。

應主要落在：

- [src/hpa_mdo/utils/discrete_layup.py](/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/utils/discrete_layup.py)
- [tests/test_discrete_layup.py](/Volumes/Samsung SSD/hpa-mdo/tests/test_discrete_layup.py)
- [tests/test_discrete_layup_main_pipeline.py](/Volumes/Samsung SSD/hpa-mdo/tests/test_discrete_layup_main_pipeline.py)

selector 的正式方向應從：

`第一個 wall thickness 不小於 target 的 catalog`

改成：

`最輕且滿足 EI / GJ / strength / buckling / manufacturing gate 的 recipe`

### C. Spanwise discrete search

這是第二優先的大改動，但應放在 recipe library 與 selector foundation 之後。

建議落在：

- 新增 `src/hpa_mdo/utils/discrete_spanwise_search.py`
- [src/hpa_mdo/utils/discrete_layup.py](/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/utils/discrete_layup.py)
- [tests/test_discrete_layup.py](/Volumes/Samsung SSD/hpa-mdo/tests/test_discrete_layup.py)
- 新增 `tests/test_discrete_spanwise_search.py`

正式方向是用 **dynamic programming / shortest-path 類方法**，而不是先跳去高成本 GA。

原因不是保守，而是這個問題本質上是：

- 一維 spanwise 鏈狀決策
- 有 clear transition rules
- 有局部製造限制

這類問題比較像 DP 的主場。

### D. Zone-dependent thinning / ply-drop rules

這是第三優先，必須放在前兩層之後。

應主要落在：

- [src/hpa_mdo/utils/discrete_layup.py](/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/utils/discrete_layup.py)
- [docs/dual_beam_preliminary_material_packages.md](/Volumes/Samsung SSD/hpa-mdo/docs/dual_beam_preliminary_material_packages.md)
- [tests/test_discrete_layup.py](/Volumes/Samsung SSD/hpa-mdo/tests/test_discrete_layup.py)

原則：

- root / joint zone 可以保守
- clean outboard span 不應永遠被同一個 global floor 鎖死
- 放寬規則時，必須搭配 termination / local reinforcement rule

## 4. 與 outer loop 的關係

這份審查不是只有材料子系統的事情，它也會直接影響外圈選 design 的邏輯。

因此它還必須接到：

- [scripts/direct_dual_beam_inverse_design_feasibility_sweep.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_inverse_design_feasibility_sweep.py)
- [scripts/dihedral_sweep_campaign.py](/Volumes/Samsung SSD/hpa-mdo/scripts/dihedral_sweep_campaign.py)
- [examples/blackcat_004_optimize.py](/Volumes/Samsung SSD/hpa-mdo/examples/blackcat_004_optimize.py)

原因：

- 如果 outer loop 只看 continuous thickness 結果，就還是在錯的設計空間裡選 winner
- discrete final verdict 必須回寫到 candidate selection
- requested / realizable 的比較要吃到真正比較接近 final design 的結構結果

## 5. 與 hi-fi 的邊界

這份架構升級**不屬於** hi-fi validation 主體。

不該先做的事：

- 不先把它丟進 `src/hpa_mdo/hifi/**`
- 不先靠 CalculiX / spot-check 去補設計空間本身的缺口
- 不先把 Track C 升格成這條工作的 blocker

Track C 的角色仍然是：

`local structural spot-check`

也就是：

- 抓 deck / mass / load mapping / BC 的低級錯
- 做 finalist diagnosis
- 做 sanity check

不是在這一層代替 recipe-library 架構工作。

## 6. 近期執行順序

正式順序應是：

1. `recipe library foundation`
2. `property-based selector`
3. `spanwise discrete search`
4. `zone-dependent thinning / ply-drop`
5. `outer-loop winner logic consuming the new discrete verdict`

這個順序的重點不是把事情切得很細，而是避免做反：

- 不能先放鬆 thinning rule，卻還用錯的 catalog
- 不能先上更重的 global search，卻仍在錯的設計空間裡找
- 不能先期待 hi-fi 幫忙補主線設計空間的洞

## 7. 快速分析的計算預算

近期 quick analysis 不應再用「幾分鐘內一定要跑完」當硬約束。

目前的正式假設改成：

- 若能明顯提升設計品質，單次 quick analysis / candidate search 容許約 `10 到 30 分鐘`
- 這份預算應優先花在：
  - 更多低維 aero-shape candidates
  - 更完整的 recipe family 比較
  - 更乾淨的 spanwise discrete search
- 不應優先花在：
  - 對每個候選都跑更重的 hi-fi
  - 高維 free-form 無界搜尋

## 8. 系統工程判斷

這份審查結果的價值很高，因為它指出的不是單點 bug，而是：

- 目前的設計空間太窄
- 目前的 selector 太保守
- 目前的 discrete 分佈還沒有成為正式搜尋問題

因此它應該被視為：

`主線設計架構升級的正式輸入`

而不是：

`研究備忘錄`

或

`高保真驗證附錄`
