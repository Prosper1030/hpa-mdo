# 日本側機體設計概念說明母稿

> 本稿是繁中事實母稿，供後續翻成日文或整理成正式對外文件。
> 依據：`docs/reports/2026-05-08_commit_history_report.md`、`CURRENT_MAINLINE.md`、`project_state.yaml`、最新 Go Mode / FEM candidate package。
> 文件定位：說明目前飛機狀態、為什麼重新設計、目前可能有問題的地方。

## 1. 一句話說明

我們目前做的不是單純把既有主翼做結構最佳化，而是在建立一條能從任務需求、氣動外形、柔性主翼變形、製造 jig、CFRP 管材與鋼索支撐一起收斂的機體設計流程。

目前最重要的觀念是：

```text
想要的巡航外形
不一定等於
實際受載後可實現的飛行外形
也不等於
地面製造時需要做出的 jig shape
```

因此，重新設計不是因為前面的工作沒有價值，而是因為前面的 commit history 已經證明：如果不把這三者分開，容易得到看起來漂亮但在結構、地面間隙、airfoil 工作點、鋼索與製造上無法安全落地的結果。

## 2. 目前專案真正的主線

目前 repo 的正式主線可以寫成：

```text
Mission / design requirement
-> spanload and planform concept
-> AVL / lightweight aero screening
-> target loaded shape
-> inverse design to jig shape
-> realizable loaded shape check
-> airfoil / local Cl-Re selection
-> CFRP tube / discrete layup / wire / rib / clearance checks
-> candidate package and FEM/APDL spot-check
```

這條主線的意思是：

- 先決定任務與機體級需求，例如航程、速度、飛行員功率、翼展上限、質量預算。
- 用較快的 AVL / lightweight model 篩出可能的 spanload、上反角、外形倍率與穩定性候選。
- 對候選做 inverse design，求出要製造的 `jig shape`。
- 再檢查受載後的 `realizable loaded shape` 是否真的接近目標巡航外形。
- airfoil selection 不能只看單點低阻，必須用 actual loaded shape 對應的 local `Cl/Re`。
- 最後才把結果落到 CFRP tube、discrete layup、rib、wire、clearance、FEM spot-check。

## 3. 為什麼需要重新設計

### 3.1 舊流程容易把三種形狀混在一起

人力飛機主翼很柔，巡航時會有明顯彎曲與扭轉。若把「想要的巡航外形」、「真實可實現飛行外形」和「地面 jig shape」視為同一個幾何，後面的結構與製造會出現落差。

目前 repo 已經改成用 inverse design 反推出 jig shape，再檢查受載後是否回到目標 loaded shape。這是重新設計的第一個原因。

### 3.2 Airfoil 要跟實際 loaded shape 一起選

主翼 local section 的 `Cl` 和 Reynolds number 會隨 spanload、twist、dihedral、loaded shape 改變。若先選 airfoil，再讓結構改變 loaded shape，原本以為安全的 airfoil 工作點可能不成立。

因此目前 pipeline v2 的順序改成：

```text
先確認 actual loaded shape / AVL local Cl-Re
再做 Tier2 airfoil selection
再做 aero-structure closure
```

### 3.3 低上反角 / 低 Z 版本目前沒有通過

目前 Go Mode candidate package 顯示，在現有 beam-line contract 和 selected-airfoil spanload 下：

- 6.0 deg / 1.804 m target state：mass and clearance blocker
- 6.5 deg / 1.956 m target state：mass and clearance blocker
- 7.0 deg / 2.108 m target state：clearance blocker

目前最低 sampled clear state 約是：

```text
target main tip Z = 2.700 m
beam-line effective dihedral proxy = 8.939 deg
```

這不代表真實飛機不能做成 6-7 deg。它代表目前模型裡的 beam-line Z proxy 和 aerodynamic surface dihedral 還沒對齊，所以不能把 6-7 deg 當成已經通過的設計。

### 3.4 上游 mission/concept line 也需要重整

Birdman upstream concept line 的舊 real Julia/XFOIL run 沒有找到完全可行解，最佳診斷點航程約 16.1 km，距離 42.195 km 仍差很遠。

這表示目前問題不是只要修一個翼型或一個結構參數，而是整個 concept space 需要重新整理：

- span cap 目前以 35 m 作為工程邊界
- wing area 由 span 和 mean chord 決定
- taper、twist、spanload bias 會影響 induced drag 與 local stall
- pilot power、air density、prop efficiency、tail sizing、mass case 都要一起看

## 4. 目前最接近可討論的候選

目前最值得拿來做日本側討論的候選是：

```text
current_avl_compromise_conservative_closed
```

定位：

- 它是 `screening_closed_compromise_candidate`
- 它是目前可送 geometry inspection 和 structural spot-check 的 conservative candidate
- 它不是 final production release

主要數值：

| item | value |
|---|---:|
| P crank | 174.600 W |
| conservative P crank | 178.882 W |
| CL | 1.16853 |
| CDi | 0.0127613 |
| e_CDi | 0.9564 |
| profile CD | 0.00936885 |
| tube mass | 10.8736 kg |
| total structural mass | 13.3736 kg |
| jig ground clearance | 42.39 mm |
| wire tension | 3024 N |
| equivalent tip deflection | 1.543 m |
| target main tip Z | 2.700 m |
| beam-line effective dihedral proxy | 8.939 deg |

