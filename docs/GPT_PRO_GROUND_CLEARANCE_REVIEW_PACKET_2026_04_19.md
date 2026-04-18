# 給 GPT Pro 的嚴格審查包：Ground-Clearance / Rerun-Aero / Rib Ranking（2026-04-19）

這份內容是要**直接貼給 GPT Pro**做工程審查與決策建議用的。

請把它當成一份**完全自成一體**的專案現況說明。
你**看不到 repo、看不到程式碼、看不到任何內部檔案**，所以請不要假設自己能檢查 implementation 細節。

我需要的不是泛泛而談的方法論，而是：

- 明確問題定義
- 對現在狀態的判斷
- 具體可執行的解法方向
- 清楚的先後順序與取捨

如果你覺得某條路風險太高，也請直接講，不要委婉。

---

## 你要幫我回答什麼

請直接回答下面 6 題：

1. 目前這個專案**最值得請專家介入判斷**的問題，到底是不是 `ground-clearance recovery`？如果不是，真正的核心問題是什麼？
2. 以我們現在的狀態來看，**outer-wing jig ground clearance** 應該優先從哪一類手段去救？
3. 在目前的 `rerun-aero` 合約還不是 full trim / full aeroelastic closure 的情況下，**它是否已經足夠拿來做 candidate ranking**？如果還不夠，最低限度還缺什麼？
4. 現在這套 **rib surrogate / zone-wise rib design**，可以先拿來做什麼程度的工程決策？哪些結論可以說，哪些不能說？
5. 如果你是這個專案的嚴格系統顧問，你會建議我們接下來先做哪 **2 到 3 個工程動作**？請排序，而且每一項都要說明為什麼。
6. 請你提出 **2 到 3 條可執行解法路線**，每條都要包含：
   - 主要想法
   - 為什麼可能有效
   - 最大風險
   - 我會怎麼驗證它

請不要回答「理想上都應該做」。
我要的是：**在資源有限、但願意花 10 到 30 分鐘做一次 quick analysis / search 的前提下，現在應該怎麼選。**

---

## 專案現在的正式主線

這個專案現在的正式主線，不是老式的 parity solver 對舊結果，也不是單純 producer 包裝，而是：

`target cruise / loaded shape -> inverse design -> jig shape -> realizable loaded shape -> CFRP / discrete layup -> manufacturing-feasible design`

這條主線的意思是：

- 先有想要的飛行 / 巡航形狀
- 再反推出地面 jig shape
- 再把它往可實現、可製造的方向收斂
- 最後落到碳纖維管尺寸、離散疊層與下游設計交接

所以現在真正重要的是：

- candidate shape 進來之後，會不會導向合理的 jig
- jig shape 是否真的可製造、可落地
- discrete layup 是否已經能當正式 final design layer
- ranking / selection 是不是在對的物理與工程約束上做判斷

---

## 現在已經完成到哪裡

### A. Drawing-ready baseline package 已完成

目前專案已經有一個可以拿去做設計交接的 baseline package。

它的角色是：

- drawing / handoff truth
- 設計交接基線
- 下游繪圖與工程化依據

它**不是 external validation truth**。

換句話說：

- 對「現在要拿什麼幾何去畫圖」這件事來說，成熟度已經不低
- 但這不等於外部物理驗證已完成

### B. Discrete layup 已是正式 final design layer

目前 discrete layup 不再只是 side output，而是正式的 final design layer。

它已經能輸出：

- machine-readable final design
- human-readable summary
- drawing handoff package

但它目前仍然是：

- 結構層級的 layup schedule

不是：

- 完整工廠施工層級的 ply book

### C. Mac hi-fi / Track C 已被明確降級成 local structural spot-check

專案內建的 `Gmsh -> CalculiX -> structural_check` 是真的能跑的。
但目前的正式定位不是 validation truth，而是：

- local structural spot-check
- 抓幾何 / 支撐 / load mapping 低級錯誤
- 做 deflection / reaction / mass sanity check

它現在**不能**被當成：

- final external validation truth
- final discrete layup truth
- full aeroelastic sign-off

### D. Rerun-aero baseline 已建立

原本外圈比較像：

- legacy load refresh
- 沿用既有 case 的 light refresh

現在已經進化到：

- candidate-owned rerun-aero
- 每個 candidate 可擁有自己的 rerun artifact
- campaign / winner selection 可以分辨 `legacy_refresh` 與 `candidate_rerun_vspaero`

這是一個很重要的進展，因為它讓外圈 candidate ranking 比以前更接近真實。

### E. Rib integration baseline 已接進 candidate contract

rib 現在不再只是報表裡的文字，而是已經進入：

- rib properties foundation
- rib bay surrogate
- passive robustness compare mode
- zone-wise rib design contract

也就是說，rib 已經能影響 candidate / winner selection。

但目前它仍然是：

- surrogate / contract 層

不是：

- 經過高保真或實驗校正後的 rib truth

---

## 最近幾輪真正解掉了什麼

### 1. Parser blocker 已經解掉

