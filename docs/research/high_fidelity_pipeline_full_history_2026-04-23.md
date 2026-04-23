# 高保真路線完整發展史 (2026-04-23)

## 這份文件的目的

這份整理不是只講 `shell_v1 ~ shell_v4`。

它要回答的是更大的問題：

> `hpa-mdo` 這條高保真路線，從一開始到底是怎麼長出來的？
> 每一段在解什麼工程問題？
> 哪些 commit 只是前置基建，哪些 commit 才是 main-wing / shell 主線真正的轉折點？

所以這份文件會把整條線拆成 6 個階段：

1. `M-HF` 結構高保真驗證層
2. `origin SU2` 高品質自動網格路線
3. `ESP/OpenCSM feasibility -> hpa_meshing_package` 產品化
4. `esp_rebuilt` 外流幾何 / coarse smoke / forensics 主線
5. `shell_v1 -> shell_v3`
6. `shell_v4` boundary-layer / solver-validation 主線

如果只看 `shell_v1 ~ v4`，
會錯過一個很重要的事：

- 這條線不是突然從 `terminal strip suppression` 開始
- 它前面其實先經過了
  `高保真結構驗證 -> origin SU2 meshing -> ESP feasibility -> package 化 -> esp_rebuilt coarse smoke`
  這幾層前史

## 一句話總結整條線

這條高保真主線，不是在同一個問題上反覆修 patch。

它其實是在一路換問題層級：

1. 先把高保真驗證層的 `STEP -> Gmsh -> CalculiX` 骨架建起來
2. 再試一條 `origin -> SU2` 的高品質自動外流路線
3. 發現真正需要一條可產品化、可診斷、可比較的 meshing package
4. 於是長出 `hpa_meshing_package`
5. 再把 `esp_rebuilt main_wing` 推進到能做 3D coarse smoke
6. 然後才進入 `shell_v1 -> v4` 這條真正的 real-wing / shell / BL 主線

所以從工程角度看：

- 前半段在解「高保真工具鏈能不能站起來」
- 中段在解「外流幾何和 coarse mesh 能不能穩定 materialize」
- 後半段才在解「真實主翼 / shell / near-wall / BL / solver-entry contract」

## 整條線的相位圖

| 階段 | 時間 | 核心問題 | 代表成果 |
| --- | --- | --- | --- |
| A | 2026-04-15 ~ 2026-04-18 | 高保真結構驗證層能不能形成可跑的工具鏈 | `M-HF` 驗證 stack、structural check、mesh diagnostics |
| B | 2026-04-20 | 能不能先做一條 `origin -> SU2` 自動高品質外流路線 | `origin SU2` auto meshing / step-backed route |
| C | 2026-04-20 ~ 2026-04-21 | 能不能把這些能力整理成 package / contract / gate | `hpa_meshing_package` 主線本體、mesh study、convergence gate |
| D | 2026-04-21 ~ 2026-04-22 | `esp_rebuilt` 可不可以走到穩定的 coarse smoke 與 3D forensics | `esp_pipeline`、`native OpenCSM`、3D watchdog、hotspot forensics |
| E | 2026-04-22 | `shell_v1 -> shell_v3` 怎麼把 tip-end 問題從 downstream patch 推回 upstream seam truth | `shell_v2_strip_suppression`、`shell_v3_quality_clean_baseline` |
| F | 2026-04-23 | `shell_v4` 怎麼正式切成 BL / solver-validation 路線 | `shell_v4_half_wing_bl_mesh_macsafe` 與後續 family-level fixes |

---

## A. `M-HF` 結構高保真驗證層

這一段還不是 `shell_v1 ~ v4`，
但它是整條高保真路線的技術前史。

如果沒有這一段，
後面就不會那麼快出現：

- named sets
- diagnostics sidecar
- structural check
- result extraction
- geometry-aligned load/support evidence

### A1. 基礎 runner 與驗證層骨架

- `19c8108` `docs+blueprint: 高保真驗證層介面與管線更新`
  這顆主要是藍圖與 interface framing。
  它不是主功能 commit，但它把高保真驗證層當成獨立能力來定義，後面 `M-HF` 相關 commit 幾乎都沿著這個 framing 在長。

