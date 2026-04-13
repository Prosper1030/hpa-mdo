# 連續 HPA 結構設計到離散碳纖維管型錄選擇的兩階段搜尋演算法架構

## 執行摘要

本報告提出一套「實用級」兩階段搜尋（Two-Stage Search）架構，用來把以連續變數描述的 HPA（以碳纖維管為主的桿件/樑件結構）設計，轉換成可直接採購與裝配的「離散碳管型錄型號」組合。核心精神是：先用連續模型快速找到接近最優的「理想幾何/性能目標」，再在離散型錄空間中以「候選集縮減 + 啟發式取整 + 分支定界」把解精煉至可行且高品質（必要時可提供最優性界）離散解。此思路與結構工程中「型錄斷面選擇」的 MILP/MINLP 研究方向一致：型錄離散化會讓問題變成混合整數（常伴隨非線性）並帶來指數級組合爆炸，因此必須用良好的放鬆、界限與剪枝策略控制搜索樹規模。citeturn12view0turn5search4turn13search5turn8search1

連續階段建議用 SQP 類連續優化器（如 SLSQP）或更強健的 NLP 求解器（如 Ipopt）求解：SLSQP 在 entity["organization","SciPy","python scientific library"] 中提供，支援邊界、等式與不等式約束，並以停止準則（如 `ftol`）同時控制目標值變化與約束違反程度。citeturn0search4turn0search0turn0search1turn8search13turn8search3

離散階段的關鍵在於「映射」：將連續解（例如每段管的外徑、內徑/壁厚、等效模量、質量/長度、成本）轉成少量候選型號，再用（1）快速啟發式取整取得可行解當作 incumbent（上界），（2）以分支定界（B&B）在候選空間內做有界搜索並透過放鬆問題給下界以剪枝。此流程可類比 entity["organization","COIN-OR Couenne","open-source MINLP solver"] 與 entity["organization","BARON","global MINLP solver"] 等全球 MINLP 求解器的空間分支定界精神：以界限與變數域縮減來加速搜尋。citeturn13search5turn9search3turn9search6turn8search1turn8search19

物理裝配（套接/接頭）限制往往是「離散化後最容易翻車」的來源：即使連續解性能很漂亮，只要相鄰管的 OD/ID 配合、公差、黏著膠層（bond gap）、接頭厚度、台階（step）限制不滿足，就無法裝配。報告因此提供一組可直接放進連續約束、非線性約束或混合整數（指示/Big‑M/析取）模型的數學式，並用 ISO 配合公差觀念與圓柱固定/黏著產品之許可間隙資料做參考（例如圓柱固持膠可容許到特定級距的間隙）。citeturn4search4turn4search1turn4search5turn15view0

---

## 問題定義與假設

### 問題敘述

目標是選擇一組離散碳纖維管型號（型錄品）與必要的接頭/墊片/黏著方案，使得多段組合結構在載重、剛度、強度/安全係數、幾何與裝配限制下達到設計目標（常見：最輕、最便宜、或在重量/剛度/成本之間折衷）。型錄通常直接提供每支管的 ID/OD、壁厚、長度、重量（或密度）、纖維鋪層/模量等資訊；例如市面碳管商品頁常列出 OD、ID、壁厚、近似重量與纖維模數等。citeturn2search5turn2search2turn2search1turn2search8turn10search3

> 名詞提醒：使用者文字中的「HPA」縮寫在航空脈絡常指 Human‑Powered Aircraft；但在其它領域也可能指高壓空氣（High‑Pressure Air）等。此處依題意採「以碳纖維管為主要構件的結構設計」解讀；若實際是特定產品/系統縮寫，僅需在本架構中替換載荷與約束模型即可。citeturn3search0turn3search1turn3search3

### 已知與未指定參數一覽（必要時以「未指定」標註）

下表刻意把「你沒講清楚但會決定模型長相」的部分列出，方便你後續補齊資料或做情境化設定。

| 類別 | 參數（符號示意） | 狀態 | 備註 |
|---|---:|---|---|
| 結構分段 | 段數 \(K\)、各段長度 \(L_k\) | **未指定** | 是否為線性串接（鏈狀）或含分岔/框架（網狀）會影響求解難度；本報告以「相鄰段有套接」為主軸，可延伸到一般桿系/框架。citeturn12view0turn5search4 |
| 型錄 | 型號數 \(N\)、每型號資料（OD/ID/成本/重量/模量…） | **未指定** | 百至千種型號是常見量級；型錄資料品質（是否含公差）會強烈影響可行率。citeturn2search8turn2search5turn2search1 |
| 設計變數（連續） | 每段 \(D_k\)（外徑）、\(d_k\)（內徑）、\(t_k\)（壁厚）、材料等效 \(E_k, G_k\) | **部分未指定** | 若型錄已給定，離散階段可直接用型錄常數；連續階段可把它們當連續放鬆變數或由 \(D_k,d_k\) 推導截面。citeturn11search2turn11search3turn10search3 |
| 目標函數 | 重量/成本/剛度/安全係數/多目標 | **未指定** | 本報告用「可加權單目標」與「Pareto 多目標」兩種寫法描述；對多目標可搭配演化算法框架。citeturn6search1turn6search0 |
| 載重與邊界條件 | 外力、分佈載重、扭矩、支承/固定方式 | **未指定** | 會決定是簡化樑公式、桿件公式或需要 FE 分析；先用簡化解析式可快速形成可用的 MILP/MINLP。citeturn10search0turn10search1 |
| 失效準則/限制 | 應力、撓度、屈曲、疲勞、接頭剪力/剝離 | **未指定** | 若含黏著接頭，常需額外接頭強度模型；文獻指出黏著接頭的設計與失效分析是獨立且重要的議題。citeturn4search2turn4search10 |
| 裝配/公差 | 管 OD/ID 公差、裝配裕度、黏著膠層厚度、接頭厚度、台階限制 | **部分未指定** | 可用 ISO 配合觀念建模，並用「最壞情況」把公差轉成必滿足不等式。citeturn4search4turn4search12turn4search1 |

