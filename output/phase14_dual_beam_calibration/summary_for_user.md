# 給使用者的中文摘要

## 這次先做了什麼

這一輪不是改結構模型，而是先把 repo 裡到底有哪些結構模型、哪些驗證證據是真的 apples-to-apples、哪些只是 spot-check，全部整理成一個 calibration 規劃包。

核心結論很簡單：

- `equivalent_beam` 沒有被證明「算錯」。
- 它當年通過 ANSYS/APDL parity，證明的是「單一等效梁這個假設下，內部 solver 和 ANSYS 是對得上的」。
- 但現在專案真正要做的設計判斷，已經不是單一等效梁問題，而是：
  - 前樑和後樑怎麼分擔載重
  - wire 怎麼改變支撐路徑
  - 氣動 torque 應該怎麼掛
  - rib/link 拓樸會不會把後樑外翼放大

所以 `dual_beam_production` 才會變成主線。

## `equivalent_beam` 到底證明了什麼

它證明了幾件很重要但範圍有限的事：

- 等效 `EI / GJ` 的數學和質量 bookkeeping 基本一致
- 等效梁的 deflection / reaction / mass 和 ANSYS 在同一套假設下可以對上
- 這條 legacy parity 路線適合拿來做 regression

但它沒有證明：

- 前後樑真實 load sharing
- wire tension-only 行為
- 後樑外翼位移放大是不是合理
- torque ownership 應該用 `MY` 還是前後樑垂直 force couple
- 現在 inverse design / jig shape 主線的真實外部校準已經完成

## 現在應該信什麼，不該信什麼

目前可以先信的：

- `dual_beam_production` 是 repo 內部現在的正式 structural truth
- `equivalent_beam` 的歷史 parity 可以當 regression / legacy reference
- Mac 上的 CalculiX 路線已經有 spot-check 價值，特別是 support reaction 和 tip deflection sanity

目前還不該直接當 final truth 的：

- `dual_beam_production` 已經被外部 FEM 完整驗證
- 任一單次舊 ANSYS/APDL case 就是最終標準答案
- 現在 shell-plus-beam 的 CalculiX 結果可以直接拿來背書 production calibration
- torque ownership 已經完全釘清

## CalculiX / ANSYS 下一步該做什麼

最合理的下一步不是直接衝完整 STEP -> Gmsh -> CalculiX shell mesh。

比較對的順序是先做控制良好的 beam benchmark ladder：

1. 單一簡單 cantilever tube
2. tapered single tube
3. dual beam 無 wire
4. dual beam 有 wire
5. dual beam + lift + `Cm` torque
6. 最後才拿一個凍結的 smooth-tier2 production-like case 來比

這樣做的原因是：

- 先把 `EI`、BC、load mapping、wire、torque ownership 一層一層釘清
- 不然一開始就用 shell mesh，比到最後就算差了，也不知道是 beam 模型錯、wire 錯、torque 錯，還是 mesh 本身有問題

## 這件事能不能做

能做，而且 repo 其實已經有不少材料可以接：

- ANSYS equivalent-beam export
- dual-spar spot-check route
- dual-beam production compare route
- Gmsh / CalculiX structural_check
- benchmark compare helper

但有一個很值得先警覺的點：

- `dual_beam_production` 目前在 internal mode 定義、測試、ANSYS export 註解、以及 report wording 之間，對 torque ownership 的描述並沒有完全一致

這不代表主線一定錯，但代表 Round 2 做 benchmark 前要先把這個 contract audit 清楚，不然很容易做出表面上很完整、其實不是同一題的 compare。

## 本輪最重要的工程判斷

今天如果要問一句最直接的話：

> `equivalent_beam` 有價值，但它只證明了舊的等效梁世界是自洽的；它沒有替現在的 `dual_beam_production` 做完外部校準。

所以接下來應該做的是：

- 保留 `equivalent_beam` 當 legacy parity / regression
- 用控制好的 benchmark ladder 去校準 `dual_beam_production`
- 在外部 beam benchmark 沒跑完前，不要把 calibration factor 塞進 production code
