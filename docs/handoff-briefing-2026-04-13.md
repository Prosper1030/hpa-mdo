# HPA-MDO 專案接手簡報

> 日期：2026-04-13
> 文件定位：這份是歷史接手簡報，用來保留當時的背景與轉向脈絡；如果你現在要判斷正式入口或近期優先順序，請先看 [README.md](../README.md)、[docs/README.md](README.md)、[NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md)。

---

## 1. 專案目標

這個專案的核心不是做一個單次分析腳本，而是做一個 HPA 設計引擎：
- 給定目標巡航外形、幾何、材料與結構選項
- 能做結構求解與設計選解
- 能輸出正式設計結果
- 能做 batch / campaign
- 之後還要能接更高階的外圈（氣動穩定性、材料 catalog、更多學科）

目前主線重心在：
- dual-beam 結構
- inverse design
- 外圈 campaign / 穩定性篩選

---

## 2. 已完成到哪裡

### 2.1 dual-beam 結構主線

已經完成新的 dual-beam production mainline，不再只是舊檔 patch。

已完成的重點：
- dual-beam 主線 kernel
- builder / solver / recovery / optimizer_view
- 與 ANSYS/APDL 的 beam-level 對拍
- 主樑/後樑位移、最大位移、反力、質量這些整體量級大致對得上

目前可以把它視為：
- 前期結構設計主線已成立
- 但不是高保真複材最終驗證工具

### 2.2 離散設計空間

已經從連續調參，走到製造導向的離散化設計空間。

已有：
- discrete geometry
- grouped/discrete 變數
- joint geometry + material workflow
- 正式 decision layer：
  - Primary
  - Balanced
  - Conservative

這條線已經不是只會 spit out 一個數字，而是會給正式設計槽位。

### 2.3 材料 proxy

目前不是用真實 vendor 型號，而是用等效材料 package。

已有材料家族：
- main_spar_family
- rear_outboard_reinforcement_pkg

目前材料數值是 preliminary engineering estimate，不是最終供應商料號。
這些數值大致像合理 CFRP 等效值，不像亂填金屬數據，但仍然只能當前期設計 proxy。

### 2.4 producer / autoresearch / campaign

已經做完一整套可持續實驗框架：
- hpa_mdo.producer
- hpa_mdo.autoresearch
- history / compare / provenance / fingerprint / lineage
- input snapshot / archive
- campaign / batch orchestration

也就是說：
這個 repo 不只是 solver，而是已經有第一版可持續做實驗的架構。

### 2.5 STEP 匯出

已可輸出：
- Primary / Balanced / Conservative 對應的 STEP
- inverse-design jig STEP

目前 STEP 是幾何外形模型，偏向：
- 梁外形 sanity check
- CAD / viewer 檢查
- 高保真前處理幾何起點

不是完整裝配 CAD，也不是顯式 sleeve / 接頭 / layup 模型。

---

## 3. 專案中途的重要轉向

原本結構問題是這樣定義的：
- 給定基準幾何
- 在巡航載重下算額外變形
- 用最大變形量（例如 2.5 m）當限制
- 找最輕可行解

後來確認這樣的問題定義不夠對題，因為我們真正想要的是：

**飛在天上的巡航外形要長成指定樣子**

所以主問題已經轉向為：

### Aeroelastic Inverse Design

- 將 VSP / 目標巡航幾何視為 target loaded shape
- 反推出 jig shape
- 再檢查：
  - ground clearance
  - safety / buckling
  - 製造限制
- 後續還要看鋼線張力與穩定性

這條 inverse-design 主線現在已經做出 MVP。

---

## 4. inverse-design 目前做到哪裡

### 4.1 已完成

- frozen-load inverse-design MVP
- `nodes_jig = nodes_target - ΔU`
- target / jig CSV
- jig STEP
- basic feasibility report

後來又補了：
- 1~2 次外層 load refresh
- 這一步之後，forward mismatch 已被壓到很小
- 所以目前可暫時認為：
  - coupling 不是主要問題
  - 主要問題已轉成 search / active constraints

### 4.2 曾經走過的錯方向

一開始 inverse-design 因為 formulation + search 很粗，會掉進：
- 非常保守
- 非常重
- 但 technically feasible 的解

曾經出現：
- 49 kg
- 77.9 kg

後來透過：
- multi-start local refine
- better seed ranking
- search engineering

一路壓回到：
- 約 21.7 kg

這證明：
- 原本超重主因不是 physics
- 而是 search policy

### 4.3 已排除的假設

後來也試過：
- 把 full exact nodal closure 放鬆
- 改成 low-dimensional loaded-shape matching

結果沒有讓重量明顯下降，反而：
- mass 沒明顯改善
- mismatch 變大
- forward mismatch 變差

所以目前可視為已知結論：

**21–22 kg 不是因為 shape matching 太硬。
真正卡住的是 active walls：ground clearance + geometry/discrete boundary。**

---

## 5. 目前最重要的工程診斷結果

### 5.1 主瓶頸不是 failure / buckling

目前 inverse-design 線上，主要卡的不是：
- failure
- buckling

這些通常還有餘量。

### 5.2 主瓶頸是 ground clearance

目前最明確的瓶頸是：
- ground clearance
- 再來是幾何 / 離散牆
- 尤其是：
  - main_radius_taper
  - rear_radius_taper
  - 先前也看過 rear_thickness_step