---

## 兩階段搜尋策略架構

### 連續放鬆模型的建立與求解

**目的**：在忽略「只能選型錄離散集合」的限制下，先解一個連續 NLP，快速找到每段管的理想幾何（例如 \(D_k,d_k\)）與性能分配，作為離散搜索的「導航訊號」（target）。這類「先連續、再離散」的思路在離散桿件/斷面設計領域常見：離散化後問題會變成 MINLP，直接全域搜索很昂貴，因此常先做連續放鬆取得良好起點或界限。citeturn5search4turn5search13turn12view0

#### 連續變數（示意）

對每一段 \(k=1,\dots,K\)：

- 幾何：外徑 \(D_k\)、內徑 \(d_k\)、壁厚 \(t_k=(D_k-d_k)/2\)，且 \(0<d_k<D_k\)。
- 可選：等效彈性模數 \(E_k\)（若你在連續階段允許「等效材料/鋪層」也連續化），或固定為某型錄族群的值（例如標準模數碳纖維約 33 Msi 等級的材料常被商品資料引用）。citeturn10search3turn2search5

截面量（常用於簡化樑/桿分析）可由幾何推得：

- 截面面積  
  \[
  A_k=\frac{\pi}{4}(D_k^2-d_k^2)
  \]
  （空心圓截面公式）citeturn11search2turn11search0
- 二次面積矩（彎曲慣性矩）  
  \[
  I_k=\frac{\pi}{64}(D_k^4-d_k^4)
  \]
  （空心圓截面公式）citeturn11search3turn4search3turn11search2

#### 目標函數（因未指定，給「可落地」的通用模板）

常見單目標加權式（可用於工程折衷）：

\[
\min_{D_k,d_k,\dots}\;\;
J
=
w_m \sum_{k=1}^{K}\rho_k A_k L_k
+
w_c \sum_{k=1}^{K} C_k(D_k,d_k)
+
w_s \, \Phi(\text{撓度/應力/屈曲裕度})
\]

- 第一項是重量（或質量）最小化，型錄/商品頁常提供近似重量或密度資訊可用於校正。citeturn2search5turn2search1  
- 第二項是成本模型（若你有材料/加工/接頭成本）。  
- 第三項可用「違反程度的懲罰」或「最大化最小安全係數」的等價轉換。

若你傾向多目標（重量 vs 剛度 vs 成本），可在連續階段先求 Pareto 前緣，再把每個 Pareto 解送進離散階段做映射；在 Python 生態系中，有成熟的多目標演化算法框架可用。citeturn6search1turn6search13

#### 連續約束（示意：性能 + 幾何 + 裝配的「放鬆版」）

1) **幾何界限**（由型錄範圍或製程限制給定）
\[
D_k^{\min}\le D_k \le D_k^{\max},\quad
d_k^{\min}\le d_k \le d_k^{\max}
\]

2) **撓度限制**（若採樑模型，示意以懸臂端點載重）
\[
\delta_B=\frac{F L^3}{3 E I} \le \delta_{\max}
\]
這是經典 Euler–Bernoulli 樑的端載懸臂撓度公式，常用於快速設計估算。citeturn10search0turn10search8

3) **屈曲限制**（若有軸壓桿件，示意 Euler 屈曲）
\[
P \le \frac{\pi^2 E I}{(K L)^2}
\]
用於細長柱臨界載重估算；在早期設計可提供「需要多粗」的量級訊號。citeturn10search1turn10search9

4) **裝配/台階的放鬆**  
連續階段可先用「理想化」的相鄰段幾何差限制（例如先忽略公差與接頭細節）：
\[
|D_{k+1}-D_k|\le \Delta_{\text{step}}^{\max}
\]
真正可裝配的詳細限制在下一節以完整數學式處理（離散階段務必用完整版，否則會出現「連續解漂亮、離散不可裝」）。citeturn15view0

#### 連續求解器選擇與建議

- SLSQP（SQP 類）在 SciPy 的 `minimize(method="SLSQP")` 提供，支援邊界、等式與不等式約束，並以 `ftol` 等參數作停止判定（同時關注最適性條件與約束違反）。citeturn0search4turn0search0turn0search1  
- 若模型較硬（約束多、尺度差很大、或需要更穩健的 NLP），建議使用 entity["organization","Ipopt","COIN-OR NLP solver"]（可透過 entity["organization","cyipopt","python wrapper for ipopt"] 在 Python 呼叫），它是大型非線性規劃常用的內點法求解器。citeturn8search13turn8search3turn8search17

> 實務提示：連續階段通常是「局部最適」。你若擔心落入差的局部解，可做多起點（multi-start），或先用粗略全域法（例如隨機/演化）找到幾個不錯的起點再交給 SLSQP/Ipopt 精修。這種「全域找起點 + 局部精修」的混合策略在工程最佳化很常見。citeturn6search2turn6search3turn6search0

---

### 從連續解到離散型錄的映射方法（多種可併用）

設型錄共有 \(N\) 種管型號 \(m=1,\dots,N\)，每個型號有資料向量  
\[
\mathbf{p}_m = [D_m,\; d_m,\; \rho_m,\; E_m,\; c_m,\;\dots]
\]
連續解給出每段目標 \(\mathbf{p}_k^\*\)。

