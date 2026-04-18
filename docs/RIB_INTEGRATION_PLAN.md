# Rib Integration Plan

> **文件性質**：系統工程整合計畫。
> **目的**：把 rib 從「研究想法 / proxy 假設」推成 repo 可實作、可派工、可逐步驗證的正式工作軌道。
> **搭配文件**：
> - [docs/TARGET_STANDARD_GAP_MAP.md](/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md)
> - [docs/TARGET_STANDARD_PROGRAM_PLAN.md](/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_PROGRAM_PLAN.md)
> - [docs/dual_beam_mainline_theory_spec.md](/Volumes/Samsung SSD/hpa-mdo/docs/dual_beam_mainline_theory_spec.md)

## 1. 先講結論

rib 值得做，而且應該做。
但它現在**不應該直接以主線設計變數的形式開進最佳化**。

目前比較對的做法是分三層：

1. `L1 foundation`：先把 rib properties、spacing、family、derived knockdown 變成正式資料與物理 contract
2. `L2 passive robustness`：先把 rib 對 bay / torsion / link stiffness 的影響變成 reportable、可比較、非主動最佳化的 robustness mode
3. `L3 zone-wise optimization`：等前兩層穩住後，再把 rib 當成有限度的 zone-wise 設計自由度

## 2. rib 應該放在哪裡

rib 不應該放在：

- Track C / hi-fi spot-check
- drawing package 後處理
- 最後才補的手工 engineering note

rib 應該放在：

`rerun-aero candidate loads`
-> `inverse design / structural sub-layout`
-> `rib + spar + layup realization`
-> `winner selection`

白話講：

- rib 是**結構主線的一部分**
- 不是 hi-fi 驗證層的一部分
- 也不是只在最後補一個重量修正係數

## 3. repo 現在的 rib 起點

目前 repo 已經有 rib 的預留位，但還沒有 rib 設計變數主線：

- `dual_spar_warping_knockdown` 已經存在，用來降低 rigid-rib dual-spar torsional coupling 的理想化假設
- `joint_only_equal_dof_parity` 與 `joint_only_offset_rigid` 已有明確邊界
- `dense_finite_rib` 已被理論規格列為目標模式，但程式尚未完成
- `data/rib_properties.yaml` 已經在長期藍圖中被預留

這代表我們不是從零開始，但也還沒到「只差最後一哩」。

## 4. 現在不要做的事

- 不要做 `per-rib` 位置 / 厚度 / 材料自由度
- 不要直接做 rib cutout / topology optimization
- 不要把 rib 第一版工作放進 hi-fi
- 不要在 rerun-aero / candidate load ownership 還在變時，就把 rib 當成正式 winner-selection 變數

## 5. 建議的三層落地順序

## L1：Rib Foundation

### 目標

把 rib 從手動註解與單一 scalar knockdown，升成正式資料層與推導層。

### 這層要完成什麼

- 建立 `data/rib_properties.yaml`
- 定義 rib family：
  - material
  - thickness
  - shear / rotational stiffness proxy
  - spacing guidance
  - usage notes
- 建立從 rib family + spacing 推導 `warping_knockdown` 的 helper / schema
- 保留 backward compatibility，讓舊 config 還能跑

### 這層還**不要**做什麼

- 不要把 rib 變成 outer-loop 設計變數
- 不要碰 hi-fi
- 不要一次把 dense finite rib mode 也做完

### 完成判準

- repo 不再只靠手填 `dual_spar_warping_knockdown`
- rib family 有正式 machine-readable contract
- 測試能驗證 derived knockdown 的行為，而不是只有 YAML 長出來

## L2：Passive Rib Robustness

### 目標

在不把 rib 變成 optimizer knob 的前提下，先讓 rib 影響變成可報告、可比較、可用來發現假最優的 robustness layer。

### 建議拆成兩條

1. `rib bay surrogate`
- 讓 candidate 能輸出 bay-length / local `Δ/c` / shape-retention risk 類指標
- 先當 report 或 soft gate，不必第一天就變 hard constraint

2. `passive rib robustness mode`
- 從 current parity / offset rigid，往更接近 physical rib 的 robustness compare path 推進
- 目標是 sensitivity / robustness，不是立刻取代主線

### 完成判準

- candidate summary 能看見 rib bay 風險，而不是只有 mass
- dual-beam mainline 有更合理的 rib robustness compare path
- 可以比較 parity / rigid / finite-rib 對 ranking 的敏感度

## L3：Zone-Wise Rib Optimization

### 目標

在前兩層穩住後，把 rib 正式納入結構設計空間。

### 正確變數形式

不是每根 rib 一個變數，而是：

- `zone-wise rib pitch`
- `zone-wise rib family`
- mandatory ribs 固定不動：
  - root
  - joints
  - wire / strut attach
  - control / geometry breakpoints

### 建議第一版限制

- 半翼 `4 到 6` 個 zone
- spacing 用 local `Δ/c` 選項，不用全翼固定實體間距
- family 先把 `material + thickness` 綁成同一個離散狀態
- mix mode 先加材料切換懲罰或材料種類上限

### 完成判準

- rib 變數已進入 `optimize_structure(...)` 的概念層
- winner selection 會一起看 spar / rib / layup 的最終結果
- 還沒有必要一開始就碰 per-rib 或 topology

## 6. 推薦的派工順序

### Wave 6：現在就可以做

- `Track L`：rib properties foundation

### Wave 7：等我驗證 Wave 6 後可開

- `Track M`：rib bay surrogate contract
- `Track N`：passive rib robustness mode

這兩包可以平行，前提是 write set 不撞。

### Wave 8：等我驗證 Wave 7 後可開

- `Track O`：zone-wise rib design contract

## 7. 工程判斷摘要

- rib 是高價值項目，但現在正確的切入點是 foundation，不是 full optimization
- repo 距離 rib-ready 不是很遠，但也不是今天直接打開就安全
- 第一版 rib integration 應該先把資料與物理 contract 做對
- 真正的 rib optimization 應該在 rerun-aero outer-loop baseline 之後進場