- `3737360` `feat(hifi): 新增 Gmsh STEP 網格 runner`
  第一顆真正把高保真 meshing 能力落地的 commit。
  新增 `scripts/hifi_mesh_step.py`、`src/hpa_mdo/hifi/gmsh_runner.py` 與對應測試，代表：
  `STEP -> Gmsh` 不再只是手動流程，而是 repo 內有正式 runner。

- `1c69530` `feat(hifi): 新增 CalculiX 靜力驗證 runner`
  新增 `calculix_runner.py`、`frd_parser.py`、`hifi_validate_tip_deflection.py`。
  這顆把高保真路線從「只有 mesh」推進到「能做靜力驗證」。

- `20f66fe` `feat(hifi): 新增 CalculiX 挫曲驗證報告`
  在已有 CalculiX runner 上補 buckling report。
  這表示當時的高保真線已經不是只求有位移結果，而是開始把 buckling 納入正式檢查。

- `725bb4c` `feat(hifi): M-HF5 Gmsh mesh .inp 加命名 NSET（ROOT / TIP / WIRE_N）`
  這顆很關鍵，因為它把 mesh 與後續求解/後處理的 semantic interface 補齊了。
  沒有 named NSET，後面的 root / tip / wire evidence 很難穩定對齊。

- `4c33136` `M-HF4: add ParaView pvpython script generator for CalculiX hi-fi results`
  補了 ParaView 視覺化腳本產生器。
  工程意義是：
  高保真路線不只是算出數字，還開始要求結果可視化、可檢查、可交付。

### A2. structural check 正式化

- `c350691` `feat: 新增 hifi structural check 結構驗證入口`
  把 structural check 提升成正式 entrypoint。

- `b35104d` `feat: 補上 hifi structural check runner 與測試`
  補 `scripts/hifi_structural_check.py`、`structural_check.py`、完整 tests。
  從這裡開始，高保真結構驗證不再只是 runner 集合，而是有一個統一的 check workflow。

- `acb1b87` `feat: 補強高保真 structural check 載荷與單位尺度`
  補 load / unit scale。
  這顆的工程意義很大，因為高保真流程如果單位尺度不穩，後面再多 diagnostics 都不可信。

- `aab250b` `feat: 讓高保真驗證可跑 partial shell mesh`
  這是把高保真結構驗證從「只適合完整模型」推向更能做局部檢查的形式。

- `c8073de` `fix: 補強高保真結果擷取與 buckling parser`
  補強結果擷取與 parser，讓整條高保真結構路線更像產品而不是 demo。

- `50cf8a2` `fix: 將高保真預設切到 dual-beam 現行標準`
  這代表高保真驗證層開始明確對齊團隊當時認定的現行工程標準，而不是只保留研究式 runner。

### A3. 結果對齊與 diagnostics 強化

- `4b588ff` `feat: 強化 Mac hifi structural spot-check 診斷輸出`
  把本機驗證/spot-check 診斷做得更完整。

- `d73aa4b` `fix: 修正 hifi root boundary fallback 容差`
  修 root boundary fallback tolerance。

- `832d7e8` `fix: 補強 hifi named point spanwise 匹配`
  修 named point spanwise matching。

- `513b1f1` `fix: 去除 hifi analysis 重複 shell facets`
  去掉重複 shell facets，這是標準的幾何清潔度問題。

- `ef210e5` `feat: 補上 hifi mesh diagnostics sidecar 與報告`
  很重要的一顆，因為它讓 high-fidelity 不再只靠 solver log，而是有獨立 diagnostics sidecar。

- `32dc373` `feat: 補上 hifi mesh 維度診斷輸出`
  補 mesh dimension diagnostics，讓「這到底是 2D、shell、還是 volume 問題」更容易被分辨。

- `8cac121` `fix: 補上 hifi shell 法向與 sliver 過濾`
  顯示當時已經在碰 shell normal / sliver 這類幾何品質問題。

### A4. 幾何座標與支承/載荷對齊

- `03c1bd5` `fix: 對齊 hifi spar load replay 到 main rear 幾何座標`
- `984ca73` `fix: 對齊 hifi summary 與 spar load evidence root`
- `3a02f71` `fix: 對齊 hifi wire support 到 main spar 幾何座標`
- `3534172` `fix: 補上 hifi wire support 小範圍 cluster 對齊`
- `507c4a9` `feat: 補上 hifi support reaction compare 輸出`
- `430e5e2` `fix: align hifi deck thickness with discrete layup`