映射的核心不是「四捨五入」這麼簡單，而是要把「可行性（含套接公差）」與「性能（重量/剛度）」一起納入距離或篩選規則。

#### 方法一：最近鄰（Nearest Neighbor）/加權距離

對每段 \(k\)，以加權距離選擇最接近的型號：
\[
m_k
=
\arg\min_{m}
\;
\bigl\|\mathbf{W}(\mathbf{p}_m-\mathbf{p}_k^\*)\bigr\|_2
\]
其中 \(\mathbf{W}\) 是尺度化/重要度權重（例如直徑以 mm、成本以元、模量以 GPa，需先正規化）。

**優點**：超快，適合當第一個 baseline。  
**缺點**：各段獨立選，容易在「相鄰套接」時失敗；因此通常要搭配後處理或改用「含相鄰約束的映射」。citeturn15view0turn4search4

#### 方法二：分段映射（Piecewise Mapping）

把直徑或壁厚的連續範圍分段（例如依 OD 區間），每段只允許選該區間的型號，再做最近鄰。此法本質是「先做粗分類，再做細挑」，可大幅縮小搜尋空間。

#### 方法三：啟發式四捨五入（Heuristic Rounding）

常見技巧包括：

- **向內/向外偏置取整**：若你最在意套接可行性（需要留膠層/間隙），可對「外徑」採向下取整、對「內徑」採向上取整，以提高組裝機率；反之若追求剛度則可能偏向選更粗。  
- **依約束敏感度取整**：連續求解器可提供 Lagrange multiplier / 近似敏感度訊號（哪些約束最緊）；對緊約束段採保守取整（例如選更厚壁/更大 I）。SLSQP 屬 SQP 方法，概念上就是在解一系列二次近似並對約束做一階近似，因此敏感度訊號在工程上常被拿來做離散化決策參考。citeturn0search1turn0search4turn0search9

#### 方法四：候選集（Top‑M）＋全局組合選擇（推薦最實用）

對每段先取 Top‑M 候選（例如 5～30 個），再在整體組合上選最好的可行解。這是處理百～千型號時最常見的工程作法，因為原始組合數是 \(N^K\)（爆炸），但縮成 \(M^K\) 後才可能做 B&B 或 DP。citeturn12view0turn5search4

**候選集生成的硬篩選（先過濾可行再談距離）**通常很有效：

- 先用直徑配合與公差窗口把明顯不可套接者剔除（見下一節數學式）。citeturn4search4turn4search1turn15view0  
- 再用加權距離或成本/重量排序取 Top‑M。

#### 方法五：用 SOS/凸組合做「連續到離散的橋接」（進階）

若型錄型號可依某個順序（例如 OD 由小到大）排列，可用 SOS2/凸組合讓連續模型「只混合相鄰兩個型號」，先得到分數型（fractional）的近似，再在離散階段把它取整；SOS 的概念本來就是在分支定界中提供更聰明的分支方式與更緊的放鬆。citeturn5search3turn5search11turn5search7

---

### Branch-and-Bound 與 Heuristic Rounding 的整合流程（含 mermaid）

下面給一個「能直接落地寫程式」的整合式流程：先用啟發式快速找到可行 incumbent（上界 UB），再用 B&B 用放鬆問題或下界估計（LB）剪枝。

```mermaid
flowchart TD
  A[輸入資料: 型錄、段長、載重、邊界、公差/裝配規範] --> B[階段一: 連續放鬆NLP]
  B --> C[連續求解器: SLSQP/Ipopt 等]
  C --> D[取得連續目標解 x* (D_k*, d_k*, ...)]
  D --> E[候選集生成: 每段Top-M + 硬性裝配篩選]
  E --> F[啟發式取整/修復: 生成可行離散解]
  F --> G[Incumbent (UB): 目前最佳可行解]
  E --> H[階段二: 分支定界B&B]
  H --> I[節點: 固定部分段的型號]
  I --> J[求下界LB: 放鬆/簡化子問題]
  J --> K{LB >= UB?}
  K -->|是| L[剪枝: 不再展開]
  K -->|否| M{節點可行且已全決策?}
  M -->|是| N[更新UB/Incumbent]
  M -->|否| O[分支: 選下一段/變數]
  O --> I
  N --> H
  L --> H
  H --> P[停止條件: gap/時間/節點數]
  P --> Q[輸出: 離散型號 + 接頭/墊片 + 驗證報告]
```

上述流程與全球 MINLP 求解器的核心思想一致：以分支定界為主架構，配合界限、啟發式可行解與界縮減技術。citeturn9search3turn13search5turn8search1turn1search1

---

### 收斂準則、剪枝策略與複雜度估計

#### 收斂準則（建議）

- **連續階段（NLP）**：  
  使用求解器的 KKT/停止判定；以 SLSQP 為例，`ftol` 會同時影響目標與約束違反、步長與函數變化的停止條件（工程實務上常再加一條「最大約束違反 ≤ ε」的明確檢查）。citeturn0search0turn0search4

- **離散階段（B&B）**：  
  常用相對 gap：
  \[
  \text{gap}=\frac{UB-LB}{\max(1,|UB|)}\le \varepsilon
  \]
  並搭配時間上限、節點上限。全球 MINLP 求解器手冊通常也以類似的 gap/界限概念做終止（例如 BARON 以 branch‑and‑bound 類演算法並結合 range reduction）。citeturn8search1turn9search3

#### 剪枝（Pruning）與加速策略（實用優先）

1) **界限剪枝（Bound Pruning）**：若節點下界 \(LB\) 已不可能優於 incumbent \(UB\)，直接砍掉。這是 B&B 的主力。citeturn8search1turn9search3turn9search11  