這個 candidate 目前的好消息：

- conservative airfoil assignment 是 query-pass。
- aero-structure closure 在目前 screening route 內已經閉合。
- internal fixed-design load-factor estimates 到 2g 仍沒有顯示 tube stress 或 equivalent buckling 先失效。
- 目前第一個外推 fail mode 是 wire tension，而不是 CFRP tube stress。

這個 candidate 目前的限制：

- `42.39 mm` ground clearance 很薄。
- `1.543 m` equivalent tip deflection 對外部審查需要清楚解釋。
- FEM spot-check 中 internal tip `1.5432 m` vs CalculiX `1.3480 m`，差異約 `12.6%`，還不能當 final validation。
- beam-line Z 仍是 spar beam-line proxy，不是 aerodynamic surface final geometry。
- composite local buckling、root fitting、rib fitting、cable hardware、nonlinear aeroelastic stability 尚未 sign-off。

## 5. 目前可能會有問題的地方

### 5.1 Ground clearance margin

目前 candidate 的 jig clearance 約 42 mm。對實際製造和飛行準備來說，這個 margin 很薄，容易被以下因素吃掉：

- jig / spar / rib 製造誤差
- wire pretension setup 誤差
- runway surface variation
- joint compliance
- flight load case difference

日本側文件應避免把這個數字寫成「地面間隙已充裕」。

### 5.2 Wire and fitting loads

目前 internal estimate 的第一個 failure mode 是 wire tension，估計約 `n = 3.030`。這代表後續審查應優先看：

- cable allowable
- termination / clamp / fitting
- root and wire attach details
- pretension adjustment
- load path into main/rear spar

不能只看 CFRP tube stress。

### 5.3 Beam-line proxy vs real aerodynamic geometry

目前 `8.939 deg` 是 beam-line effective dihedral proxy。若日本側關心的是真實 aerodynamic surface 的 total dihedral 或 wingtip height，必須先建立 beam-line 到 aerodynamic surface 的 mapping。

否則溝通上會出現：

```text
工程師 A 說 6-7 deg
模型報告說 8.939 deg
但兩者其實不是同一個幾何定義
```

### 5.4 FEM / CalculiX still spot-check level

最新 FEM route 已經修掉很大的 offset-rigid export 問題，讓 early mismatch 從非常大的錯配變成約 12.6% displacement scale mismatch。但這仍然是 model-basis mismatch，不是 final validation pass。

目前能說的是：

```text
FEM route repaired enough for candidate-relevant equivalent-physics validation,
but not enough for final composite/root/wire hardware sign-off.
```

### 5.5 High-fidelity CFD is paused

主翼 mesh-native CFD / SU2 線已經證明 mesh/SU2 pipeline 可以接起來，但尚未證明：

- credible CL/CD/Cm
- grid independence
- low-Re boundary-layer / transition model
- final drag

因此目前不能用 SU2 當 performance claim 的主要證據。

## 6. 對日本側可以採取的溝通語氣

建議使用下面這種說法：

```text
我們目前已有一個可追溯、可重跑、可交付審查的 conservative screening candidate。
它把氣動、loaded shape、airfoil selection、jig shape、CFRP/wire 初步結構檢查串起來。
但是目前仍不是 final production design，尤其 ground clearance、wire/fitting、beam-line-to-surface geometry mapping、
FEM scale mismatch、composite local buckling/root/rib joint validation 還需要工程審核。
```

避免使用下面這種說法：

```text
目前設計已完成。
目前 CFD 已驗證阻力。
目前 FEM 已完整驗證結構。
目前 6-7 deg 方案已通過。
目前 174-179 W 是最終性能保證。
```

## 7. 建議請日本側一起確認的問題

1. 幾何定義
   - 日本側希望看的 dihedral 是 beam-line、quarter-chord、aerodynamic surface，還是 wingtip height？
2. Clearance
   - 42 mm margin 是否在製造和操作上可接受？
3. Wire system
   - cable, termination, pretension, adjuster, fitting 的可用規格與安全係數應如何定義？
4. Root / rib / joint
   - 哪些接頭要先做 coupon、shell、或 detailed FEM？
5. Mission assumption
   - 42.195 km、速度 6.5-6.7 m/s、pilot power、prop efficiency 是否是日本側也同意的 sizing basis？
6. Evidence level
   - 哪些結果可以叫 concept candidate，哪些必須等外部驗證後才能叫 design candidate？

## 8. 建議正式文件章節

正式日本側文件可以整理成：

1. Project background
2. Why the aircraft is being redesigned
3. Current design workflow
4. Current conservative screening candidate
5. Current known blockers and engineering risks
6. What has been validated, and what is only diagnostic
7. Questions / requested review from Japan side
8. Next engineering steps

## 9. 結論

目前 repo 的 commit history 顯示，設計方向正在從「分析既有外形」轉成「建立能真正收斂到可製造飛機的設計流程」。這是合理的工程演進，因為 HPA 柔性主翼的氣動、結構、製造、鋼索和任務條件不能分開看。

目前最適合對外說明的狀態是：

```text
已有 conservative screening candidate，可以進入日本側幾何與結構審查。
但還沒有 final sign-off。
目前最需要釐清的是 clearance、wire/fitting、beam-line geometry proxy、FEM mismatch、local composite/joint validation。
```