這一串 commit 的共同意義是：

- 高保真驗證不再只是「跑出一個 FE 結果」
- 而是開始要求 load path、support path、deck thickness、summary evidence 全部幾何對齊

### A 階段的工程意義

這一段完成的是：

- 高保真結構驗證 stack 能跑
- mesh / result / diagnostics / supports / loads 都有正式 interface

但它還不是後面的 `main_wing shell` 外流主線。

工程上可以把它看成：

- 先把 high-fidelity verification 的工具層建好
- 還沒真正進到 `esp_rebuilt main_wing` 3D 外流主問題

---

## B. `origin SU2` 高品質自動外流路線

這一段是高保真外流線的另一條前史。

它和 `M-HF` 不同，
重點不是 CalculiX 結構驗證，
而是：

> 能不能先走一條比較直接的 `origin -> Gmsh -> SU2` 自動高品質路線？

### B1. origin 自動 meshing / SU2 runner

- `567bcd2` `feat: add origin su2 auto meshing`
  新增 `origin_gmsh_mesh.py`、`origin_su2.py` 與測試。
  這顆把 `origin -> SU2` 的自動外流路徑正式放進 repo。

- `6274328` `feat: prefer step-backed origin su2 meshing`
  把 origin meshing 往 STEP-backed 路線推。
  工程上代表團隊已經不滿足於較脆弱的直接路線，而是開始要求較可控的 STEP-backed geometry handoff。

- `39fc539` `fix: harden origin step meshing fallback contract`
  補強 fallback contract。
  這一顆的價值不是做新功能，而是讓 origin 路線開始有明確的 failover 邊界。

### B 階段的工程意義

`origin SU2` 線的價值是：

- 證明 repo 需要一條正式的自動外流高品質路線
- 也暴露出 ad hoc script 形式不夠，後面才會自然長成 `hpa_meshing_package`

所以從高角度看：

- `origin SU2` 不是失敗品
- 它其實是後面 package 化與 contract 化的直接前身

---

## C. `ESP/OpenCSM feasibility -> hpa_meshing_package` 產品化

這一段是整條外流高保真主線真正開始「像產品」的地方。

### C1. feasibility 與 package 主線建立

- `d7dcde6` `docs: add ESP/OpenCSM feasibility spike report`
  這雖然是 docs commit，但它很重要。
  它把 `ESP/OpenCSM` 當成正式選項來審查，不再只是隨手試。

- `5f7091d` `feat: 整合 hpa_meshing_package 主線本體`
  這顆是 package 化的真正起點。
  一次加入：
  `gmsh_backend.py`、`su2_backend.py`、`cli.py`、`dispatch.py`、`pipeline.py`、`schema.py`、providers、tests。
  工程上可以把它視為：
  「高保真外流主線從腳本集合變成 package」。

- `ae9f95e` `docs: productize hpa_meshing_package front door`
  把 package front door、contracts、current status 整理出來。
  雖然是 docs，但對主線非常重要，因為它把 package 的使用入口與 contracts 穩定下來。

- `b2bca95` `fix: restore hpa_meshing report writers`
  把 json / markdown report writer 補回來。
  這顆代表 package 已經不只是「算」，還要正式輸出 artifact。

### C2. gates 與 study contract

- `31a74b7` `feat: add baseline convergence gate contract`
  建立 convergence gate。

- `978912e` `feat: 新增 hpa_meshing_package mesh study gate`
  建立 mesh study gate。

- `3fbd51c` `docs: 補上 hpa_meshing_package mesh study 合約說明`
  補上 mesh study contract docs。

- `c96190e` `fix: 修正 baseline convergence trend 與 mesh study runtime preset`
- `73a2a47` `fix: 收斂 baseline mesh study 預設 preset`
- `66845e3` `test: 補強 baseline mesh study preset regression`
- `5fc11a2` `fix: harden mesh study gate for low-CM cases`
- `0a76db7` `fix: keep super-fine as diagnostic mesh-study tier`

這一串 commit 在做的事很一致：

- 讓 study / gate / preset 不是研究式亂試
- 而是有穩定 contract、有預設、有 regression