2) **可行性傳播（Constraint Propagation）**：當你固定某段型號後，立刻用套接限制縮小相鄰段候選集（例如可套接的 ID/OD 窗口）。這類「邊走邊縮域」就是 MINLP/CP 系統常用的域縮減概念。citeturn8search1turn9search6turn0search2  

3) **強分支/優先分支（Strong or Priority Branching）**：優先對「最容易造成不可行」或「對目標最敏感」的段分支，例如：承受最大彎矩的段（對 \(I\) 敏感）、或直徑配合最緊的接頭位置。citeturn12view0turn5search4  

4) **節點鬆弛的選擇**：  
   - 若你的性能約束能被線性化/預先表格化（例如每型號預算好質量/長度、EI、允許應力等，並把結構分析寫成線性關係），就能把離散階段轉成 MILP，效率與可擴展性通常會明顯提升，而且可以保證全域最優（在 MILP 模型正確下）。結構領域已有用「型錄 + SAND」把離散斷面選擇寫成 MILP 並以 B&B 解到全域最優的案例。citeturn12view0  
   - 若必須保留非線性（例如 \(D^4\) 類剛度或更複雜的接頭模型），則使用 MINLP 放鬆（或空間 B&B）會更貼近物理，但成本較高。citeturn13search5turn9search3turn5search13

#### 複雜度估計（百～千型號 × 多段）

- **天真枚舉**：\(N^K\)（不可行）。  
- **候選集縮減後**：\(M^K\)。例如 \(K=10, M=10\) 仍是 \(10^{10}\)（仍大），但 B&B + 剪枝可把實際展開節點壓到可接受；而若結構是鏈狀且相鄰約束強，候選集會在傳播下快速縮小。citeturn8search1turn9search3turn0search2  
- **每節點成本**取決於你如何算「下界」：  
  - 若下界是快速可分解的（例如各段獨立的最低質量）則節點成本低但界鬆。  
  - 若下界需解一個子 NLP/QP（像 SQP 子問題）則節點成本高但界更緊。SQP 的本質是反覆解二次近似子問題並對約束做一階近似。citeturn0search1turn0search9turn13search5

**實務建議（面對百～千型號）**：優先投資在「候選集生成」與「裝配硬篩選」；把每段候選從 1000 壓到 10～30，往往比換更強的全域 MINLP 求解器更有效。結構型錄/斷面選擇研究也強調：若能把問題改寫為 MILP，B&B 可給全域最優且可用 gap 提前停止（例如 5%～10%）取得工程上很划算的解。citeturn12view0turn9search11turn9search3

---

## 物理套接限制的數學式

本節用「相鄰管 \(i\) 與 \(j\)」表示一個套接/接頭位置。假設 \(i\) 是內插（male）那支、\(j\) 是外套（female）那支；若你的幾何相反，交換符號即可。

### 幾何尺寸與公差定義

- 名目尺寸（型錄值）：外徑 \(D_i\)、內徑 \(d_i\)；外徑 \(D_j\)、內徑 \(d_j\)。  
- 製造公差：\(\tau^{OD}_i,\tau^{ID}_i,\tau^{OD}_j,\tau^{ID}_j\)。  
  最壞情況界：
  \[
  D_i^{-}=D_i-\tau^{OD}_i,\; D_i^{+}=D_i+\tau^{OD}_i,\;
  d_j^{-}=d_j-\tau^{ID}_j,\; d_j^{+}=d_j+\tau^{ID}_j
  \]
ISO 286 的「limits and fits」體系就是用這種上下偏差框架來描述孔/軸配合，工程上可直接借用到圓柱套接問題（把 tube ID 當 hole、tube OD 當 shaft）。citeturn4search4turn4search16turn4search12

### 內徑/外徑匹配與容許公差（直接套接，不含接頭）

令裝配間隙（clearance / bond gap）  
\[
g_{ij}=d_j - D_i
\]

你通常會需要一個 **最小間隙** \(g_{\min}\)（裝得進去、或保留黏著膠層/裝配裕度），以及一個 **最大間隙** \(g_{\max}\)（太鬆會影響同心度、或黏著層過厚導致性能不穩）。

**把公差納入最壞情況**後，可用兩條不等式保證「任何公差落點都能裝」：

\[
d_j^{-} - D_i^{+} \;\ge\; g_{\min}
\]
\[
d_j^{+} - D_i^{-} \;\le\; g_{\max}
\]

若你採用圓柱固持/黏著（retaining）類產品，許多產品資料會明確給「可容許的最大間隙等級」（例如某些圓柱固持膠設計用於接近 0.25 mm 等級的黏著間隙），此時 \(g_{\max}\) 就可直接由規格書轉成約束上限。citeturn4search1turn4search5turn4search17

### 接頭厚度、階差（step）與重疊長度限制（含接頭/套筒）

考慮使用一個「套筒/接頭」（sleeve/coupler），其設計參數可能包含：

- 接頭壁厚 \(t_c\)（若接頭是金屬/複材管件）；或接頭內外徑 \(d_c, D_c\)。  
- 黏著層厚度（或配合間隙）\(g_{i,c}\)、\(g_{c,j}\)。  
- 重疊長度 \(L_{ov}\)（套接插入長度）。  

**幾何配合（示意：內管 \(i\) 插入接頭，接頭插入外管 \(j\)**）：

1) 內管與接頭內徑配合（若接頭套在內管外面）：
\[
d_c^{-} - D_i^{+} \ge g_{i,c}^{\min},\quad
d_c^{+} - D_i^{-} \le g_{i,c}^{\max}
\]