### 5.3 clearance-aware ranking 已做

目前已經有：
- active-wall diagnostics
- clearance-aware ranking / objective
- 可以把 technically feasible but brittle 的解往後排

這使 selected solution 從：
- 幾乎擦地

變成：
- 還可行、但更重

這代表邏輯正確，但也證明真正瓶頸確實在 clearance。

---

## 6. 鋼線 / rigging 狀態

目前已做最小版 wire / rigging 輸出：
- L_flight
- ΔL
- L_cut = L_flight - ΔL
- Tension_Force
- allowable_tension
- tension_margin

這步很重要，因為它揭露了一個新的核心問題：

**目前 selected solution 的 wire tension margin 是負的**

也就是說：
- 梁的解可能 technically feasible
- 但鋼線其實會先爆

所以現在不能只看結構重量，還必須把：
- wire margin

正式當成設計判斷的一部分。

---

## 7. 最近最重要的新判斷：23 kg 為什麼壓不下來？

我們現在的診斷是：

**真正原因不是 search，也不是 coupling**

而是：

**氣動團隊給的 target cruise shape 上反角太小，導致 Z_tip 天花板太低**

因此發生：
- 為了滿足 Z_jig >= 0
- 系統只能選超硬的管
- 重量被推到 23 kg 左右
- wire tension 也跟著爆

也就是說，目前的主問題已經不再只是內圈結構，而是：

**target cruise shape 本身就太兇**

---

## 8. 新架構方向：Outer-Loop Dihedral Sweep

目前決定的下一步主線不是再硬榨內圈，而是做：

**氣動-結構外圈 campaign**

核心想法：
- 拿現成 .avl 當 source of truth
- 對上反角做 multiplier sweep
- 先用 AVL 做 Dutch Roll 穩定性濾網
- 若穩定，再進 inverse-design 內圈
- 內圈不改載重 physics，只把 target shape 的 Z 座標乘上 multiplier
- 最後比較：
  - stability
  - mass
  - jig clearance
  - wire tension

這是目前已拍板的 MVP-1 路線。

---

## 9. 目前已決定的 MVP-1 外圈規格

應該實作一個單一腳本，例如：
- `scripts/dihedral_sweep_campaign.py`

流程：
1. 讀基準 .avl
2. 對各 section dihedral 乘上 multiplier
3. 產生暫存 .avl
4. subprocess 呼叫本機 avl
5. 解析 .st
6. 抓 Dutch Roll eigenvalue
7. 若 unstable，標記 Aero-Infeasible
8. 若 stable，進 inverse-design 內圈
9. 內圈 target Z 乘上相同 multiplier
10. 寫出 `dihedral_sweep_summary.csv`

第一版：
- 不碰 OpenVSP
- 不讓 AVL 提供新載重
- AVL 只做穩定性濾網
- 先把外圈談判桌打通

---

## 10. 專案目前到哪個階段

### 已完成

- dual-beam 主線
- ANSYS beam-level compare
- 離散 geometry
- material proxy
- decision interface
- producer / autoresearch / campaign
- exact nodal inverse-design MVP
- light load refresh
- active-wall diagnostics
- clearance-aware ranking
- minimal wire / rigging output

### 正在進行

- outer-loop dihedral sweep
- 目的是回答：
  - target dihedral 提高後，結構重量能不能掉
  - wire tension 能不能回安全區
  - Dutch Roll 會不會先爆

### 還沒做

- full coupling
- 動態設計空間
- 真實 vendor catalog
- 高保真自動前處理
- 完整 wire / rigging system
- OpenVSP 自動回寫
- 更多學科整合

---

## 11. 接下來建議優先順序

### 第一優先

完成 `dihedral_sweep_campaign.py` 的 MVP-1

這是目前最重要的主線。
因為它會回答：
- 是不是 target shape 本身太兇
- 增大 dihedral 後，內圈重量是否能明顯下降
- 氣動穩定性會不會先失控

### 第二優先

如果外圈確認某個 dihedral 範圍合理，再做：
- 更細 sweep
- summary / ranking 改善
- 將 wire tension / clearance / mass 一起做決策

### 第三優先

之後才考慮：
- 動態設計空間
- vendor-aware catalog
- 更高 fidelity load update
- rigging system 完整化

---

## 12. 目前需要你接手時特別注意的事

1. **不要再回頭懷疑 inverse-design 主方向**
   - loaded shape → jig shape 這條線是目前主方向
   - 問題不是它錯，而是 target shape 太兇 + active walls 太硬

2. **不要再花時間放鬆 shape matching**
   - 這條已經驗過，不是主因

3. **不要急著擴設計空間**
   - 現在更該先用外圈確認 target dihedral 問題

4. **wire margin 很重要**
   - 這不是裝飾輸出
   - 目前它已經是實際設計瓶頸之一

5. **23 kg 不能當合理答案**
   - 只能當診斷結果
   - 不能當設計成功

---

## 13. 一句話版

這個專案現在的核心已經從「限制額外變形量的結構優化」轉成：

> 給定 target cruise shape，反推出 jig shape 與結構配置；目前內圈已經成立，但真正卡住的是 target dihedral 太小，所以現在要做外圈 dihedral sweep，用 AVL 穩定性濾網 + inverse-design 結構內圈，一起找真正可飛、可做、可撐住鋼線的 target shape 範圍。