先前 `candidate_rerun_vspaero` 會被 OpenVSP 3.45.3 的 `.lod` 欄位 schema 變動卡住。
這個問題現在已經被修掉。

所以目前的情況不是「rerun-aero 根本跑不起來」。

### 2. Explicit wire-truss 假性不收斂已經解掉

先前多組 replay 都掉在：

`Explicit wire truss Newton solve did not converge`

後來修正後，這個問題在已驗證的 replay snapshot 上已經不再是 immediate blocker。

這代表：

- 現在不是 solver 還在亂死
- 而是流程終於能把真正的設計問題暴露出來

---

## 現在真正卡住的是什麼

### 核心 blocker：outer-wing jig ground clearance

目前在真實 replay 中，candidate 已經不再死在 parser 或 solver。
它會跑到 `analysis complete`，也會產生一個 selected candidate。

但 selected candidate 仍然：

- `target_mass_passed = true`
- `overall_feasible = false`
- 主要 failure = `ground_clearance`

這代表：

- 質量本身不是現在最主要的 immediate blocker
- solver 也不是
- 現在最主要的 blocker 是 **jig shape 會碰地**

### 這個 clearance 問題不是小問題，而是大幅穿地

目前已驗證的一個 replay snapshot 顯示：

- `target_mass_kg = 22.0`
- `total_structural_mass_kg ≈ 21.74`
- 但 `jig_ground_clearance_min_m ≈ -1.37 m`

這不是差幾毫米，而是大幅穿過地板。

### 問題位置不在根部，而在外翼尾段

最低點集中在：

- rear spar
- outer wing near tip
- 半翼座標大約 `y ≈ 15.8 ~ 16.7 m`

也就是說：

- 問題不是根部夾持區
- 不是局部小雜訊
- 而是外翼尾段 / 翼尖附近的 jig shape 整體太低

這一點很重要，因為它會直接影響你應該怎麼修：

- 是從外圈 target shape / uplift / dihedral 去修？
- 還是從 rib penalty / surrogate 去修？
- 還是從別的地方修？

這正是我們想請你判斷的地方。

---

## 我們目前的困惑是什麼

我們現在的困惑不是「這個 bug 怎麼修」。

真正不確定的是下面這 3 件事：

### 困惑 1：ground-clearance recovery 的正確解法到底是哪一類？

目前我們傾向的方向是：

- 先從低維 outer-loop knob / candidate seed / search bias 下手
- 例如 uplift / dihedral / target-shape recovery 類手段

但我們不確定：

- 這是不是正確主方向？
- 還是說真正更該優先的是別的 recovery 策略？

### 困惑 2：目前 rerun-aero contract 是否夠格做 ranking？

雖然已經從 legacy refresh 前進到 candidate-owned rerun-aero，
但目前還不是：

- full trim
- full aeroelastic loop closure

所以我們不確定：

- 這樣的 rerun-aero contract 是否已經夠支撐 candidate ranking？
- 還是說現在做 ranking 仍然太早？

### 困惑 3：rib-on ranking 現在能信到什麼程度？

rib 已經進入 candidate contract，這是好事。
但它仍然是 surrogate / zone-wise contract，不是 calibrated truth。

所以我們不確定：

- 它現在可不可以先拿來影響 winner
- 還是只能先當 soft signal
- 什麼程度的決策算合理，什麼程度算過度自信

---

## 我們目前不希望你建議的方向

請不要把重點放在以下方向，除非你認為其中一項其實是唯一正解，而且你願意明說理由：

- 不要把建議重點放在 parser bug 或一般小 bug
- 不要把重點放在單元測試怎麼補得更漂亮
- 不要把重點放在把 Mac hi-fi 升格成 final truth
- 不要建議直接打開 per-rib combinatorial optimization
- 不要建議先做 full free-form 超高維外形優化
- 不要建議直接關掉 clearance gate 或放鬆地板定義

我們現在要的是：

- 在現有主線之上，怎麼把真正的設計 blocker 往前推

---

## 你回答時請遵守的格式

請用下面格式回答：

### 1. 核心判斷

一句話講清楚：
你認為我們現在最值得先解的是什麼。

### 2. 問題重定義

請用你的話重述這個問題，讓我們知道你真的理解：

- 哪些 blocker 已經解掉了
- 哪個才是現在真正的 blocker
- 目前最大的不確定性在哪裡

### 3. 建議方案（至少 2 條，最好 3 條）

每條方案都要包含：

- 方案名稱
- 主要想法
- 為什麼可能有效
- 最大風險
- 我會怎麼驗證它

### 4. 排序後的下一步

請直接列出：

1. 第一個該做的動作
2. 第二個該做的動作
3. 哪些事情現在不要做

### 5. 可說 / 不可說

請直接寫：

- 以目前狀態可以安全說的話
- 目前還不能說的話

---

## 最後提醒

請你把自己當成：

- 看不到 code 的嚴格系統顧問
- 不是幫我們 debug 小 bug
- 而是幫我們判斷「現在該怎麼修這條設計主線」

如果你覺得我們某個方向其實走歪了，請直接講。
如果你覺得我們現在最該做的不是我們以為的那件事，也請直接講。