2) 接頭外徑與外管內徑配合：
\[
d_j^{-} - D_c^{+} \ge g_{c,j}^{\min},\quad
d_j^{+} - D_c^{-} \le g_{c,j}^{\max}
\]

3) **階差（step）限制**：避免外形（或內部）直徑突變過大，例如
\[
|D_j - D_i| \le \Delta_{\text{step}}^{\max}
\]
或限制比值 \(D_j/D_i \le r_{\max}\)。  
（此約束多半是設計規範/經驗要求；若你要把它變成線性約束，可以用輔助變數 \(s_{ij}\ge 0\) 轉成 \(D_j-D_i\le s_{ij},\; D_i-D_j\le s_{ij},\; s_{ij}\le \Delta_{\text{step}}^{\max}\)。）

4) **重疊長度（overlap）限制**：黏著/搭接接頭常需要足夠重疊長度以降低剪應力集中與避免蠕變破壞；例如工程手冊/技術報告中常見「重疊長度約為最薄被貼合件厚度的若干倍」之設計建議（用於促進較均勻的剪應力分佈）。citeturn4search10turn4search2  

> 實務提醒：有些實作經驗會因型錄尺寸不一致而用「膠帶/墊片」補尺寸以求緊配合，但這會引入額外不確定性與施工風險；相關人力飛行器開發報告就記錄過用金屬膠帶調整套筒配合而導致施工問題、需要後續改良的案例。這也是為何建議把「可裝配」用數學式硬性保證，而不是靠現場補救。citeturn15view0

### 在優化中表達製造公差與裝配裕度：線性 vs 非線性

- 上述「最壞情況」形式（用 \(D^{+},d^{-}\)）在大多數情況是**線性的**，非常適合放進 MILP / MIQCP / CP-SAT。citeturn4search4turn0search2turn12view0  
- 若你把 \(D_i\) 也當變數，並讓公差 \(\tau\) 隨尺寸變（例如公差帶與尺寸相關），則會導入**非線性**或分段線性（piecewise）關係；可用 SOS2 近似或直接用 MINLP。citeturn5search3turn9search3turn8search1

### 引入二元變數表示是否使用接頭/墊片：混合整數約束範例

定義二元變數：

- \(z_{ij}\in\{0,1\}\)：是否使用接頭（1=用接頭；0=直接套接）。  
- \(u_{ij}\in\{0,1\}\)：是否使用墊片/襯套（shim/liner）。  
- \(s_{ij}\ge 0\)：墊片等效厚度（連續）。

以 Big‑M（或指示約束）寫出「二選一」的析取：

**直接套接（當 \(z_{ij}=0\) 時啟用）**
\[
d_j^{-}-D_i^{+}\ge g_{\min} - M z_{ij}
\]
\[
d_j^{+}-D_i^{-}\le g_{\max} + M z_{ij}
\]

**使用接頭（當 \(z_{ij}=1\) 時啟用）**
\[
d_c^{-}-D_i^{+}\ge g_{i,c}^{\min} - M(1-z_{ij})
\]
\[
d_j^{-}-D_c^{+}\ge g_{c,j}^{\min} - M(1-z_{ij})
\]
其餘上界類似。

若改用「廣義析取（GDP）」建模，會更乾淨；entity["organization","Pyomo","python optimization modeling language"] 提供 GDPopt 等分解器處理析取模型（可視為用邏輯分解來解 GDP/MINLP）。citeturn0search15turn8search5turn8search2

---

## 演算法與開源求解器推薦

### 這類問題的本質：MIP vs MIQCP vs MINLP

當你把「從型錄選一支管」建成二元變數 \(y_{k,m}\in\{0,1\}\) 且 \(\sum_m y_{k,m}=1\)，問題至少是 MIP；若剛度/能量/屈曲用到二次項或雙線性項，會變成 MIQP/MIQCP；若包含一般非線性（例如 \(D^4\)、非線性黏著破壞準則、非線性幾何），就是 MINLP。citeturn12view0turn9search2turn13search5turn8search1

因此「最實用」的策略通常是：

- 能線性化就線性化 → 用 MILP（最穩、最可擴、可給最優性界）citeturn12view0turn9search11  
- 必須保留非線性 → 用 MINLP（開源/商用全球求解器或客製 B&B）citeturn13search5turn8search1turn1search1  
- 若分析是黑盒（外部 FE、試算表、仿真）→ 用啟發式/演化/退火，但要認清「無法保證最優」。citeturn12view0turn6search3turn7search0

---

### 求解器/演算法適用性比較（含表格要求欄位）

> 規模欄位給「粗略工程經驗」：實際取決於約束結構、界限緊密度、以及每次評估成本（是否要跑 FE）。