### C3. mesh policy stabilization

- `31d03da` `docs: add mesh policy stabilization research note`
- `1474da7` `fix: stabilize field-driven thin-sheet mesh policy`
- `ddafe83` `fix: 導正 hpa_meshing_package 高保真網格尺寸主線`
- `83e187e` `fix: 讓 Gmsh edge sizing 隨 preset 一起縮放`

這一段回答的是：

> package 有了，那網格尺寸主線到底要怎麼穩？

工程意義是：

- 從這裡開始，meshing policy 被當成正式主線，而不是每次 case-by-case 手動改

### C4. ESP 接線前置準備

- `d91bc27` `docs: 對齊 esp provider 現況與 enablement 計畫`
- `cb67140` `docs: 補上 esp handoff 與禁止 worktree 說明`
- `94bcad5` `test: 鎖定 esp runtime discovery 與 fail-loud 診斷`

這一段的價值在於：

- 還沒真正 materialize `esp_rebuilt`
- 但已經先把 runtime discovery、handoff、enablement 說清楚

### C 階段的工程意義

這一段完成的是：

- 高保真外流能力從腳本化變成 package 化
- contract / schema / gate / report / study 全部被正式化

沒有這一段，
後面的 `esp_rebuilt`、`shell_v1 ~ v4` 根本不可能有那麼完整的 artifact 與 regression discipline。

---

## D. `esp_rebuilt` 外流幾何 / coarse smoke / 3D forensics 主線

這一段是 `shell` 之前最關鍵的前史。

因為從這裡開始，
高保真主線正式面對：

- `ESP/OpenCSM` geometry materialization
- coarse smoke
- 2D / 3D diagnostics
- hotspot / sliver / no-volume / HXT / burden metrics

### D1. ESP runtime 與 materialization 打通

- `cf888df` `fix: 放寬 esp batch runtime gate`
- `11e8e7c` `test: 隔離 esp CLI 測試的本機 runtime 依賴`
- `0208067` `fix: 打通 esp_rebuilt materialize 路徑`
- `649df32` `fix: 匯出 ESP assembly 全部 body`
- `4e734e3` `fix: 修正 esp step 單位正規化`
- `6568777` `fix: 補完 esp step 單位正規化與拓樸探測`

這些 commit 的共同意義是：

- 先把 ESP runtime / export / step normalization / topology probing 這一整條基本路打通

### D2. `esp_pipeline.py` 與 CFD-ready external geometry

- `ec0fd64` `feat: 將 esp_rebuilt 正規化為 CFD-ready external geometry`
  這是一顆大 commit。
  它讓 `esp_rebuilt` 不只是能匯出，而是能被正式正規化成 CFD-ready external geometry。

- `c0a9207` `test: 補強 esp_rebuilt CFD normalization 測試`
  把這個 contract 用測試鎖住。

- `de89b9d` `feat: 新增 esp_rebuilt component 拆分與 STEP 單位縮放修正`
  把 component split 與 STEP scaling 修正補上。

- `d457878` `feat: 補強 esp provider wing section diagnostic artifact`
  這顆後來對 `shell_v1/v2/v3` 很重要，因為 section-level artifact 是後面 tip family 診斷的基礎。

- `1bf7600` `feat: 改寫 esp_rebuilt 為 native OpenCSM provider`
  這是 `esp_rebuilt` 線的一個超級大轉折。
  從這裡開始，provider 不再只是包一層外部輸入，而是用 native OpenCSM provider 重建。

### D3. coarse smoke 往前推

- `38d98d6` `fix: 讓 clean esp_rebuilt geometry 的 coarse smoke 往後推進`
- `808d977` `fix: 補強 esp_rebuilt 外流 meshing 診斷與 lifting-surface route`
- `1adbc8a` `feat: 新增 esp_rebuilt HXT coarse smoke 設定`

這些 commit 表示：

- `esp_rebuilt` 不再只是 geometry normalization
- 它已經正式進入 coarse smoke / HXT / lifting-surface route 的可跑性階段

### D4. Gmsh repair / diagnostics / watchdog 主線