| 演算法/求解器 | 適用問題規模（粗略） | 預期時間複雜度 | 優點 | 缺點 | 支援非線性約束 | 支援整數/二元 |
|---|---:|---|---|---|---|---|
| 連續 NLP（SLSQP，作為階段一） | 變數數十～數百（取決於段數） | 迭代式；每步解近似子問題 | 實作簡單、能處理一般約束、快速給出連續「好方向」 | 局部解、尺度差大時須調參 | 是（一般非線性） citeturn0search4turn0search0 | 否 |
| 連續 NLP（Ipopt，作為階段一） | 變數數百～上千（常見 NLP） | 迭代式內點法 | 對大型 NLP 較強健、常用於工程 NLP | 需可微/良好尺度化；仍是局部解 | 是 citeturn8search13turn8search3 | 否 |
| 客製兩階段：候選集 + 啟發式取整 | \(N\) 很大、但每段候選 \(M\) 可壓小 | 約 \(O(KN)\) 建候選 + 組合取整 | 工程最常用：快、可融入裝配規則、可平行化 | 無最優保證，品質看啟發式設計 | 視你的可行性檢查而定 | 是（因本來就在選離散） |
| 分支定界（客製 B&B / 與取整整合） | \(K\) 中等（例如 5～20）且 \(M\) 小（10～30） | 最壞指數級 \(O(M^K)\) | 可用界限剪枝、可搭配強傳播與 incumbent | 最壞仍爆炸；界限鬆會很慢 | 可（若節點放鬆是 MINLP/NLP） | 是 |
| CP‑SAT（OR‑Tools） | 大量整數/0‑1、線性或 CP 形式 | NP-hard；但工業級剪枝 | 對整數組合很強；文件強調需用整數建模（可放大尺度） | 不支援一般連續非線性；需離散化/線性化 | 否（一般非線性） citeturn0search2turn0search6 | 是 |
| MILP（結構分析可線性化時） | 可到大型（上萬變數/約束常見） | NP-hard；B&B/branch‑and‑cut | 可保證全域最優（在 MILP 模型正確下）；成熟生態 | 必須把物理寫成線性/分段線性 | 否（但可用分段線性近似） citeturn12view0turn5search3 | 是 |
| BONMIN（MINLP，偏凸） | 中小～中等 MINLP | 分解 / NLP‑BB / OA 等 | 多種 MINLP 演算法（OA、NLP‑BB、feasibility pump…），開源 | 對非凸較弱（可能只給局部或失敗） | 是 citeturn1search0turn0search19turn13search4 | 是 |
| COUENNE（非凸 MINLP 全球） | 小～中等非凸 MINLP | 空間 B&B（最壞指數） | 目標是非凸 MINLP 全球最優；含線性化、bound reduction、啟發式 | 規模大時可能很慢 | 是 citeturn9search3turn13search5turn9search6 | 是 |
| BARON（非凸 MINLP 全球，商用） | 小～中等非凸 MINLP | branch‑and‑bound + range reduction | 針對非凸 NLP/MINLP 全球最優；文件描述以 B&B 並加強域縮減 | 商用授權；大型實例仍可能耗時 | 是 citeturn8search1turn8search0turn8search19 | 是 |
| SCIP（MIP/MINLP 框架） | 中小～中等 MINLP/MIP | 分支切割等（最壞指數） | 同時可做 MIP 與 MINLP；是 CIP 框架，利於客製剪枝/啟發式 | 授權條件需留意；要用得強需理解插件/參數 | 是 citeturn1search1turn1search9turn13search11 | 是 |
| Gurobi（MIP/MIQP/MIQCP） | 大型 MILP/MIQP/MIQCP 常見 | branch‑and‑cut 等 | 對線性/二次類很強；支援凸與部分非凸二次約束（需設定） | 不支援一般非線性（需轉成二次/線性） | 部分（限二次/二次約束） citeturn9search0turn9search16turn13search2 | 是 |
| CPLEX（MIP/MIQP/MIQCP） | 大型 MILP/MIQCP 常見 | MIP 系列（最壞指數） | 支援 QP/QCP/MIQP/MIQCP 等；參數化成熟 | 不支援一般非線性；需改寫 | 部分（限二次/二次約束） citeturn9search2turn9search13turn9search9 | 是 |
| GA（演化算法） | 很大、黑盒評估也可 | 迭代式；無保證 | 容易塞進複雜約束（用懲罰/修復）；適合多目標；Python 套件成熟 | 參數多、收斂慢、無最優保證 | 以黑盒方式「可」但難保可行 | 是 |
| Simulated Annealing | 中等～很大 | 迭代式；無保證 | 結構簡單、適合局部極小陷阱；可作為離散修補器 | 調溫參數敏感、仍無最優保證 | 同上 | 是 citeturn6search3 |
| Tabu Search | 中等～很大 | 迭代式；無保證 | 擅長組合鄰域搜尋、可嵌入約束修復與記憶結構 | 設計鄰域/禁忌表需經驗 | 同上 | 是 citeturn7search0 |

---

### Python 生態系實作建議（套件、介面、並行化、混合策略）

**建模層（選一種主幹）**

- 你想自己掌控兩階段流程：  
  用 NumPy/SciPy 做連續階段；離散階段自寫取整 + B&B；需要 MILP/MIQCP 時再接商用或開源求解器。citeturn0search4turn9search0turn12view0
- 你想快速做 MINLP 原型：  
  用 Pyomo 建模，接 Bonmin/Couenne/Ipopt（或 BARON/SCIP/Gurobi/CPLEX 等）。Pyomo 官方定位就是 Python 的開源建模語言，可連結多種商用與開源求解器。citeturn8search2turn8search5turn1search0turn13search5

**求解層（建議的「混合」配置）**

1) 階段一：SLSQP 或 Ipopt（求得連續目標解）citeturn0search4turn8search13turn8search3  
2) 階段二（優先順序）：
   - 若能把性能/分析改寫成 MILP/MIQCP：用 Gurobi/CPLEX（或開源 MILP solver）做主求解；這路線在「型錄斷面 + 結構分析約束」研究中可保證全域最優，並可用 gap 提早停止。citeturn12view0turn9search16turn9search2  
   - 若必須非凸 MINLP：Couenne（開源）或 BARON（商用）做全球解；或用 SCIP 框架做更客製的界縮減與剪枝。citeturn13search5turn8search1turn1search9  
   - 若是超大且黑盒：用 GA/SA/Tabu 做「可行解搜尋 + 局部改善」，再用你自己的 B&B 或 MILP 做精煉（把候選縮小後再進精確法）。citeturn12view0turn6search0turn6search3turn7search0

**並行化（務實做法）**

- 候選集生成可對每段獨立並行。  
- 啟發式取整可做多起點（不同權重、不同偏置規則）並行產生多個 feasible incumbents。  
- B&B 節點評估可用工作佇列（work stealing）並行，但要小心共享 incumbent（鎖/原子更新），以及避免重複計算（cache）。  
（這些屬一般工程並行技巧；若用 DEAP，其文件也特別提到可與 multiprocessing/SCOOP 等並行機制整合。）citeturn6search0

---

## 實作細節與範例

### 關鍵演算法步驟偽程式碼

以下偽程式碼刻意只放「決策流程骨架」，你可以把結構分析替換成解析式或 FE 呼叫。

```text
Inputs:
  catalog: list of N tube models with properties (D, d, rho, E, cost, tolerances, ...)
  K segments with lengths L_k and load/boundary definitions
  joint rules: clearance bounds, sleeve options, step limits, overlap rules, ...
  objective weights: w_m, w_c, w_s (may be None if unspecified)

Stage 1: Continuous Relaxation (NLP)
  define continuous vars x = {D_k, d_k, ...}
  define objective J_cont(x)
  define constraints g_cont(x) <= 0, h_cont(x) = 0
  x_star = solve_NLP(x0, J_cont, g_cont, h_cont)  # SLSQP or Ipopt
  targets p_k* = extract_targets(x_star)

Stage 2A: Candidate Generation
  for each segment k:
    C_k = filter_catalog_by_hard_bounds(catalog, segment k)
    C_k = filter_by_joint_feasibility_window(C_k, neighbors, tolerances, ...)
    C_k = select_top_M_by_weighted_distance(C_k, p_k*)
  # Now each C_k has size M_k (typically 5~30)

Stage 2B: Heuristic Rounding (Feasible Incumbent)
  best_feasible = None
  for trial in 1..T:
    order = choose_branch_order(strategy="most constrained first")
    sol = greedy_or_DP_select(C_1..C_K, order, joint_constraints)
    sol = local_repair_and_swap(sol)
    if feasible(sol) and (best_feasible is None or J(sol) < J(best_feasible)):
        best_feasible = sol
  UB = J(best_feasible)

Stage 2C: Branch-and-Bound on Candidates
  Node = (fixed assignments for subset of segments)
  priority_queue.push(root node)
  while queue not empty and not stop_condition(gap, time, nodes):
    node = pop_best_LB_node()
    LB = compute_lower_bound(node)  # relaxation / decomposed bound / MILP relaxation
    if LB >= UB: continue  # prune
    if node is complete:
        if feasible(node.sol) and J(node.sol) < UB:
            best_feasible = node.sol
            UB = J(best_feasible)
        continue
    branch_var = choose_next_segment(node, strategy="strong/most constrained")
    for each candidate in C_branch_var:
        child = node + fix(branch_var = candidate)
        if quick_infeasible_check(child): continue
        queue.push(child)
  return best_feasible
```

---

### 小型示例：型錄 20 種、3 段管（流程示範與結果解讀）

**設定（示意）**

- 段數 \(K=3\)，長度：\(L_1=0.6\) m、\(L_2=0.8\) m、\(L_3=0.5\) m。  
- 目標（示意）：最小重量 \(\sum \rho A L\)，並滿足一個端載撓度上限（用樑公式快速估算）與相鄰套接間隙限制。撓度公式採懸臂端載 \(\delta=F L^3/(3EI)\) 作示例。citeturn10search0turn10search8turn11search3  
- 型錄：20 種碳管，每種給 \((D_m,d_m,\rho_m,E_m)\) 與公差 \(\tau\)（此處不列滿 20 行，只示意其中 6 行的格式）。

| 型號 m | OD \(D_m\) (mm) | ID \(d_m\) (mm) | \(\rho_m\) (kg/m³) | \(E_m\) (GPa) |
|---:|---:|---:|---:|---:|
| 1 | 18 | 16 | 1550 | 70 |
| 2 | 20 | 18 | 1550 | 70 |
| 3 | 22 | 20 | 1550 | 70 |
| … | … | … | … | … |
| 20 | 40 | 36 | 1550 | 70 |

> \(\rho, E\) 在真實情境應以供應商/型錄資料為準；市售產品頁常列出碳纖維模數、管規格與重量等資訊，可用於建立這張表。citeturn2search5turn10search3turn2search1

**步驟一：連續階段（得到目標幾何）**

解連續 NLP 得到（示意）：
\[
(D_1^\*,d_1^\*)=(21.2,19.4)\text{mm},\quad
(D_2^\*,d_2^\*)=(24.0,22.0)\text{mm},\quad
(D_3^\*,d_3^\*)=(19.6,17.8)\text{mm}
\]

**解讀**：第 2 段因為長度較大（撓度對 \(L^3\) 敏感），連續解自然傾向把第 2 段做得更粗以提高 \(I\)（因 \(I\) 隨 \(D^4\) 成長）。citeturn10search0turn11search3

**步驟二：候選集生成（Top‑M）**

例如取 \(M=5\)：

- 第 1 段候選 \(C_1=\{2,3,4,5,6\}\)  
- 第 2 段候選 \(C_2=\{4,5,6,7,8\}\)  
- 第 3 段候選 \(C_3=\{1,2,3,4,5\}\)

並用硬性套接窗口（含公差最壞情況）先剔除明顯不可能配合者：
\[
d_j^{-}-D_i^{+}\ge g_{\min},\quad d_j^{+}-D_i^{-}\le g_{\max}
\]
（若使用黏著固持膠，可把 \(g_{\max}\) 設成產品允許的間隙等級。）citeturn4search1turn4search5turn4search4