- `18476c2` `feat: 新增 gmsh discrete surface repair fallback`
- `0c2ccce` `fix: 補強 gmsh overlap surface pair 診斷`
- `a7a175c` `fix: 補強 gmsh classify angle probe 診斷`
- `dad49df` `fix: 補強 gmsh surface repair no-volume guard`
- `837f36e` `fix: 精簡 gmsh no-volume 失敗診斷流程`
- `dad9753` `feat: add gmsh mesh2d watchdog diagnostics`
- `bdcb02d` `fix: 補強 Mesh2D watchdog diagnostics`
- `82be71f` `fix: harden esp_rebuilt gmsh meshing policy`
- `7ae1a58` `fix: 補強 assembly 2D import scale fallback`
- `627059d` `fix: 明確標記 surface-only probe 並補 3D watchdog artifact`
- `78646f7` `feat(gmsh_backend): add coarse-first-tetra surface-budget policy for esp_rebuilt`
- `9cee47e` `fix: 補強 gmsh 3D burden watchdog 診斷`
- `b5901f7` `fix: 補強 gmsh HXT 3D watchdog phase 診斷`
- `018abd9` `fix: 拆分 gmsh volume smoke decoupled field`
- `f39a34e` `fix: 補上成功 3D mesh 的 burden metrics`
- `1998fee` `test: 補強 gmsh 3D 成功回傳 burden metrics 測試`
- `efb52f7` `fix: 補上 3D tetra quality metrics 與 worst tets 定位`
- `27e5b72` `fix: 補上 3D optimize probe metadata 與 post-optimize hooks`

這一串 commit 很容易被看成很亂，
但工程上其實很一致：

- 目標不是再發明幾何
- 而是把 2D/3D meshing failure 拆解成可定位、可比較、可重現的 artifact

這一段的真正成果不是「馬上成功」，
而是：

- 你終於知道失敗是 `surface-only`、`no-volume`、`optimization`、`burden too high`、還是 `tet quality`

### D5. hotspot forensics 與 meshing-only 局部修補嘗試

- `55b694e` `fix: 補上 31/32 hotspot patch forensics artifact`
- `abfffdc` `fix: 補上 31/32 small-family compound meshing probe`
- `4f8ba98` `fix: 補上 31/32 local BRep hotspot audit`
- `c9198e1` `feat: 新增 tip quality buffer policy 與 winner selector`
- `754ed60` `fix: 讓 tip quality buffer 可下探 MeshSizeMin`
- `d5b5b2c` `feat: add sliver cluster diagnostics and volume pocket policy`
- `c80d8a7` `fix: center sliver cylinder pockets on cluster midpoint`

這一段非常重要，
因為它是 `shell_v3-A` 的前導。

它在回答：

> 如果先不改 upstream truth，只靠 meshing / local pockets / local buffers，能不能把剩下的壞族群吃掉？

後來答案是：

- 能幫忙縮小問題
- 但不能完成主線收斂

### D 階段的工程意義

這一段真正完成的不是 final mesh，
而是：

- `esp_rebuilt` 被正式納入可 materialize、可 smoke、可 forensics 的主線
- meshing failure 從黑盒變成可分類問題

也正因為有這一段，
`shell_v1 -> v4` 才不是盲修。

---

## E. `shell_v1 -> shell_v3`

這一段就是你前面一直追的主線。

更細的敘事我已經另外寫在：
[shell_v1_to_v4_pipeline_overview_2026-04-23.md](</Volumes/Samsung SSD/hpa-mdo/docs/research/shell_v1_to_v4_pipeline_overview_2026-04-23.md>)

這裡只把它放回完整高保真歷史裡看。

### E1. `shell_v1`

嚴格來說，
repo 裡沒有一顆 commit 名字直接叫 `shell_v1`。

`shell_v1` 比較像是 artifact / baseline 名稱：

- 它代表第一代 downstream `terminal strip suppression` 3D smoke 路線
- 工程上對應到 `C1 topology lineage + strip classifier` 開始能辨識 tip terminal strip family 的時期

最接近 `shell_v1` 起點的 code commit 是：

- `273612a` `fix: 補上 C1 topology lineage report 與 strip classifier`

這顆做的事是：

- 加 `topology_lineage_report.json`
- 把 rule section 跟 source section lineage 串起來
- 對 terminal strip candidate 做明確 classifier