**步驟三：啟發式取整（先求可行解）**

一個簡單的鏈狀修復策略：

1. 先選第 2 段（最長、最敏感）在 \(C_2\) 中挑重量最低且滿足撓度的型號。  
2. 再向兩側選第 1、3 段，選擇能與第 2 段滿足套接與 step 限制者中最輕的。  
3. 若失敗（套不進去或太鬆），回退改選下一個候選（有限次回溯）。

得到第一個可行離散解（示意）：
\[
(m_1,m_2,m_3)=(3,6,2)
\]
並計算其重量與撓度，作為 incumbent 上界 \(UB\)。

**步驟四：分支定界精煉（候選空間）**

以 \(C_k\) 的 \(5^3=125\) 種組合為例，已小到可以用 B&B 很快掃完；若是實務規模（例如 \(K=12, M=20\)），B&B 的剪枝就變得關鍵。

B&B 在此例可能很快找到更佳解（示意）：
\[
(m_1,m_2,m_3)=(2,6,2)
\]
並給出「最佳已知界」：若下界 \(LB\) 與上界 \(UB\) 收斂至 gap < 1%，即可宣告收斂。

**結果解讀（你應該看的不是型號，而是三件事）**

1) 是否滿足最壞情況公差下的套接（可裝配）。  
2) 是否滿足載重下的撓度/應力/屈曲（可用）。citeturn10search0turn10search1  
3) 若你做多目標：這個解在 Pareto 前緣的哪個位置（重量換剛度/成本多少）。citeturn6search1turn6search13

---

## 視覺化與圖表

### 建議的效能/複雜度比較圖（文字版）

你在做方案評估或向團隊報告時，最有用的兩張圖通常是：

1) **候選數 \(M\) vs 計算時間/節點量**（折線圖）  
   - x 軸：每段候選數 \(M\)（例如 5、10、20、30）  
   - y 軸：總時間、展開節點數、或平均每節點評估時間  
   - 作用：讓大家看到「投資候選縮減」的回報，通常 \(M\) 從 30 降到 10，節點數會呈指數級下降（但品質可能下降，需權衡）。

2) **不同策略的剪枝效果（柱狀圖）**  
   - 比較：只用界限剪枝 vs 加上可行性傳播 vs 加上強分支  
   - 指標：節點數、可行解找到時間、最終 gap  
   - 作用：說服團隊「為什麼要花時間寫傳播/修復器」。

這些圖的數據可直接從你的 B&B 日誌輸出：每秒節點數、LB/UB 軌跡、候選集縮減率。全球求解器（如 BARON / Couenne / Gurobi MIP）也都內建類似的搜尋日誌概念（上界/下界/節點）。citeturn8search1turn9search3turn9search11

---

## 實務建議與下一步行動清單

### 最重要的工程結論（務實版）

1) **先把「可裝配」變成硬約束**：套接可行性（含公差最壞情況）應該在候選生成時就大幅篩掉；否則離散階段會浪費大量時間在不可行組合上。ISO limits & fits 的上下偏差框架很適合作為建模語言。citeturn4search4turn4search12turn15view0  

2) **把型錄離散化後，盡量把物理改寫成 MILP/MIQCP**：只要你能把分析/限制寫成線性或二次形式，MIP 求解器的可擴展性通常遠勝一般非凸 MINLP；而且可以給最優性界。結構領域已有把「型錄斷面選擇 + 結構分析方程」寫成 MILP 並用 B&B 保證全域最優的範例。citeturn12view0turn9search16turn9search2  

3) **兩階段法的價值在「縮小搜索空間」**：連續解不是最終答案，但它提供非常有效的候選排序與界限；做得好的候選縮減，往往比換 solver 更能縮短總時間。citeturn12view0turn0search4turn8search1  

### 資料需求清單（你需要準備什麼才能落地）

- 型錄資料（CSV/JSON）：每型號至少要有 \(D, d\)（或壁厚）、重量/長度或密度、價格、可供長度、以及公差（若型錄不給，至少要有你量測/供應商保證的公差帶）。citeturn2search5turn2search1  
- 接頭/黏著與裝配規範：可接受的 \(g_{\min}, g_{\max}\)、接頭幾何（若有）、重疊長度下限等；若使用黏著固持膠，需其可容許間隙與適用條件作為約束上限來源。citeturn4search1turn4search5turn4search10  
- 載重/邊界條件與驗證模型：至少先有簡化樑/桿公式能估撓度/屈曲；之後再用 FE 或試驗校正。citeturn10search0turn10search1  

### 測試案例與驗證步驟（建議按此順序）

- **單接頭可行性測試（最先做）**：隨機抽 20 組相鄰型號，檢查最壞情況公差下 \(d_j^{-}-D_i^{+}\) 是否仍 ≥ \(g_{\min}\)。  
- **小規模端到端測試**：\(N=20, K=3\)（如本報告示例），確保流程能輸出「可裝配」且性能滿足的解。  
- **中規模壓力測試**：例如 \(N=500, K=10\)，觀察候選縮減後的 \(M_k\) 分佈、B&B 節點量與時間，並用不同剪枝組合做 A/B。  
- **物理驗證**：對最終解做（1）實體套接試裝，（2）關鍵載荷下撓度/應力量測，（3）接頭破壞/疲勞試驗（若接頭是主要風險）。黏著接頭設計與失效分析在複材結構中是獨立的工程主題，建議至少做一輪小試件試驗校正模型。citeturn4search2turn4search10turn15view0