它的意義不是直接修好 mesh，
而是把 `shell_v1` 的核心病灶第一次講清楚。

### E2. `shell_v2`

- `773406a` `fix: 抑制 C1 terminal tip strip family`

這顆就是 `shell_v2_strip_suppression` 的核心。

它把前一顆的 diagnosis 變成真正的 suppression rule：

- 加入 `topology_suppression_report.json`
- 實作 `_apply_terminal_strip_suppression()`
- 對 terminal tip strip 做座標 trim / bridge 重建

工程判讀：

- `v1` 是能定位問題
- `v2` 是能暫時壓住問題，形成可比較的 control baseline

### E3. `shell_v3` 前半：證明 meshing-only 不夠

- `3f6e656` `feat: add autonomous source-section tip topology repair controller`

這顆很大，
它把 bounded autonomous repair controller、schema、summary/no-go artifact 全部補進來。

工程意義是：

- 不再只是手動 patch
- 而是正式做「bounded candidate sweep」來回答
  `meshing-only / local repair 到底夠不夠`

結論後來很清楚：

- 不夠

### E4. `shell_v3` 核心轉折：upstream seam truth

- `6490c36` `fix: 補上 ESP tip TE seam coalesce 並同步更新收尾測試`

這顆是 `shell_v3` 最重要的轉折點。

它把問題從 downstream suppression 推回 upstream seam truth：

- `_coalesce_trailing_edge_seam()` 成為新的關鍵
- downstream `shell_v2` suppression 不再需要當 active fix
- 它變成 honest no-op

這在工程上很重要，
因為它等於是在說：

- 主問題不是「要 suppress 幾張面」
- 而是「原始 seam topology 有沒有先長對」

### E5. `shell_v3` 收束：frozen baseline 與 coarse CFD

- `bc8e15b` `feat: 凍結 shell_v3 quality baseline regression gate`
- `b739897` `feat: 建立 shell_v3 baseline SU2 coarse CFD route`
- `087ca80` `feat: 建立 shell_v3 near-wall meshing study route`
- `c60865c` `Revert "feat: 建立 shell_v3 near-wall meshing study route"`
- `dfca1d5` `feat: 建立 shell_v3 coarse CFD mesh refinement study`
- `90d86cf` `fix: 預設 SU2 與 Gmsh 使用 4 CPU threads`
- `a66aacd` `feat: 支援 SU2 threads mpi 可選啟動模式`

這一串 commit 的整體意義是：

- geometry baseline 凍結
- coarse CFD route 建立
- near-wall study 試過但不應冒充主線
- solver runtime contract 開始穩定

工程判讀：

- `shell_v3` 的真正完成態是 `frozen geometry baseline`
- 不是「已經有完整 boundary-layer route」

---

## F. `shell_v4` boundary-layer / solver-validation 主線

這一段是目前 active mainline。

### F1. 新 route 建立

- `dc58b22` `feat: 新增 shell_v4 half-wing BL Mac-safe meshing route`

這顆就是 `shell_v4` 的 birth commit。

它的工程意義非常明確：

- 承認 `shell_v3` 那條 tetra shell 線不應硬扮成 BL route
- 正式新開 `half-wing + explicit BL + Mac-safe` 路線

### F2. baseline 與 solver contract

- `9c51ca3` `feat: 調整 shell_v4 baseline off-wall volumetric refinement`
- `12b49ce` `fix: 改用 MPI 啟動 shell_v4 Mac-safe 求解`
- `0eb2f31` `fix: 補齊 shell_v4 wall diagnostics 輸出契約`

這三顆把 `shell_v4` 從只有 mesh 推進到：

- prelaunch 可重複
- solver launch contract 清楚
- wall diagnostics 至少有正式輸出契約

### F3. real-wing 幾何導入

- `30e767d` `feat: 讓 shell_v4 支援真實主翼 section 幾何`
- `0bb9b56` `fix: 改用 BL 生成面關閉真實主翼 root closure`
- `8ba9ba0` `fix: 加入真實主翼幾何感知 BL 保護`
- `de5a36e` `fix: 補強 real-wing tip-near BL 截斷保護與診斷`
- `813892c` `fix: 補強 truncation seam connector band 局部保護`

這一段的共同主題是：

- 一旦 `shell_v4` 從 baseline/surrogate 走到 real-wing
- 就開始出現只在 BL route 會看到的新 topology family

### F4. class-level closure 修正

- `aac4c9b` `fix: 改寫 shell_v4 closure ring family rebuild contract`

這顆把
`353 / 383 / 410 / 427 / 471`
從單面 patch 提升成 class-level family rebuild。

這是 `shell_v4` 非常重要的里程碑，
因為它代表主線已經脫離 one-face-at-a-time patch。

### F5. triangular end-cap fallback

- `4e92fa2` `fix: 補強 shell_v4 triangular end-cap closure fallback`

這顆則是針對新的 family：

- `degenerated prism`
- `Could not recover boundary mesh: error 2`

做一次受限的 class-level fix。

工程判讀是：

- 這已經不是舊的 closure-ring ordering 問題
- 而是 collapsed-edge / triangular-end-cap / volume-side contract 問題

### F 階段的工程意義

`shell_v4` 這條線真正完成的是：

- 真正的 BL / solver-validation route 已經存在
- 第一個 real SST run 已經可啟動
- 問題層級已經從 geometry baseline 進到 BL topology / solver-entry contract

但它目前還不是 production-ready route。

---

## 這條高保真路線真正的發展脈絡

如果從更高角度看，
整條線其實是這樣往前走的：

### 第一段：工具鏈成形

`M-HF`

- Gmsh STEP runner
- CalculiX runner
- buckling / structural check
- diagnostics / named sets / ParaView

這一段回答：
高保真驗證工具層能不能站起來？

### 第二段：外流自動化早期試線

`origin SU2`

- 自動外流網格
- STEP-backed meshing
- fallback contract

這一段回答：
能不能先有一條高品質外流自動線？

### 第三段：package 化與 contract 化

`hpa_meshing_package`

- pipeline
- adapters
- schema
- report writers
- convergence gate
- mesh study gate

這一段回答：
能不能把高保真外流主線做成正式 package？

### 第四段：`esp_rebuilt` 與 coarse smoke / forensics

- materialization
- CFD-ready external geometry
- native OpenCSM provider
- 2D/3D watchdog
- hotspot/sliver forensics

這一段回答：
真正的 `esp_rebuilt main_wing` 幾何能不能被穩定 meshing 與分析？

### 第五段：`shell_v1 -> shell_v3`

- downstream strip suppression
- bounded repair controller
- upstream seam coalesce
- frozen quality baseline

這一段回答：
tip-end 問題到底是 mesh patch，還是 upstream geometry truth？

### 第六段：`shell_v4`

- half-wing BL route
- solver-validation
- real-wing topology families
- closure ring / triangular end-cap class-level fixes

這一段回答：
如果 geometry baseline 已經乾淨，真正的 BL / solver-entry 問題會在哪裡爆？

---

## 最後的工程結論

### 1. `shell_v1 ~ v4` 不是高保真路線的全部

它只是：

- `M-HF`
- `origin SU2`
- `hpa_meshing_package`
- `esp_rebuilt coarse smoke / forensics`

這些前史之後，才長出來的主線後半段。

### 2. 真正的主線轉折，不是 `v1 -> v2 -> v3 -> v4` 這四個名字本身

真正的轉折其實是：

1. 從腳本到 package
2. 從 geometry export 到 CFD-ready external geometry
3. 從 black-box meshing 到 artifact-driven forensics
4. 從 downstream patch 到 upstream seam truth
5. 從 frozen tetra shell baseline 到 honest BL route

### 3. 現在最合理的心智模型

今天如果要看整條高保真主線，
最合理的分層是：

- `M-HF`: 結構高保真驗證層
- `origin SU2`: 早期外流高品質自動化嘗試
- `hpa_meshing_package`: 正式 package / contract / gates
- `esp_rebuilt`: 真實主翼外流幾何與 coarse smoke/forensics 主線
- `shell_v1 ~ v3`: 幾何真值與 frozen baseline 收斂
- `shell_v4`: BL / solver-validation 主線

### 4. 如果只問現在主線在哪裡

答案是：

- `shell_v3` 是 geometry baseline 的完成態
- `shell_v4` 是 active BL / solver-validation branch

而整條更早的高保真歷史，
則解釋了為什麼這兩句話今天成立。
