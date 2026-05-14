# HPA-MDO：人力飛機新概念設計管線

## 2026-05-14 Canonical Hybrid Half-Wing CFD Route Reset

WO-006 active CFD delivery route 已重設為 `canonical_hybrid_halfwing_v0`。唯一可讀的
active route state 是
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/manifest.yaml`，
並可用 `scripts/check_canonical_hybrid_cfd_release.py` 檢查。
外部 GPT Pro rescue 方向已保存到
`docs/reports/wo006_cfd_external_rescue_reference.md`；它是 stuck 時的工程參考，
不是 manifest 的替代 authority。

工程決策：WO-006R25/R26/R27/R28/R29/R30 全部退回 forensic evidence。R27 只證明
marker ownership；R28 證明 SU2 dual-control-volume quality 病態且 `CD=0.3916`
仍 fail；R29 排除單純 primal adjacent-tet volume ratio；R30 重現 SU2-style
`CV Sub-Volume Ratio≈2.0784e11` 並定位到 core/farfield tet construction。這些證據的
用途是說明舊 custom all-tet / global-star / owner-pyramid handoff 為什麼不能再當
active CFD route，不是開 R31 繼續修。

新 route policy 寫死幾件事：half-wing、root symmetry、`wing_upper` / `wing_lower`
作 primary force markers，`tip_wall` / `te_wall` / `closure_wall` 分開報告；BL 必須保留
prism/hexa，core 才用 tetra，interface 必須 conformal；不得把 BL split 成 all-tet
global-star handoff，不得把 closure face 靜默併入 `wing_wall` force marker，也不得把
保守 numerics 跑完當成功。manifest 裡只允許四個 release gate：
`TOOLCHAIN_PASS`、`PRESSURE_SANITY_PASS`、`ROUTE_SMOKE_PASS`、`GRID_LADDER_PASS`。
Phase 1 `TOOLCHAIN_PASS` 與 Phase 2 `PRESSURE_SANITY_PASS` 已通過；下一個 gate 是
Phase 3/4 的 hybrid BL route-smoke。
Phase 1 artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/toolchain_sanity/`：
2D wall-resolved `INC_RANS/SA` sanity cases 全部 completed 且 force window stable，
`CD` 分別為 NACA4412 `0.0207559`、current root DAE31 `0.0211785`、current tip
`0.0204750`。root DAE31 首跑失敗是因為 closed/cusped trailing edge 造成 Gmsh BL
負品質 quad；現在 2D sanity mesh 將 closed TE 正規化成 `0.002c` finite TE cap，這是
toolchain sanity regularization，不是 3D performance claim。

Phase 2 artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/pressure_sanity/`。
它使用 half-wing、root symmetry、Euler/slip pressure-only setup、`AOA=0`，
`MARKER_MONITORING=(wing_upper, wing_lower)`，並把 `tip_wall` / `te_wall` /
`closure_wall` 保留為獨立 marker。正式 run 在 `383` iterations 達成 SU2
`Cauchy[CD] < 1e-5`，最後 `CL=0.365344`、`CD=0.0177873`、`CMy=-0.0706675`，
last-100 `CL/CD` relative spans 約 `0.00445` / `0.00553`。SU2 dual quality 為
min orthogonality `19.4086 deg`、max CV face-area aspect ratio `7487.37`、
max CV sub-volume ratio `186725`，明顯不再是 R28/R30 的病態量級。工程邊界：
這只證明 pressure/geometry/marker/reference sanity；不是 viscous BL route-smoke、
不是 y+、不是 grid ladder，也不能宣稱 final HPA drag。

Phase 3 route-smoke gate 已新增於 `scripts/run_canonical_hybrid_phase3_route_smoke.py`
與 `tests/test_canonical_hybrid_phase3_route_smoke.py`，但目前 **尚未** 通過
`ROUTE_SMOKE_PASS`。第一個 Gmsh topological BL extrusion 嘗試確實保留了 hybrid cell
types（例如 `15,600` prism BL cells + `2,857` core tets），marker split 也保留，
但 SU2 `INC_RANS/SA` 仍快速發散；solver log 顯示 max CV sub-volume ratio 約
`1.81024e8`，已被 Phase 3 gate 明確視為不可接受的 dual-volume blocker。pps12/s6
one-iteration force breakdown 顯示 `tip_wall` / `te_wall` / `closure_wall` 的 CD
contribution 很小，主要壞 drag 來自 `wing_upper + wing_lower` primary wall，而不是
closure marker 被混進 force。工程判讀：不要再靠 CFL、gradient scheme、或 closure
小修補救這條 Gmsh-extruded path；下一步要改成 mesh-native owned BL topology / direct
hybrid SU2 handoff，再重新跑 `ROUTE_SMOKE_PASS`。

後續 direct handoff 原型已新增在同一個 Phase 3 script/test：它可以寫出
mesh-native direct surface-prism BL + Gmsh tetra core 的 hybrid SU2 mesh，保留
`15,600` prism BL cells、約 `4,750` core tets，且 `wing_upper` / `wing_lower` /
`tip_wall` / `te_wall` / `closure_wall` / `root_symmetry` / `farfield` ownership audit
通過。這條路沒有 all-tet global-star BL split，也沒有把 `bl_outer_interface` 當外部
marker 輸出；core mesher 改用 Gmsh `Algorithm3D=1`，因為 `Algorithm3D=10` 在這個
discrete-interface/geo-farfield 組合會產生含 node `0` 的 invalid tetra。工程邊界：
這仍不是 `ROUTE_SMOKE_PASS`。direct writer 之後已修正 prism ordering / marker face
orientation，使 `wing_upper` / `wing_lower` / farfield area-vector 方向與 Phase 2 pressure
mesh 一致；24-layer direct hybrid probe 的 SU2 dual metrics 改為 min orthogonality
`15.5098 deg`、max CV face-area aspect ratio `40411`、max CV sub-volume ratio
`158295`。但 Euler/slip 仍在 iter 10 divergence，初始 `CD≈0.2613`。direct writer
現在也會輸出 `direct_prism_quality_gate`；default wall-resolved first height
`5e-5 m` 讓 root-symmetry sidewall quad aspect ratio 達到約 `7794.66`，24-layer probe
有 `90` 個 root-side quads 超過 `1000`，所以這條 direct topology 會在 solver 前被
block。下一步應先查 root/TE prism distortion、高曲率 edge、root-symmetry hole 與
partial-BL/cap policy，不應把這個 topology/orientation success 當 viscous CFD 成功。

最新 partial-BL probe 進一步把問題切開：只對 `wing_upper` / `wing_lower` 長 prism，
並把 `tip_wall` / `te_wall` / `closure_wall` 留給 explicit caps 時，
`points_per_side=42`、24 layers、growth `1.2` 會得到 `124,416` 個 prism，signed
volume 全正，root-symmetry sidewall max aspect ratio `966.04`，`direct_prism_quality_gate`
可通過。Artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/partial_wing_prism_caps_pending_pps42_l24/`。
這個 handoff 也已把 partial-BL sidewall quads 分回 diagnostic markers：
`tip_wall=1944` quads、`te_wall=1344` quads、`closure_wall=192` quads。工程邊界：
這仍不是完整 CFD mesh，因為 original cap faces 還沒 materialize：
`tip_wall=82`、`te_wall=28`、`closure_wall=4` source faces 必須先與 BL outer interface
形成 conformal cap，才能交給 tetra core；artifact status 仍是
`blocked_cap_faces_missing`。

小型 cap-materialized core probe 已建立：
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/partial_wing_cap_core_probe_pps12_l4/`
使用 `points_per_side=12`、4 BL layers，將 BL outer interface、cap sidewall quads、
original cap faces 組成 triangulated discrete inner boundary。Gmsh core fill 產生
`7,295` tetra、`0` forbidden pyramid/prism/hex core cells。工程邊界：這只是小型
topology proof，不是 wall-resolved `ROUTE_SMOKE_PASS`；pps42/l24 full-resolution
merge 與 merged SU2 writer 還沒通過。

GPT Pro 後續審核把下一個 blocker 收斂成更硬的 topology contract：partial BL 的
非 root rim quad 不能直接交給 tetra core；它必須先經過 prism-to-pyramid-to-tet
transition collar。最小人工單元已新增於
`write_phase3_minimal_transition_unit_su2()`，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/minimal_transition_unit/`。
它寫出 `2` prisms、`4` pyramids、`18` tetra，`tet_to_prism_quad_contact=0`、
`prism_quad_to_pyramid_base_contact=4`、`pyramid_triangle_to_tet_contact=16`、
`boundary_faces_unmarked=0`，SU2 boundary ownership pass。工程邊界：這是人工
topology unit，不是真翼 mesh；下一步應把這個 collar contract 套回真翼
`points_per_side=42`、layers `3 -> 8 -> 16 -> 24` 的 build-up，而不是繼續把問題
當成 Gmsh multi-loop cap surface repair。

真翼 partial-BL transition-collar handoff 也已建立在
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/partial_wing_transition_collar_handoff_pps42_l24/`：
`124,416` prisms + `3,480` pyramids，原本會被誤標成 diagnostic wall 的 rim quads
已轉成 internal pyramid bases（`tip_wall=1944`、`te_wall=1344`、`closure_wall=192`），
`transition_collar_interface` 產生 `13,920` triangular faces，`force_wall_rim_marker_leak_count=0`，
pyramid signed volume non-positive count `0`，SU2 boundary ownership pass，direct prism
quality gate pass。工程邊界：這仍是 caps/core pending handoff，不是 route-smoke；
下一步是把 original tip/TE/closure cap physical faces 與 tetra core merge 進同一個
hybrid SU2 mesh。

小型 collar+cap core probe 已新增：
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/partial_wing_transition_collar_core_probe_pps12_l4/`。
在 `points_per_side=12`、4 BL layers 下，新的 transition collar interface 加上
original cap faces 交給 Gmsh core fill，產生 `9,088` tetra、forbidden core element
counts `{}`。這證明 collar+cap shell 在小尺度可被純 tetra core 吃下；但它仍不是
merged SU2 hybrid mesh，也還沒有 pps42/l24 scale-up、pre-solver dual-quality gate、
pressure-only CD sanity 或 RANS route-smoke。
後續 pps24/l4 scale probe 顯示 collar height 不能太厚：`2.5e-4 m` 仍觸發 Gmsh
`PLC Error: A segment and a facet intersect at point`，但 `1.0e-4 m` thin collar
可生成 `12,028` tetra 且 forbidden core element counts `{}`。下一步 scale-up 應先用
thin collar policy，再往 layers `8 -> 16 -> 24` 推，不要直接用厚 collar 衝 pps42/l24。
thin collar 的 pps42 scale ladder 已手動推到 16 layers：l4 產生 `16,462` tetra
（約 `51 s`）、l8 產生 `20,093` tetra（約 `118 s`）、l16 產生 `26,600` tetra
（約 `355 s`），forbidden core element counts 都是 `{}`。工程邊界：l16 已偏重，
l24 不應盲跑；下一步更應先寫 merged SU2 hybrid mesh，並在 l4/l8 上做 marker/dual-quality
與 pressure-only sanity，再決定是否值得跑 l24。

merged SU2 hybrid writer 已新增 pps12/l4 小尺度 proof：
`output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/partial_wing_transition_collar_core_hybrid_pps12_l4/`。
它寫出 `5,376` prisms + `340` pyramids + `8,690` tetra，移除 internal
`bl_outer_interface` / `transition_collar_interface` markers，保留
`wing_upper` / `wing_lower` / `tip_wall` / `te_wall` / `closure_wall` /
`root_symmetry` / `farfield`，SU2 marker audit / ownership pass。writer 也會做 final
node compaction；目前移除 `4` 個 unused surface-layer nodes，修掉 SU2 的 `NPOIN`
mismatch preprocessing error。
writer 內建的 mixed-element SU2-style subvolume proxy 也會在 solver 前 fail：
pps12/l4 的 max CV sub-volume ratio proxy 為 `4.371350805765444e11`，worst point
`3234` 的 source pair 是 `tetra_core|tetra_core`，但 incident elements 包含
`3` 個 boundary-layer prisms、`2` 個 transition-collar pyramids 與 `21` 個 core tets。
這把 blocker 從 marker/NPOIN 收斂到 local collar/core-interface dual-volume quality。

但同一 pps12/l4 merged mesh 的 pressure-only smoke 仍 fail：
`partial_wing_transition_collar_core_hybrid_pps12_l4_pressure_probe/`。SU2 已能讀 mesh，
但只跑到 `3` rows / final iteration `2`，dual-control-volume metrics 爆掉：
min orthogonality `0.0105006 deg`、max CV face-area aspect ratio `7.58862e9`、
max CV sub-volume ratio `4.37135e11`，force breakdown missing，初始 CL/CD 也完全不可信。
工程判讀：transition collar 解決了 prism→tet element compatibility，但目前 thin collar
附近的 core tetra dual subvolume 仍是 SU2 vertex-dual 病態來源；下一步要修 collar/core
interface geometry/quality，不能進 RANS。
小型 collar-height sweep 顯示這不是單純 Gmsh point sizing 問題：`collar_height=2.0e-3 m`
能把 proxy 降到約 `8.87e9`，比 `1.0e-4 m` 好很多但仍 fail；`2.5e-3 m` 開始出現
overlapping facets。因此下一步不能只調 thickness，必須重設 collar side-triangle quality
或改 transition topology。
解析度也不是單一解：pps42/l4 merged writer 可產生 `20,736` prisms + `580` pyramids +
`16,462` tetra，root sidewall aspect 約 `966` 已過 smoke gate，但 dual proxy 仍是
`1.1725639068823458e10`。所以 pps42/l4 不應升級成 pressure/RANS route。
GPT Pro 建議的 Build 1 真翼 `pps42/layers=3` 也已補跑：
`partial_wing_transition_collar_core_hybrid_pps42_l3/` 可寫出 `15,552` prisms +
`435` pyramids + `15,705` tetra，root sidewall aspect 約 `966` 且 direct prism
quality gate pass，但 mixed dual proxy 仍 fail，max CV sub-volume ratio 約
`3.3939807886633167e11`，worst source pair 是 `tetra_core|tetra_core` 並鄰接
transition-collar pyramid。工程判讀：3-layer build-up 也不能直接進 pressure sanity；
目前 blocker 是 collar/core local dual-volume topology，不是單純 BL layer count。
hotspot geometry diagnostic 進一步顯示 worst point 同時接到 `6.0e-5 m` 級 local
edge 與約 `1.68 m` 的 core edge，incident core tet edge-ratio 可到 `~1.37e4`；
下一步要做 collar/core local grading、structured transition patch 或成熟 layer-addition
mesher cross-check，而不是只調 global core size 或降 BL layers。給 GPT Pro / meshing
specialist 的可複製問題包在
`docs/reports/wo006_cfd_collar_core_blocker_gpt_pro_prompt.md`。
`dual_subvolume_proxy` 也已把 `max_hotspot_incident_edge_length_ratio=1000` 納入
smoke threshold；pps42/l3 會同時被 dual ratio 與 hotspot edge-ratio blockers 擋下。
新的 `segmented_collar_scale_transition_unit/` 人工拓樸單元已驗證下一個可行方向：
把長 prism rim quad 切成 `16` 個短段後，每個 collar base 的 max edge ratio 約
`500`，`tet_to_prism_quad_contact=0`、non-root exposed prism quad `0`、dual proxy pass。
工程邊界：這只證明 segmentation/ramp contract，不是真翼 route-smoke；下一步才是把
這個 rule 套到真翼 TE/tip/closure rim。pps42/l24 真翼 handoff 已量化：原本
`3,480` 個單一 rim quads 要降到 edge-ratio threshold `1000`，約需 `6,928` 個
segmented rim pieces（`te_wall=4,376`、`tip_wall=1,944`、`closure_wall=608`）；
per-quad split plan 已寫入 artifact，預估最大切後 base edge ratio 約 `997.8`。
同一 plan 壓回 source mesh 後是 `145` 條 source rim edges、約 `809` 段
（`te_wall=640`、`tip_wall=81`、`closure_wall=88`），更接近下一步實作量級。
新的 pps42/l3 segmented source-rim handoff 已把這個 rule 實作到真翼表面：
`64` 條長 source rim edges 先切成 `728` 段，新增 `664` 個 source vertices，
輸出 `17,544` prisms + `2,427` pyramids；collar base 最大 edge ratio 降到
約 `982.03`，每個 rim quad 不再需要二次分割，force-wall rim leak `0`，
pyramid non-positive `0`。這仍是 caps/core pending，不是 route-smoke。
同一 segmented surface 的 pps42/l3 core merge 也已跑完：`36,327` tetra、
runtime 約 `179 s`、required markers/ownership pass，但 dual proxy 仍 fail
（max CV sub-volume ratio 約 `1.6899e11`，hotspot incident edge ratio 約
`2.2339e4`）。所以目前卡點已經不是 prism rim base，而是 collar-adjacent
tetra core grading；不可進 pressure/RANS。
也測過較窄的 boundary-point sizing：pps12/l4 在 `transition_collar_interface`
points 設 `0.05 m` mesh size，runtime 約 `110 s`，但 dual proxy 反而惡化到
`1.1247e16`，hotspot edge ratio 約 `1.072e5`。所以不要把下一步寫成
Gmsh point-size hack；要做明確 multi-row / structured transition patch。
新的 `structured_transition_patch_unit/` 人工單元已證明這個方向：`4` 個
segmented collar bases + `4` 個 primary pyramid collars + `40` 個 prisms +
`106` 個 pyramids + `432` 個 tets，兩層 transition rows 為
`0.03 m -> 0.09 m`（growth ratio `3.0`），並把 `102` 個 sidewall quads 轉成
sidewall pyramid/tet triangular interface。dual proxy pass，沒有
tet-to-prism-quad contact、exposed prism quads 或 exposed pyramid faces。這還不是真翼
route-smoke；下一步要把同一套 sidewall closure / triangular-interface 規則套回真翼
pps42/l3，再重新跑 dual gate。
目前已先做 bounded 真翼 handoff smoke：
`segmented_partial_wing_structured_transition_handoff_tiny/` 用真翼幾何與 segmented
collar pipeline，但刻意放大 first layer 到 `1e-3 m`、只用 `points_per_side=4` /
`spanwise_subdivisions=1` / `layers=1`。它產生 `482` prisms、`1175` pyramids、
`4512` tets，topology / ownership / dual proxy pass。這只證明資料結構與
triangular-interface contract 可投影到真翼，不是 y+ 或 route-smoke 證據。
pps42/l3 的 projection gate 也已跑過：`9708` 個 collar interface triangles 若照
目前 naive per-triangle sidewall closure 放大，會投影到 `330,627` 個 volume
elements，超過 `250,000` 的 Mac-safe gate；因此不能直接放大 tiny handoff。
改用 stitched-sheet projection 後，因為 interface 只有 `1624` 個 boundary edges
需要 closure，投影總量降到 `55,627` 個 volume elements，低於 gate。下一步要做
shared-node stitched transition sheet。
shared-node stitched transition sheet 現在已有 pps42/l3 真翼 handoff artifact：
`segmented_partial_wing_structured_transition_handoff_pps42_l3_stitched_r010_030/`。
實作後發現原先 `0.03 m -> 0.09 m` transition rows 在 pps42/l3 仍會造成
structured-transition prism dual hotspot（max CV sub-volume ratio 約 `3.36e8`），
所以 active 設定改成 `0.01 m -> 0.03 m`。新的 artifact 產生 `36,960`
prisms、`5,987` pyramids、`14,240` tetra，總 `57,187` volume elements；
topology / element-quality / SU2 boundary ownership / dual proxy 全部 pass。這仍不是
`ROUTE_SMOKE_PASS`：它只證明 partial-BL prism rim 已可用 stitched transition
轉成 triangular core-interface topology；下一步仍要做 caps/core merge 和
pressure-only sanity，不能直接跑 viscous RANS。

closed-wall direct prism wrapper 也重新檢查過：pps12/l16 可把 dual proxy 清到
`pass`（無 `>1e7` hotspot）且 prism non-positive count `0`，但 root sidewall aspect
仍約 `3589`；pps42/l16 root aspect 可降到約 `966`，但 cap/TE/tip 附近出現
`245` 個 non-positive prisms。新增的 marker/layer localization 顯示這些翻轉集中在
`wing_upper=124`、`te_wall=121`，主要是 layers `10-15` 的 aft/TE 區域。工程判讀：
closed wrapper 說明「core 不要貼到薄 BL 內層」是對的，但 raw full-cap extrusion
仍不可直接當 route-smoke mesh。
`closed_wall_wrapper_layer_window_pps42_span4/` 進一步把這個判斷變成可重跑的
layer-window probe：在 `points_per_side=42`、growth `1.2` 下，4/5/6 layers 的 prism
signed volume gate pass，但這些薄層先前 dual proxy 仍是 `~1e10` 量級；7 layers 開始出現
`10` 個 non-positive prisms，8/9/10/16 layers 分別惡化到 `22` / `39` / `65` / `245`。
工程邊界：沒有簡單的 pps42 closed-wall layer count 同時滿足「足夠厚以隔離 core
dual-volume」與「cap/TE prism 不翻轉」。下一步不能只縮 layers 或直接重跑 RANS；要處理
TE/aft cap 的 BL termination / smoothed cap extrusion / transition-buffer topology。
第一個 TE-stageback signed-volume probe 已產生：
`closed_wall_te_stageback_pps42_l16_cap6/`。它保留 `points_per_side=42`、main
wing wall `16` layers，但把 diagnostic cap/TE/tip/closure 與 TE 附近 primary triangles
限制在 `6` layers；`stageback_segments=0` 時仍有 `124` 個 `wing_upper`
non-positive prisms，而 `stageback_segments=2/4/6/8/10` 全部讓 prism signed-volume
gate pass、non-positive count `0`。工程判讀：TE/aft stageback 是目前最有希望的
closed-wrapper 修正方向；exposed internal step sidewalls 現在會標成
`bl_termination_interface`，不會被混進 `wing_upper` / `te_wall` force wall。
但這仍只是 signed-volume diagnostic，還需要把 termination interface 接到 tetra core、
跑 SU2-style dual proxy 與 pressure-only CD sanity，才可能變成 route-smoke candidate。
stageback core-hybrid writer 也已新增，會把 `bl_outer_interface` 與
`bl_termination_interface` 一起交給 tetra core，並在 final SU2 marker set 裡隱藏這兩個
internal interfaces。pps42/l16/cap6 sweep 顯示 `stageback_segments=6` 目前最好：
prism quality gate pass、約 `16,637` core tets、max dual sub-volume proxy 約
`6.04e9`，仍 fail `1e7` gate；core mesh size 從 `0.35` 掃到 `0.12` 時 core tet count
與 dual proxy 不變，表示目前 blocker 不是單純全域 core sizing，而是 termination/outer
BL interface 附近的 local grading 或 transition topology。
naive whole-interface transition-buffer 也已測過：
`closed_wall_te_stageback_buffered_core_hybrid_pps42_l16_cap6_s6_b2/`。它加入
`15,980` 個 non-wall buffer prisms，combined prism quality gate pass，但 Gmsh core fill
在 SU2 handoff 前以 `Invalid boundary mesh (overlapping facets)` 停住。工程判讀：
不能把整個 outer+termination shell 直接等距 extrude 當 buffer；下一步要改成局部
termination ramp / structured transition patch，或改用成熟 layer-addition mesher 生成
這個區域。

## 2026-05-14 WO-006R8 Basic Airfoil BL Sanity Benchmark

`scripts/run_wo006r8_basic_airfoil_bl_benchmark.py` 新增一個刻意簡化的 CFD route
sanity case：2D `NACA4412`、chord `1.130189765 m`、`V=6.5 m/s`、`Re≈5.03e5`、
`alpha=4 deg`，用 Gmsh `BoundaryLayer` 產生 wall-resolved BL quads，SU2 config 使用
`INC_RANS + SA + MARKER_HEATFLUX=(airfoil,0.0) + MARKER_FAR=(farfield)`。這是 debug
工具鏈用的簡單 case，不是 Baseline A 幾何，也不能替代 Baseline A mesh ladder。

最新長跑 `solver_5000` artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r8_basic_airfoil_bl_benchmark/solver_5000/`：
mesh 約 `25,168` cells / `15,190` nodes，其中 BL quads `4,833`。SU2 在
`4597` iterations 達成 `Cauchy[CD] < 1e-6` 後結束，最後
`CL=0.887615`、`CD=0.021682`、`CMz=0.100707`；阻力量級是合理的 `0.0XX`，
不是 WO-006J/F 那種 `CD≈0.5-0.6`。最後 100 iter `CL` span 約 `0.0046%`，
`CD` span 約 `0.0456%`，所以判讀是 basic route sanity pass / force convergence usable。

工程判讀：這證明「SU2 + viscous no-slip + BL」在簡單 HPA-Re case 上沒有先天把 CD 算成
0.5 的工具鏈錯誤；Baseline A 目前的大 CD 更像幾何/BL prism/pressure setup 或 3D handoff
問題。下一步仍要先修 Baseline A BL/core handoff quality，再回 coarse/medium/fine ladder。

## 2026-05-14 WO-006R18 Handoff Residual Localization Probe

`scripts/probe_wo006r18_handoff_residual_localization.py` 接在 R17 後面，專門把最後
BL/core handoff residual 變成可修的幾何證據。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r18_handoff_residual_localization_probe/`。

實跑結果和 R17 數字一致：共有 `68` 個 residual triangles；其中 `core_wall_loop_cap=60`
是 unowned，另外 `core_tip_receiver_outer=4` / `wake_edge_receiver=4` 是 candidate-owned
但 split incompatible。R18 把 loop-cap residual 分成左右兩個 fan，每個 `30` triangles /
`31` nodes，位置在 `y≈±17.201-17.202 m`、`x=0.000327-0.644058 m`、
`z=2.597761-2.689000 m`；split-incompatible 部分集中在兩個 `tip_receiver/left_tip`
cells：`26110`、`26111`，各自 target `6` triangles、match `4`、unmatched `2`。

WO-006I data-authority-restored preflight 現在會讀 R18，active blocker 仍是
`near_wall_hybrid_tet_prism_handoff_not_compatible`，但 mesh repair target 已收斂成
`materialize_core_wall_loop_cap_owner_cells_then_repair_left_tip_receiver_split`。工程判讀：
這還不是 CFD mesh，也沒有 y+ 或 CL/CD/Cm；它只是把下一個 repair target 從「修 handoff」
縮到「先補兩個 loop-cap owner fan，再修左 tip receiver split」。

## 2026-05-14 WO-006R19 Loop-Cap Owner Pyramid Probe

`scripts/probe_wo006r19_loop_cap_owner_pyramid.py` 驗證 R18 的第一個 repair 假設：
用既有 `physical_wall_edge_receiver` quads 當 pyramid base，左右 loop-cap fan center
當 apex，形成 near-wall side 的 owner pyramids。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r19_loop_cap_owner_pyramid_probe/`。

實跑結果：`60` 個 physical-wall-edge receiver faces 產生 `60` 個 owner pyramid cells，
可以 `60/60` match `core_wall_loop_cap` triangles；owner volume 全為正，
`min=6.26e-7 m^3`、`max=6.52e-5 m^3`。這表示 loop-cap unowned family 有可行的
mixed-cell ownership repair basis，但不是 final mixed SU2 mesh。

剩餘 blocker 只剩 R17/R18 那 `core_tip_receiver_outer=4` / `wake_edge_receiver=4`
left-tip shared-tessellation mismatch，以及尚未寫出 merged mixed mesh、尚未 postprocess y+、
尚未跑 SU2 ladder。WO-006I data-authority-restored preflight 現在的 mesh repair target 是
`repair_left_tip_receiver_shared_tessellation_then_write_loop_cap_owner_pyramid_mixed_mesh`。

## 2026-05-14 WO-006R20 Left-Tip Star Tessellation Probe

`scripts/probe_wo006r20_left_tip_star_tessellation.py` 驗證 R19 之後最後兩個
`tip_receiver/left_tip` cells 的 shared-tessellation repair basis：只針對 R17 hybrid
audit 中 `unmatched_triangle_count > 0` 的 cells (`26110`、`26111`)，用 cell center
star tessellation 直接 own 三個 core-facing faces 的 target triangles。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r20_left_tip_star_tessellation_probe/`。

實跑結果：target cells `2`、target triangles `12/12` matched，其中
`core_outer_edge_receiver=4`、`core_tip_receiver_outer=4`、`wake_edge_receiver=4`；
star-tet volume 全為正，`min=2.71e-7 m^3`、`max=3.45e-7 m^3`，R19/R20 後的
R17 residuals 為 `{}`。這代表最後已知 left-tip local handoff residual 有正體積修法依據。

工程邊界：R20 仍不是 final mixed SU2 mesh，沒有 marker/quality-gated BL+core handoff，
也沒有 near-wall y+ 或 SU2 ladder。WO-006I data-authority-restored preflight 現在會把
core closure 推進到 `handoff_repair_basis_ready_mixed_mesh_pending`，active blocker 改成
`near_wall_merged_mesh_handoff_missing`；下一步是寫出 marker/quality-gated mixed BL+core
SU2 handoff 並做 y+ probe，而不是直接跑 medium/fine solver。

## 2026-05-14 WO-006R21 Split Assembly Conformality Probe

`scripts/probe_wo006r21_split_assembly_conformality.py` 檢查 R17/R19/R20 的 local repair
basis 能不能直接組成全域 conformal near-wall split volume。這一步是 mixed BL+core SU2
writer 前的 topology gate：不是看單一 core-facing face 有沒有 match，而是把 candidate cells
依目前 selected tet/prism pattern split 後，檢查 cell-to-cell internal faces 是否還有 unmatched
triangles 或 non-manifold faces。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r21_split_assembly_conformality_probe/`。

實跑結果：candidate cells `26880` 會被拆成 `161280` 個 local split volume elements；
R17 selected core-facing cells `2638`。目前 assembly 不是 conformal：有 `7960` 個 internal
split leak faces，另有 `64` 個 non-manifold split faces。這代表 R17 的 per-cell best pattern
不能直接拿去寫 final mixed mesh；否則 SU2 會看到不合法的內部拓樸，而不是可解讀的 BL CFD。

工程邊界：R21 把下一步收斂成全域 conformal split assignment 問題。WO-006I
data-authority-restored preflight 現在的 active blocker 是
`near_wall_split_assembly_internal_nonconformal`，mesh repair target 是
`solve_global_conformal_near_wall_split_assignment_before_mixed_mesh_writer`。在這個 gate
過之前，不應該跑 medium/fine SU2，也不應該宣稱 Baseline A CL/CD/Cm。

## 2026-05-14 WO-006R22 Global Star Split Basis Probe

`scripts/probe_wo006r22_global_star_split_basis.py` 接在 R21 後面，改用全域一致的
cell-center star split basis：internal quad faces 用 deterministic diagonal，core-facing
boundary faces 則使用 R19/R20 修復後的 target triangles。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r22_global_star_split_basis_probe/`。

實跑結果：Baseline A current-GO near-wall/receiver candidate 仍是 `26,880` 個 cells；
global-star split 產生 `322,432` 個非退化 tet elements，target triangles
`5594/5594` match，internal split leaks `0`，non-manifold split faces `0`，
non-positive tets `0`。剩餘 blocker 是 `128` 個 degenerate star triangles，集中成
sharp-edge / zero-area cell reduction 問題，而不是 R21 的全域 internal nonconformal。

工程邊界：R22 仍不是 final mixed SU2 mesh，沒有 marker/quality-gated BL+core handoff，
沒有 near-wall y+，也沒有 SU2 ladder。WO-006I preflight 現在會把 active blocker 更新成
`near_wall_global_star_split_degenerate_cells`，recommended repair 是
`reduce_degenerate_star_cells_before_mixed_mesh_writer`。在這個 local cell reduction 過之前，
不應該跑 medium/fine SU2，也不能宣稱 Baseline A CL/CD/Cm。

## 2026-05-14 WO-006R23 Degenerate Star Cell Localization Probe

`scripts/probe_wo006r23_degenerate_star_cell_localization.py` 把 R22 的
`128` 個 degenerate star triangles 轉成 cell/face/coordinate evidence。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r23_degenerate_star_cell_localization_probe/`。

實跑結果：`128` 個 degenerate triangles 分布在 `32` 個 cells，全部是 `wake_receiver`
role/source，marker 為空字串；bounds 約 `x=0.6569-1.2772 m`、
`y=-17.166143..17.166143 m`、`z=-0.0950..2.5975 m`。sample records 顯示零面積
triangle 來自 wake receiver face 內重複座標點，而不是 core target triangle marker 本身。

工程判讀：下一個修復目標已縮小成 wake-receiver local cell-type reduction /
degenerate-cell special casing。這仍不是 mixed SU2 mesh、不是 y+，也不是 CFD ladder；
但它避免後續再把問題誤判成 SU2 iteration、BL physics 或全域 split assignment。

## 2026-05-14 WO-006R24 Degenerate Cull Handoff Basis Probe

`scripts/probe_wo006r24_degenerate_cull_handoff_basis.py` 讀取 R22/R23 artifacts，檢查
degenerate star triangles 是否全都可視為空 marker wake-receiver zero-area faces。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r24_degenerate_cull_handoff_basis_probe/`。

實跑結果：R24 verdict 是 `degenerate_cull_basis_ready_mixed_mesh_pending`；
`128` 個 degenerate triangles 全部可作為 wake-receiver cull/reduction basis，沒有 owned
marker 被吃掉。WO-006I preflight 已把 active topology state 推進到
`handoff_degenerate_cull_basis_ready_mixed_mesh_pending`，blocker 改成
`near_wall_merged_mesh_handoff_missing`，recommended repair 是
`write_culled_global_star_mixed_su2_handoff_and_yplus_probe`。

工程邊界：這代表 topology/cell-reduction basis 足以進入 writer probe，但還不是 mixed SU2
mesh、不是 marker/quality gate pass、不是 y+，也不是 SU2 coarse/medium/fine ladder。

## 2026-05-14 WO-006R25 Culled Mixed SU2 Handoff Probe

`scripts/probe_wo006r25_culled_mixed_su2_handoff.py` 依 R24 cull basis 寫出第一個
Baseline A mixed SU2 handoff probe：global-star near-wall tets + loop-cap owner
cells + R13 repaired core tet mesh，並做 final volume-boundary marker audit。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r25_culled_mixed_su2_handoff_probe/`。

實跑結果：成功寫出 `culled_global_star_mixed_handoff.su2`，`56,873` nodes /
`332,221` volume elements，全部 tetra，mixed volume quality `pass`，non-positive
volume elements `0`。near-wall first-layer estimate 仍是 `5e-5 m` 對應 `y+≈1.04`
量級。R25 也把 `68` 個已確認為 exterior 的 physical wall / physical-wall-edge
closure faces 補入 `wing_wall`，marker counts 變成 `wing_wall=1924`、
`farfield=2366`。

但 final boundary marker audit 仍 `fail`：還有 `68` 個 exterior volume faces 無 SU2
marker，剩餘 unmarked area 約 `0.0759 m^2`。它們集中在 loop-cap fan / wake-edge
對接區，不是全域 volume quality 問題，也不是 solver iteration 問題。WO-006I preflight
現在會把 active blocker 更新成 `near_wall_mixed_su2_boundary_marker_blocked`，
recommended repair 是 `localize_and_close_remaining_mixed_su2_boundary_leaks_before_solver`。
在這個 gate 過之前，不應該跑 Baseline A medium/fine SU2。

## 2026-05-14 WO-006R26 Remaining Boundary Leak Localization Probe

`scripts/probe_wo006r26_remaining_boundary_leak_localization.py` 接在 R25 後面，
把最後 `68` 個 unmarked exterior volume faces 做成可審核的 marker ownership repair
plan，而不是直接把它們硬塞進 SU2 solver。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r26_remaining_boundary_leak_localization_probe/`。

實跑結果：`68` 張外露 face 全部被分類，沒有 unclassified face；總面積
`0.075898249 m^2`，bounds 約 `x=0.000327-0.656936 m`、
`y=±17.202316 m`、`z=2.597441-2.689000 m`。依 adjacent source 分成
`loop_cap_owner_pyramid_tet_split=64`、`core_tet_mesh=2`、
`culled_global_star_near_wall=2`；依幾何 ownership 分成
`loop_cap_owner_pyramid_exterior=60`、`loop_cap_physical_wall_edge_closure=4`、
`candidate_wake_edge_receiver_boundary=2`、`core_wake_edge_receiver_boundary=2`。
repair plan 狀態是 `repair_plan_ready`，只允許把這些已定位的 solid closure faces 補到
`wing_wall`。

工程判讀：這把 R25 的 marker blocker 從「還有外露面，不可跑 solver」推進成
「可套用的 bounded marker repair plan」。但 repair 尚未寫回 mixed SU2 writer，marker
audit 也尚未 pass，所以仍不能跑 medium/fine CFD ladder，也不能解讀 Baseline A CL/CD/Cm。

## 2026-05-14 WO-006R27 Apply Boundary Marker Repair Probe

`scripts/probe_wo006r27_apply_boundary_marker_repair.py` 已把 R26 repair plan 套回
mixed SU2 handoff：只接受 `recommended_marker=wing_wall` 的 R26 leak records，重寫
`culled_global_star_mixed_handoff_r27_repaired.su2`，並重新跑 final volume-boundary
marker audit。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r27_apply_boundary_marker_repair_probe/`。

實跑結果：mesh 仍是 `56,873` nodes / `332,221` tetra volume elements；marker counts
是 `wing_wall=1992`、`farfield=2366`。final boundary marker audit `pass`：
`4358/4358` exterior faces marked，`unmarked=0`、`extra=0`、duplicate marker faces `0`、
nonmanifold volume faces `0`；mixed volume quality 也 `pass`，non-positive volume `0`。

工程判讀：這是第一個 Baseline A current-GO mixed SU2 handoff marker/quality gate pass，
可進 bounded SU2 route-smoke wiring；但它還不是 solver result、不是 postprocessed y+、
不是 coarse/medium/fine ladder，也不是 CL/CD/Cm 或 drag truth。當前問題與解法 register
整理在 `docs/reports/wo006_cfd_problem_solution_register.md`。

## 2026-05-14 WO-006R28 R27 SU2 Route-Smoke Probe

`scripts/probe_wo006r28_r27_su2_route_smoke.py` 把 R27 repaired mixed mesh 接到
wall-resolved SU2 config：`INC_RANS`、`SA`、`INC_NONDIM=INITIAL_VALUES`、
`MARKER_HEATFLUX=(wing_wall,0.0)`、`MARKER_FAR=(farfield)`，並把 config marker audit、
SU2 history stability、CD-order sanity 和 SU2 solver-side mesh-quality parser 寫成 gate。
測試在 `tests/test_wo006r28_r27_su2_route_smoke_probe.py`。

實跑結果分兩個診斷 case。FDS/MUSCL/CFL=1 case 可讀到 R27 mesh/markers，但 SU2 在
iteration `5` divergence；solver log 顯示 dual-control-volume quality 已病態：
min orthogonality `0.00108069 deg`、max CV face-area aspect ratio `5.15199e8`、
max CV sub-volume ratio `2.07841e11`。保守 JST、`MUSCL_FLOW=NO`、`CFL=0.02` case
可以跑滿 `180` rows，但最後 `CL=0.6908`、`CD=0.3916`、`Cm=-0.1424`，last-100
force/residual stability 都 fail，且 CD 仍遠高於 HPA main-wing 合理 `0.0XX` 量級。

工程判讀：R27 marker repair 讓 SU2 讀得到 mesh，不代表 CFD setup 可用。R28 證明現在的
active blocker 是 BL/core transition sizing / mixed-mesh dual-volume quality；不能用這個
mesh 推 medium/fine ladder，也不能把有限 CL/CD/Cm 當低信心 CFD。下一步要把 SU2 dual
quality 極值 localization 回 near-wall/global-star、loop-cap owner pyramid 或 core tetra source。

## 2026-05-14 WO-006R29 Dual Quality Source Localization Probe

`scripts/probe_wo006r29_dual_quality_source_localization.py` 是接在 R28 後面的
mesh-source diagnostic，不跑 SU2、也不產生 CFD 係數。它重建 R25/R27 mixed mesh
provenance，掃描所有 internal shared faces 的相鄰 tet volume jump，想確認 R28 的
SU2 dual-control-volume pathology 是否能被單純的 primal source-pair size jump 解釋。
測試在 `tests/test_wo006r29_dual_quality_source_localization_probe.py`。

實跑 artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r29_dual_quality_source_localization_probe/`。
結果是 negative but useful：nodes / volume elements 仍是 `56,873` / `332,221`；
記錄到 `1,432` 個 volume ratio `>=1000` 的 internal faces，但最大 ratio 只有
`29263.77`，低於這個 probe 設的 `1e6` blocker threshold。最差 source pair 是
`culled_global_star_near_wall|culled_global_star_near_wall`；`core_tet_mesh|culled_global_star_near_wall`
最高約 `14309.05`。這無法解釋 R28 SU2 log 裡的 max CV sub-volume ratio `2.07841e11`。

工程判讀：R29 排除了「單純 shared-face adjacent tet volume jump >1e6」這條解釋路線。
R28 的 dual-quality blocker 仍然存在；下一步要定位 SU2 dual/control-volume metric
本身的幾何來源，或重建/解析 SU2 對 vertex dual volumes 的品質計算，不能只靠 primal
tet volume ratio 繼續猜。

## 2026-05-14 WO-006R30 SU2 Dual Subvolume Localization Probe

`scripts/probe_wo006r30_su2_dual_subvolume_localization.py` 接在 R29 後面，改用
SU2 source 裡 `CPhysicalGeometry::ComputeMeshQualityStatistics` 的同類邏輯：對每個
vertex dual control volume 記錄 sub-element volume 的 max/min，而不是只看整顆 tet
或 shared-face volume jump。測試在
`tests/test_wo006r30_su2_dual_subvolume_localization_probe.py`。

實跑 artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r30_su2_dual_subvolume_localization_probe/`。
R30 重現 R28 的 SU2 `CV Sub-Volume Ratio` 量級：`max=207840927876.89658`
（R28 solver log 是 `2.07841e11`）。最壞點是 point `56784`，座標
`x=-2.684534382258478`、`y=21.21191727545568`、`z=1.867804964000869`，
`point_markers=["farfield"]`，incident elements 為 `{"core_tet_mesh": 1704}`；
第二壞點 point `56503` 也是 `farfield` / `core_tet_mesh`。後續幾個 hotspots 才混到
tip 附近的 core/near-wall transition。

工程判讀：R28 的主 dual-volume 爆點不是 BL wall marker 本身，而是 core/farfield
tet construction 在 tip/farfield 周邊把極小 subvolume 和數 m3 級 subvolume 接到同一個
vertex dual CV。下一步要修 core/farfield/tip transition mesh sizing 或 farfield-core
tet construction；在 R30 blocker 消掉前，不能再用 R27 mesh 跑 medium/fine ladder。

## 2026-05-14 WO-006R17 Hybrid Tet/Prism Split Probe

`scripts/probe_wo006r17_hybrid_tet_prism_split.py` 把 R16 往混合 cell handoff 方向再推一步：
每個 near-wall/receiver hexa 可選三軸 two-prism split，也可選四種 body-diagonal six-tet
decomposition，逐 cell 選最能 match R13 core-interface triangles 的局部 representation。
artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r17_hybrid_tet_prism_split_probe/`。

實跑結果：R17 match `5590 / 5658` core triangles，比 R16 的 `5274/5658` 再提升；
`bl_outer_interface=2048`、`core_outer_edge_receiver=128`、`core_wake_outer_match=64` 已可
全部 match，`wake_edge_receiver` 也從 R16 unmatched `192` 降到 incompatible owned `4`。
剩餘 blocker 是 `core_wall_loop_cap=60` 沒有 candidate owner，以及
`core_tip_receiver_outer=4` / `wake_edge_receiver=4` 仍 split 不相容。WO-006I preflight 現在
active blocker 是 `near_wall_hybrid_tet_prism_handoff_not_compatible`。

工程判讀：hybrid tet/prism 是目前最接近 mixed BL/core handoff 的方向，但還不是 CFD mesh。
R18 已把這個 residual 定位成兩個 loop-cap fan 和兩個 left-tip receiver cells；下一步要
R19 已證明 loop-cap owner pyramid basis 可 `60/60` match，下一步要修最後 8 個
wake/tip owned triangles 並寫入 mixed mesh；完成後才
能寫 merged mixed SU2 mesh、做 marker/y+ gate，再談 coarse/medium/fine SU2 ladder。

## 2026-05-14 WO-006R16 Axis-Agnostic Prism-Split Probe

`scripts/probe_wo006r16_axis_agnostic_prism_split.py` 擴大 R15 假設：每個 near-wall hexa
不只試單一 split 軸，而是三個 opposite-face split 軸與兩個對角線都試，逐 cell 選能 match
最多 core-interface triangles 的兩-prism representation。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r16_axis_agnostic_prism_split_probe/`。

實跑結果：R16 把 R15 的 `3166/5658` 提高到 `5274/5658`，而且
`bl_outer_interface=2048` 已可全數 match。剩餘 unmatched 是 `wake_edge_receiver=192`、
`core_outer_edge_receiver=128`、`core_wall_loop_cap=60`、`core_wake_outer_match=4`。WO-006I
preflight 現在會優先讀 R17；R16/R15/R14 只當 superseded diagnostic。

工程判讀：axis-agnostic prismization 是有用方向，但仍不能形成 conformal BL/core handoff。
剩下的是 wake/outer-edge/loop-cap ownership/tessellation 問題；下一步仍必須 shared interface
tessellation 或 boundary-driven near-wall remesh，之後才有 y+ probe 和 SU2 ladder 意義。

## 2026-05-14 WO-006R15 Prism-Split Handoff Compatibility Probe

`scripts/probe_wo006r15_prism_split_handoff_compatibility.py` 把 R14 的 handoff
triangle mismatch 往下拆一層：檢查「把每個 near-wall hexa cell 切成兩個 prism，並逐 cell
選最佳對角線」是否足以讓 BL/core interface conformal。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r15_prism_split_handoff_compatibility_probe/`。

實跑 Baseline A current-GO 幾何結果：near-wall/receiver candidate 有 `26,880` 個 cells，
其中 `2,638` 個 touch core-facing boundary；最佳 per-cell prism split 只 match
`3166 / 5658` 個 R13 core interface triangles。unmatched markers 仍包含
`bl_outer_interface=2048`、`wake_edge_receiver=192`、`core_outer_edge_receiver=128`、
`core_wake_outer_match=64`、`core_wall_loop_cap=60`。R16 已把這條擴展成三軸 split search，
因此 R15 現在是 superseded diagnostic，不是最新 active gate。

工程判讀：這不是 solver iteration 問題，也不是只換 hexa/prism diagonal 就能修。下一步必須讓
near-wall 與 core 共用同一個 interface tessellation，或用 boundary-driven near-wall remesh
重做 handoff；在這之前不能跑 medium/fine SU2 ladder，也不能解讀 CL/CD/Cm。

## 2026-05-14 WO-006R9 Triangulated Core Interface Probe

`scripts/probe_wo006r9_triangulated_core_interface.py` 把 R7 指到的 preserved-core
quad-to-pyramid 轉接問題改成 Baseline A 實跑證據：同一個 current GO owned BL block，
core inner boundary 仍 preserve 節點與 markers，但以 triangulated representation 交給 Gmsh
HXT tet-fill。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r9_triangulated_core_interface_probe/`。

實跑結果：core mesh `28,410` nodes / `6,005` volume elements，全部是 tetra（type `4`），
`pyramid=0`，non-positive SICN/SIGE/volume 都是 `0`，mesh quality gate 是 `pass`。因此 R7 的
bad preserved-quad pyramid family 已被 triangulated interface route 清掉。

工程判讀：這仍不是 BL/core CFD handoff。`bl_outer_interface` 有 `2048` faces match，但
`wake_cut=64`、`span_cap=62` core faces unmatched，BL block 端還有 `6272` 個非 wall boundary
faces 未 match，而且沒有 merged mixed SU2 mesh。因此 `GOAL_STATUS=INCOMPLETE`、
`CFD_STATUS=mesh_ladder_incomplete`；下一步要把 wake/span-cap receiver 或 envelope 變成真正
merged topology，不能直接跑 medium/fine SU2。

## 2026-05-14 WO-006 Force-Stability Window Gate Hardening

`scripts/run_wo006i_grid_convergence_campaign.py` 現在不只看 force stability summary
宣稱 `pass`，也會硬性要求 CL/CD/Cm stability window 至少覆蓋 `100` 個 iterations。
若外部或舊 artifact 只用短尾段（例如 25 rows）宣稱穩定，grid-convergence gate 會加入
`*_force_stability_window_too_short` blocker，即使 CL/CD/Cm spread 看起來小於 `1%`。

工程判讀：iteration 數不是收斂定義；100-iteration rolling force window 是最低可信數值穩定
證據。即使通過這條，`CD≈0.5-0.6` 仍會被 HPA main-wing CD-order sanity gate 擋下，因為
drag 量級應該是 `0.0XX`，不能把高阻力假穩定當 CFD 完成。

## 2026-05-14 WO-006S Sleeve-Mesh Hotspot Re-diagnosis

WO-006S 用既有 `scripts/diagnose_wo006k_bl_hotspots.py` 重判 WO-006R 的
`local_transition_subdiv8_thin12_g118` mesh。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r_subdiv8_hotspot_diagnosis/`。

結果：status 仍是 `blocked`，worst BL `minSICN=8.91e-06`，worst `minSIGE=0.00710`；
top 80 hotspots 全部在 aft/TE（`x/c≈0.99`），其中 6 個仍在 DAE31 ↔ CST tip
airfoil-transition band。這代表 local sleeve 只把 non-positive cells 清掉，沒有把 TE/wake
near-wall prism quality 拉到 CFD gate 所需的 `p01 minSICN >= 0.005`。

工程判讀：目前不能把 `subdiv8` 或 `subdiv16` 拿去跑 medium/fine SU2 當 CFD ladder。
下一個真正修復目標是 TE/wake/transition receiver topology 或 owned-BL/core envelope，而不是
增加 SU2 iteration、放寬 CD gate，或把 `CD≈0.5-0.6` 當成「已收斂」。

## 2026-05-14 WO-006T Global TE Stageback Runtime Probe

WO-006T 新增 `scripts/probe_wo006t_te_stageback_runtime.py`，把「全展向 trailing-edge
stageback 是否能修 WO-006R/S 的 aft/TE BL hotspot」變成 bounded runtime probe。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006t_te_stageback_runtime_probe/`。

實跑 `x/c >= 0.99`、`x_reference=max` 的兩個 cases：HXT (`mesh_algorithm3d=10`) 約
`15.1 s` 失敗，failure family 是 `stageback_hxt_requires_triangle_boundary_surfaces`
（raw Gmsh error: HXT only supports triangles）；non-HXT alg1 約 `15.1 s` 失敗，failure
family 是 `stageback_boundary_recovery_failed`。兩者 peak sampled RSS 都約 `110 MB`，
所以不是硬體/RAM limit，也沒有 BL quality gate candidate。

工程判讀：全展向 TE stageback 不是可直接升級的 CFD 修法。下一步應該實作 owned
TE/wake receiver 或 BL/core envelope，使 TE/wake/transition 拓樸先 watertight 且 quality
gate pass，再談 SU2 route smoke。

## 2026-05-14 WO-006U BL/Core Envelope Topology Probe

WO-006U 新增 `scripts/probe_wo006u_bl_core_envelope_topology.py`，不跑 Gmsh / SU2，
直接檢查 owned BL block 的 core-envelope topology。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006u_bl_core_envelope_topology_probe/`。

實跑結果：current core-interface surface 是 watertight（`0` bad edges），但 tempting
`full_non_wall_boundary` 不是 watertight，有 `124` 條 bad edges；這 `124` 條全部分類成
`candidate_open_edge_touches_wing_wall`，marker combo 是 `span_cap=60`、`wake_cut=64`。

工程判讀：R5 的 BL/core coupling 問題不是單純 Gmsh algorithm 或 timeout 問題。直接把
all non-wall BL faces 丟給 core mesh 會把仍接 physical wing wall 的 wake/span-cap edges
暴露成 open boundary。下一步應該先設計 owned TE/wake receiver/envelope，把 wall-touching
edge closure 定義清楚，再嘗試 core tetra / mixed SU2 handoff。

## 2026-05-14 WO-006V Wake Receiver Topology Probe

WO-006V 新增 `scripts/probe_wo006v_wake_receiver_topology.py`，把 TE/wake receiver
從口號變成可數的 topology candidate：建立 receiver cells 填住 upper/lower wake connector
gap，檢查它能 match 多少 BL wake-cut faces 與 core outer wake faces。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006v_wake_receiver_topology_probe/`。

實跑結果：receiver 建出 `768` 個 cells，可 internalize `1536 / 1600` 個 BL wake-cut
faces，也 match `32 / 32` 個 core wake-cut faces；但仍剩 `64` 個 BL wake-cut faces，
且這 `64` 個全部 touch `wing_wall`。receiver 自己也留下 `32` 個 TE-base faces。

工程判讀：wake receiver 是正確修路方向，因為它把大部分 layer-wise wake-cut side faces
變成可 internalize 的 matching interface；但 TE-base ownership 還沒定義清楚，所以仍不能
宣稱 BL/core handoff ready，更不能跑 medium/fine SU2 ladder 或解讀 CL/CD/Cm。

## 2026-05-14 WO-006W TE-Base Wake Pairing Probe

WO-006W 新增 `scripts/probe_wo006w_te_base_pairing.py`，專門檢查 WO-006V 剩下的
TE-base wake-cut faces 是不是 sharp trailing-edge 的幾何重合 wake seam pair。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006w_te_base_pairing_probe/`。

實跑結果：`64` 個 TE-base faces 形成 `32` 組 coincident pairs，`unpaired=0`；wake
receiver 的 `32` 個 receiver-base faces 全部 degenerate，`max_receiver_base_area_m2=0.0`。

工程判讀：這代表 TE-base blocker 可以走 explicit seam stitching / removal，而不是把它當
新的 physical wall 或 medium/fine SU2 boundary。它仍不是 BL/core handoff，也不是 CFD
ladder；下一步要把這個 pairing candidate 實作成可審核的 stitched topology，再重跑
BL/core merge gate。

## 2026-05-14 WO-006X Stitched Wake Handoff Gate

WO-006X 新增 `scripts/probe_wo006x_stitched_wake_handoff_gate.py`，把 WO-006V/WO-006W
合成一個 wake ownership accounting gate：BL wake-cut faces 必須不是被 receiver match，
就是被 explicit sharp-TE seam stitch account。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006x_stitched_wake_handoff_gate/`。

實跑結果：`1600` 個 BL wake-cut faces 中，`1536` 個由 wake receiver match，`64` 個
由 TE-base sharp seam stitch account；`remaining_unowned_bl_wake_cut_face_count=0`。
core wake-cut 也 `32 / 32` match。

工程判讀：wake ownership 這一段可以進入實作 stitched topology 的下一步；但這還不是
完整 BL/core handoff，因為 span-cap ownership 仍是 `pending`，merged mesh quality 與 SU2
readability 也未過 gate。因此仍不能跑 medium/fine SU2 ladder 或解讀 CL/CD/Cm。

## 2026-05-14 WO-006Y Span-Cap Ownership Probe

WO-006Y 新增 `scripts/probe_wo006y_span_cap_ownership.py`，專門檢查 wake accounting
通過後剩下的 span-cap ownership。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006y_span_cap_ownership_probe/`。

實跑結果：owned BL block 有 `1536` 個 BL span-cap faces，core interface 只有 `62` 個
triangulated span-cap faces，native matched BL span-cap faces 是 `0`。其中 `60` 個 BL
span-cap faces touch `wing_wall`，`64` 個 touch `bl_outer_interface`，`96` 個 touch
`wake_cut`。

工程判讀：wake ownership 已可 accounting，但 span-cap 不能直接丟給 SU2 當未定義 boundary。
下一步需要明確 tip/span-cap ownership policy 或 receiver topology；在這之前仍不能宣稱
BL/core handoff ready，不能跑 medium/fine SU2 ladder。

## 2026-05-14 WO-006Z BL Physical Wall Surface Basis

WO-006Z 新增 `build_boundary_layer_wall_surface(...)` 與
`scripts/probe_wo006z_bl_physical_wall_surface.py`，把 BL block 裡真正可作 physical wall
的 layer-0 wing surface 獨立抽出：既有 `wing_wall` spanwise faces 會保留；finite TE
會新增非零面積 TE-base wall；sharp TE 則只做 duplicate-node seam stitch，不產生零面積
wall face；terminal tip cap 只用 layer-0 wall nodes 三角化。

Baseline A current geometry artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006z_bl_physical_wall_surface_probe/`。
實跑 `points_per_side=16`、`spanwise_subdivisions=2`、BL `layer_count=24` 時，physical
wall surface 是 watertight，`wing_wall=1016`，其中 source spanwise wall faces `960`、
tip-cap triangles `56`、sharp-TE seam pairs `33`、finite TE-base wall faces `0`。

工程判讀：這是把「物理壁面 marker 從 BL/core/span-cap/wake 混雜面裡分離」的一步，
不是 BL/core handoff ready。下一步仍要把 wake receiver / span-cap ownership 實作成
conformal merge，並重跑 mesh quality、marker match、near-wall/y+ gate 後，才可以啟動
medium/fine SU2 ladder。

## 2026-05-14 WO-006AA Tip Receiver Topology Probe

WO-006AA 新增 `scripts/probe_wo006aa_tip_receiver_topology.py`，把 WO-006Y 的
span-cap blocker 往可實作 topology 推一步：建立 virtual tip receiver accounting layer，
檢查它是否能 match 每一個 BL span-cap face，並把剩餘 side boundaries 分成
physical-wall edge、wake edge、core outer edge。

Baseline A current geometry artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006aa_tip_receiver_topology_probe/`。
實跑 `points_per_side=16`、`spanwise_subdivisions=2` 時，tip receiver candidate 可 account
`1536 / 1536` 個 BL span-cap faces，remaining `0`；side boundary role counts 是
`physical_wall_edge_receiver=60`、`wake_edge_receiver=100`、`core_outer_edge_receiver=64`。

工程判讀：span-cap ownership 已從「完全 unmatched」變成「有 virtual receiver topology
可以 account」，但這還不是 final BL/core handoff。下一步必須把這些 receiver side
boundaries 真正接到 physical wall、wake receiver、core outer interface，並通過 merged mesh
quality / SU2 marker readability；仍不能跑 medium/fine CFD ladder。

## 2026-05-14 WO-006AB BL/Core Topology Accounting Gate

WO-006AB 新增 `scripts/probe_wo006ab_bl_core_topology_accounting_gate.py`，把 WO-006Z
physical wall、WO-006X stitched wake、WO-006AA tip receiver、以及 native
`bl_outer_interface` match 合成一個 topology accounting gate。

Baseline A current geometry artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006ab_bl_core_topology_accounting_gate/`。
實跑結果：physical wall `watertight`；wake accounting pass；tip receiver accounting pass；
outer interface `1024 / 1024` match；整體 verdict 是
`topology_accounting_ready_not_handoff`。

工程判讀：這是第一次把 BL/core ownership accounting 串成完整 pre-mesh contract，但它仍不是
handoff。明確 blockers 是 receiver geometry 尚未 materialize、沒有 final merged mesh、沒有
merged mesh quality gate、沒有 SU2 marker/readability gate、沒有 near-wall/y+ postprocess、也沒有
solver ladder。因此下一步才是把 virtual receiver 實作成真幾何/mesh，不能直接跑 medium/fine CFD。

## 2026-05-14 WO-006AC Receiver Geometry Materialization Probe

WO-006AC 新增 `scripts/probe_wo006ac_receiver_geometry_materialization.py`，把 WO-006AA
的 virtual tip receiver 轉成明確座標與 volume cells，並把 WO-006AB 的
`receiver_geometry_not_materialized` blocker 改成可審核的 geometry/materialization status。

Baseline A current geometry artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006ac_receiver_geometry_materialization_probe/`。
實跑 `points_per_side=16`、`spanwise_subdivisions=2` 時，receiver geometry status 是
`tip_receiver_geometry_materialized_quality_pass`：`1536` 個 receiver cells、`1650` 個
virtual nodes、receiver thickness `0.03617304985338918 m`、min receiver volume
`1.1070816511539737e-08 m^3`、non-positive volume `0`、`external_shape_changed=false`。

工程判讀：virtual tip receiver 已 materialize 成正體積幾何，span-cap receiver geometry
blocker 已解掉；但這仍不是 final BL/core handoff。剩餘 blockers 是 final merged mesh missing、
merged mesh quality not run、SU2 marker/readability not run、near-wall/y+ not postprocessed、
solver ladder not run；因此仍不能跑 medium/fine SU2 或解讀 CL/CD/Cm。

## 2026-05-14 WO-006R10 Near-Wall Core Closure Probe

WO-006R10 新增 `scripts/probe_wo006r10_near_wall_core_closure.py`，接在 WO-006AD
sharp-TE seam repair 後，檢查 watertight near-wall candidate 是否能安全升級成
core/farfield mesh 的 inner interface。這仍是 topology/policy evidence，不是 Gmsh/SU2
handoff，也不是 CFD 係數證據。

Baseline A current geometry artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r10_near_wall_core_closure_probe/`。
實跑 `points_per_side=16`、`spanwise_subdivisions=2` 得到
`near_wall_core_interface_closure_blocked`：full near-wall boundary 是 `watertight`
且 `bad_edge_count=0`，但排除 physical-wall roles 後的 core-facing subset 仍是
`not_watertight`，有 `64` 條 bad edges（role touch：`core_tip_receiver_outer=60`、
`wake_edge_receiver=4`）。同時 full-shell policy 是 `forbidden`，因為 full shell 含
`wing_wall=960` 與 `physical_wall_edge_receiver=60`，不能借 physical wall 來補 core
interface。R10 edge-gap audit 現在把這 `64` 條邊全部配對到
`physical_wall_edge_receiver`：`core_tip_receiver_outer + physical_wall_edge_receiver`
有 `60` 條，`wake_edge_receiver + physical_wall_edge_receiver` 有 `4` 條，
`unexplained_bad_edge_count=0`。

工程判讀：WO-006AD 已修好 near-wall external surface closure，但 WO-006R10 證明下一步
不是把 full shell 直接丟給 Gmsh，而是要 materialize 一個真正 core-facing 的 closure，
不能改 Baseline A external wall shape，也不能把 physical wall 誤標成 core interface。剩餘
blockers：core-facing surface not watertight、full shell contains physical wall roles、
core interface not materialized、core/farfield mesh not generated、merged mesh quality not
run、SU2 marker/readability not run、near-wall/y+ not postprocessed、solver ladder not run。

## 2026-05-14 WO-006AD Near-Wall Merged Volume Candidate Probe

WO-006AD 新增 `scripts/probe_wo006ad_near_wall_merged_volume_candidate.py`，把 owned BL
block、wake receiver、sharp-TE stitch accounting、以及 materialized tip receiver 合成同一個
near-wall volume candidate accounting object。它仍不是 Gmsh/SU2 handoff，只是把「原始
BL span-cap / wake-cut 是否仍裸露成 solver boundary」這件事變成可檢查 artifact。

Baseline A current geometry artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006ad_near_wall_merged_volume_candidate_probe/`。
實跑 `points_per_side=16`、`spanwise_subdivisions=2` 得到
`near_wall_volume_candidate_ready_core_mesh_pending`：`28875` nodes、`26880` volume cells
（owned BL `24576`、wake receiver `768`、tip receiver `1536`），original exposed
span-cap `0`、original exposed wake-cut `0`、stitched TE-base faces `64`、removed
degenerate receiver-base faces `32`、non-positive receiver volumes `0`。WO-006AD repair
新增 layer-0 sharp-TE wall/wake seam stitch：`remapped_node_count=66`，external boundary
topology 現在是 `watertight`、`bad_edge_count=0`。

工程判讀：這解掉原始 BL `span_cap` / `wake_cut` 裸露問題，也解掉 AD 觀察到的
near-wall external boundary open-edge blocker。剩餘 blockers 是 core/farfield mesh not
generated、merged mesh quality not run、SU2 marker/readability not run、near-wall/y+ not
postprocessed、solver ladder not run；所以下一步應該是從這個 watertight near-wall
candidate 產生 core/farfield mesh 與 mixed SU2 handoff，而不是直接跑 medium/fine SU2
或解讀 CL/CD/Cm。

## 2026-05-14 WO-006R Local Transition Sleeve BL Probe

WO-006R 新增 `scripts/probe_wo006r_local_transition_sleeve_bl_quality.py`，只在 DAE31 ↔
CST transition interval 插入線性 intermediate stations（外形仍是同一個 ruled surface，
`external_shape_changed=false`），檢查 local receiver/sleeve 方向能不能讓 Gmsh BL quality
過 gate。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r_local_transition_sleeve_bl_quality_probe/`。

實跑 `transition_subdivisions=4/8/16`：
`subdiv4` 仍有 `6` 個 non-positive BL SICN；`subdiv8` 和 `subdiv16` 已把
non-positive BL SICN 清成 `0`，但 `BL p01 minSICN` 仍只有約 `7.02e-05` / `6.74e-05`，
沒有接近目前 CFD gate 的 `0.005`。三個 cases 都不是 BL quality gate pass candidate。

工程判讀：local transition sleeve 是正確方向的一部分，因為它消掉了 non-positive cells；
但單靠線性插站不夠。下一步需要真正的 near-wall receiver surface / local airfoil-transition
smoothing 或等效 topology repair，讓 p01 SICN 提升兩個數量級以上，再談 SU2 route smoke。

## 2026-05-14 WO-006Q Transition Normal-Jump Probe

WO-006Q 新增 `scripts/probe_wo006q_transition_normal_jump.py`，用 current Baseline A
geometry source 直接量化相鄰 station 的 airfoil wall normal / aft shape jump，不跑 Gmsh
也不跑 SU2。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006q_transition_normal_jump_probe/`。

實跑結果：DAE31 ↔ CST tip airfoil transition interval（`|y|=12.0163` 到
`14.076237 m`）在 aft `x/c >= 0.75` 有 `45.57 deg` max normal jump，aft normalized
shape delta `0.0543`，超過 WO-006Q blocker threshold（`20 deg` / `0.03`）。

工程判讀：這和 WO-006K hotspot 的 `y≈12.36-13.39 m`、aft/TE 位置對上。下一步應該做
receiver/sleeve 或 local airfoil-transition smoothing 的 near-wall topology repair；在這個
normal jump 沒被處理前，硬跑 BL medium/fine 只會把錯誤條件放大。

## 2026-05-14 WO-006P BL Span-Refinement Runtime Probe

WO-006P 新增 `scripts/probe_wo006p_bl_span_refinement_runtime.py`，把「靠提高
spanwise subdivision 修 DAE31 -> CST tip transition BL hotspot」這個假設改成有 timeout
與 RSS trace 的 bounded probe。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006p_bl_span_refinement_runtime_probe/`。

實跑 `pps16_span8_thin12_g118` 與 `pps16_span16_thin12_g118`，每個 case timeout `240 s`。
兩者都 timeout，peak sampled RSS 只有約 `205 MB` / `227 MB`，所以這不是 RAM hard
limit，也沒有 BL quality gate pass candidate。

工程判讀：spanwise refinement 到 span8/span16 不是便宜修法，不能拿來當 medium/fine
CFD ladder 起點。下一步仍是 transition-band topology / near-wall shape 修復，而不是硬跑
SU2 iteration 或把 runtime timeout 說成 16 GB memory limit。

## 2026-05-14 WO-006O Force-Stability Window Tightening

WO-006O 把 WO-006I history stability 判讀從短尾段 `25` rows 改成 `100` iteration
force window，CL/CD relative spread 門檻收緊到 `1%`，Cm 仍用 `0.005` absolute spread。
這比較接近 steady CFD 的工程判讀：不需要盲目跑到固定 1000 iteration，但至少要證明最後
100 iteration 的 force history 沒有明顯漂移。

工程判讀：這只是「數值穩定」條件，不是物理正確保證。若 `CD` 穩在 `0.5-0.6`，
WO-006J 的 CD-order sanity gate 仍會擋掉，因為 Baseline A main-wing drag 量級應該是
`0.0XX`；穩定地錯不能升格成 CFD completion。

## 2026-05-14 WO-006N Stageback Topology Setup Gate

WO-006N 把 WO-006M direct stageback probe artifact 接進
`scripts/run_wo006i_grid_convergence_campaign.py` 的 CFD setup gate。campaign 現在會讀
`wo006m_face_coherent_stageback_mesh_probe/summary.json` 與
`wo006m_narrow_stageback_mesh_probe/summary.json`；只要看到 Gmsh `PLC Error: A segment and a
facet intersect` 類型的 direct no-BL-hole stageback 失敗，就會加入
`direct_stageback_topology_plc_segment_facet` blocker。

工程判讀：這個 gate 是為了防止後續 agent 把已知壞 topology 拿去硬跑 medium/fine。
目前 direct stageback route 的正確定位是 BL/core topology diagnosis；修法不是多跑 SU2
iteration，而是 receiver/sleeve/staged transition topology 先成立，再重新產生同一 Baseline A
外形、同一 physics setup 的 CFD ladder。

## 2026-05-14 WO-006M Face-Coherent Stageback + Side-Filter Probe

WO-006M 修正 WO-006L stageback selector 的一個 topology 問題：原本 triangle-level
排除會把同一個 source face 切成半個有 BL、半個 no-BL，現在改成 face-coherent
排除；同時 BL side surfaces 只保留接觸 excluded-wall boundary curves 的 surfaces，
避免把 source-source seam 的 side walls 也塞進 core inner loop。Gmsh failure 現在會
輸出 stageback surface-role diagnostic。

bounded probe 顯示這個修正有縮小問題，但沒有讓 current-GO BL mesh 變成 CFD-grade。
`x/c>=0.998, |y|=12.0-14.2 m` 從 side-vs-side overlap 變成
`stageback_plc_segment_facet_intersection`；更窄的 `|y|=12.3-13.0 m` 也同樣是 PLC
segment/facet。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006m_face_coherent_stageback_mesh_probe/`
與 `wo006m_narrow_stageback_mesh_probe/`。

工程判讀：直接挖 no-BL hole 不是可用修法；它需要真正的 receiver/sleeve/staged
transition topology。舊 span8 BL meshes 雖然沒有 non-positive BL elements，但用目前 gate
重判仍 fail：`wing005` 11.28M cells 的 `BL p01 minSICN=0.00219 < 0.005`，不能拿來當
medium/fine CFD 完成。

## 2026-05-14 WO-006L Local TE Stageback Selector

WO-006L 在 mesh-native Gmsh BL writer 補上 experimental local TE stageback selector：
wall surface records 現在會用 spanwise local chord 記錄 `centroid/min/max x/c` 與
`abs y`，並可用 `boundary_layer_exclusion_x_reference="max"` 加上 `abs_y` band
只鎖定 DAE31 -> CST tip transition 的 aft/TE hotspot。這沒有改 Baseline A 外形。

selector-only probe 顯示 pps16/span4 current-GO 幾何共有 `3900` 個 wall surface
records，其中 `540` 個落在 `|y|=12.0-14.2 m` transition band；用
`max x/c >= 0.995` 只會排除該 band 的 `52` 個 aft/TE faces（`0.998` 則是 `36`
個）。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006l_te_stageback_selector_probe/`。

工程判讀：這只是把 BL 修復工具從 global-x 誤判推進到 local-chord hotspot targeting。
直接套進 current-GO Gmsh 3D localized stageback probe 跑超過 6 分鐘仍沒有 artifact
輸出，觀察到 CPU 約 `100%`、RSS 約 `865 MB`，所以不是 memory hard limit，也不是 CFD
evidence。現在仍不能跑或宣稱 medium/fine SU2 ladder；下一步是 topology-preserving
transition/interface closure，而不是硬跑 solver iteration。

## 2026-05-14 WO-006K SU2 Nondim + BL Quality Gate Repair

WO-006K 修正 mesh-native SU2 incompressible RANS config：`INC_NONDIM` 改用
`INITIAL_VALUES`，避免把係數正規化落在 `DIMENSIONAL=1 Pa` 這類不適合 aerodynamic
coefficient 比較的 setup。`scripts/run_wo006i_grid_convergence_campaign.py` 的 setup gate
也會拒絕非 `INITIAL_VALUES` 的 WO-006 CFD ladder。

工程判讀：這個 bug 是真問題，但不是 WO-006J `CD≈0.5-0.6` 的唯一來源。用修正後 config
重跑 no-BL route smoke 仍得到 `CD≈0.439`（alpha 5 deg）與 `CD≈0.291`（alpha 0 deg）；
用同一 large-domain BL mesh 重跑 RANS/SA force-breakdown probe 也仍是 `CD≈0.571`，
其中 pressure 約 `0.401`、friction 約 `0.170`。這個 friction 量級對 HPA 主翼不合理，
不能靠更多 iteration 或 medium/fine ladder 自動變成可信結果。

BL mesh quality gate 也已補強：boundary-layer `p01 minSICN < 0.005` 現在是 blocker，
不是 warning。舊 larger-domain BL sanity mesh 用新 gate 判讀會 fail：
`p01_min_sicn=1.47e-4`、`min_sicn=8.91e-6`。低成本 BL 參數 probe 顯示把 BL 做薄、
減層、或切到 `max_min_angle` surface triangulation 仍有 non-positive SICN/SIGE；
spanwise subdivision 從 1 提到 4 會改善最壞負 SICN，但仍 fail。hotspot 位於
`y≈±12.36, ±12.87, ±13.39 m`、`x≈0.81-0.85 m`，也就是 `y=12.016 m`
DAE31 到 `y=14.076 m` CST tip airfoil 的 transition band。下一步仍是修
TE/tip/transition 附近的近壁幾何/BL prism shape，而不是硬跑 coarse/medium/fine。
`scripts/diagnose_wo006k_bl_hotspots.py` 可把 Gmsh BL element quality hotspots 映射回
section table；目前 artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006k_bl_hotspot_diagnosis/`，
status 是 `blocked`。

## 2026-05-14 WO-006J CD-Order Sanity Gate

WO-006J 後續 BL/no-slip ladder 雖然已經不是 no-BL route，且 `wing_wall` / `farfield`
marker/config audit pass，但 0.48M 到 2.51M 級 rungs 的 `CD≈0.61`，4.53M partial rung
到 772 iterations 仍在 `CD≈0.593`。這個 force history 可以當 high-drag diagnosis，
不能當 CFD completion：Baseline A main-wing drag 應是 `0.0XX` 量級，穩在 `0.5-0.6`
代表 setup/domain/geometry/solver 還有錯。

工程判讀：grid-convergence gate 現在會拒絕 `CD > 0.15` 的 HPA main-wing rung，
即使 CL/CD/Cm 尾段看似穩定也不能選成 stable CFD pair。BL stability ladder 的預設
farfield 也從 route-smoke 的 `2c/4c` 改成 `20c/40c`（lateral/vertical `8c`），
但 larger-domain BL sanity 沒有修好 high-CD：`CD≈0.642`。`scripts/diagnose_wo006j_drag_source.py`
可重跑 WO-006J force-breakdown / surface-pressure localization；目前診斷顯示 Euler/slip-wall
probe 的 `CD≈0.298` 是 pressure-only，RANS/BL 的 `CD≈0.642` 由 pressure `≈0.492`
加 friction `≈0.150` 組成。`scripts/probe_wo006j_numerics_sensitivity.py` 也已把
同一 large-domain Euler mesh 拿來測 FDS/MUSCL：原 source config 的確有
`FDS + MUSCL_FLOW=NO` 的低階疑點，但無限制 MUSCL 會在 12 iter 內發散；保守
`FDS + MUSCL + VENKATAKRISHNAN`、`CFL=0.02` 跑滿 300 iter 仍是 `CD=0.447702`。
因此問題不是只靠多跑 iteration、單純放大 farfield，或只打開 MUSCL 就會好；必須先修
pressure/geometry/numerics artifact 與 BL friction setup，再重跑同幾何、同 physics 的
coarse/medium/fine ladder。

## 2026-05-13 WO-006I CFD Setup Gate Reset

WO-006I 已改成先擋 setup，而不是繼續把 no-BL route 往大網格跑。新的 preflight artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006i_setup_preflight_reset/`：
`GOAL_STATUS=INCOMPLETE`、`CFD_STATUS=mesh_ladder_incomplete`，並且 `blocked_before_solver`。

工程判讀：先前 `wo006i_grid_convergence_campaign/` 裡的 `0.49M`、`1.61M`、`3.05M`、`3.63M`
no-BL RANS/SA ladder 只能當已知錯誤 setup 的 diagnostic/quarantine evidence。它沒有
conformal BL/core handoff、沒有 postprocessed y+，force window 也不穩；所以即使有 finite
`CL/CD/Cm` history，也不得宣稱 low-confidence CFD、grid convergence、drag/power truth、
Baseline A reopen evidence、RFQ/procurement truth 或 final aircraft sign-off。

## 2026-05-14 WO-006R11 Core-Facing Loop Closure Probe

WO-006R11 新增 `scripts/probe_wo006r11_core_facing_loop_closure.py`，接在 R10
wall-edge gap audit 後，把 core-facing open edges materialize 成 `core_wall_loop_cap`
候選 surface。Baseline A artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r11_core_facing_loop_closure_probe/`。
實跑 R10 的 `64` 條 open edges 形成左右兩個 `32`-node loops；R11 補 `64` 個 cap
triangles 後，post-cap topology 是 `watertight`、`bad_edge_count=0`，且 cap face
non-positive area 是 `0`。

工程判讀：這把 R10 的 wall-edge topology blocker 推進到「可做 core/farfield mesh probe」，
但還不是 BL/core/SU2 handoff。剩餘 blockers 是 core/farfield mesh not generated、merged
mesh quality not run、SU2 marker/readability not run、near-wall/y+ not postprocessed、
solver ladder not run。

後續 WO-006 CFD 若要繼續跑，必須先過 `baseline_a_wall_resolved_bl_preflight_gate_v1`：
no-slip wall BC、farfield marker、conformal BL/core handoff、near-wall/y+ evidence、同幾何
coarse/medium/fine ladder 與 residual/force stability 都要在同一 setup 下成立。若只是要重放
no-BL debug，必須明確使用 diagnostic flag，且結果仍不能完成 CFD goal。這個 preflight gate
現在優先讀 WO-006R12 loop-cap core-mesh artifact；R12 已把最新 blocker 定位成
`near_wall_core_mesh_geometry_blocked`，也就是 tip/wake loop-cap seam 的 geometric
self-intersection，而不是 R10 wall-edge dependency 或單純 core mesh 尚未嘗試。

## 2026-05-14 WO-006R12 Loop-Cap Core Mesh Probe

WO-006R12 新增 `scripts/probe_wo006r12_loop_cap_core_mesh_probe.py`，把 R11 的
`core_wall_loop_cap` surface 直接交給 generic inner-surface core tet writer，不再回退到舊的
`build_boundary_layer_core_interface_surface(block)`。Baseline A artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r12_loop_cap_core_mesh_probe/`。

實跑結果仍是 `loop_cap_core_mesh_probe_blocked`：Gmsh HXT core fill 約 `96.6 s` 後失敗，
log 顯示 duplicate point filtering、missing facets recovery，並輸出 exactly self-intersecting
facets。R12 的幾何 audit 進一步定位：R11 surface 有 `70` 組 exact duplicate coordinates；
若按座標 weld，會產生 `8` 條 non-manifold bad edges，sample 集中在
`wake_edge_receiver` / `core_wall_loop_cap` / `core_tip_receiver_outer` 的 tip/wake loop-cap seam。

工程判讀：R11 的 index-space watertight 不等於 PLC/geometric validity。現在不能跑 SU2；
下一步要修 sharp-TE/tip/wake loop-cap 幾何重合與 non-manifold seam，讓 core/farfield mesh
quality/marker gate 真正 pass，再談 merged BL/core handoff、y+ 與 solver ladder。

## 2026-05-14 WO-006R13 Loop-Cap Geometric Seam Repair

WO-006R13 新增 `scripts/probe_wo006r13_loop_cap_geometric_seam_repair.py`，把 R12 的
tip/wake loop-cap seam blocker 變成最小幾何修復：exact duplicate coordinates weld，並移除
weld 後同 marker / 同 node set 的重合 seam faces。Baseline A artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r13_loop_cap_geometric_seam_repair_probe/`。

實跑結果：原 R11/R12 surface `28,877` vertices / `2,868` faces，含 `70` 組 exact duplicate
coordinates；R13 修後是 `28,807` vertices / `2,860` faces，drop `8` 張 duplicate seam faces，
post-repair duplicate groups `0`、welded bad edges `0`。Gmsh HXT core fill 成功，core mesh
`29,993` nodes / `9,677` tetra cells，SU2 boundary ownership `pass`，non-positive
SICN/SIGE/volume 都是 `0`。但 mesh quality 仍有 `very_low_min_gamma`、`very_low_min_sicn`、
`low_p01_gamma` warnings。

工程判讀：R13 把 core/farfield mesh probe 推過了，但仍不是 CFD。R14 handoff audit 進一步
確認 R13 core surface 與 near-wall volume 多數 polygon 對得上（`2800/2860`），但 active
triangulated core boundary 只有 `1808/5658` triangles conformal，且 `core_wall_loop_cap`
有 `60` 張 polygon 沒有 near-wall owner。R15 先證明單軸逐 cell 兩-prism split 只能 match
`3166/5658` core triangles；R16 三軸 split 提升到 `5274/5658`；R17 hybrid tet/prism 再提升到
`5590/5658`，但 `core_wall_loop_cap=60` 仍沒有 candidate owner，另有 `wake_edge_receiver=4`
和 `core_tip_receiver_outer=4` split 不相容。因此 WO-006I preflight 現在把 active blocker
定位成 `near_wall_hybrid_tet_prism_handoff_not_compatible`；舊 direct-stageback PLC failure
只保留為 superseded diagnostic。R18 進一步把 residual 定位成兩個 tip-side loop-cap fans
和兩個 `tip_receiver/left_tip` cells (`26110`, `26111`)；R19 證明 loop-cap owner
pyramids 可 `60/60` match 且 owner volumes 全為正。下一步是
`repair_left_tip_receiver_shared_tessellation_then_write_loop_cap_owner_pyramid_mixed_mesh`，
再做 y+ probe 和 solver ladder。

## 2026-05-13 WO-006J Faceted BL Setup Probe

WO-006J 針對 current-GO faceted Gmsh BL route 補上 `surface_triangulation_policy`，預設使用
`shorter_diagonal`。這沿用先前 DAE31 transition 坑的修法，沒有改 Baseline A 外形。低成本
current-GO BL probe 顯示：fixed diagonal 會產生 `93` 個 non-positive BL volumes；改成
shorter diagonal 後 non-positive volume 清為 `0`，但仍有 `10` 個負 SICN/SIGE prism，位置對稱
集中在 `y≈±13.88 m`、`x≈0.790 m` 的 DAE31 -> CST tip airfoil transition aft/TE 附近。

工程判讀：這是 BL setup repair progress，不是 CFD result。它證明接下來要修的是 transition
surface / TE local BL prism shape；單純改 BL 總厚度或把 pps32/span2 硬開大不是答案，後者又回到
已知 `Unknown curve -1550` 拓撲坑。

## 2026-05-13 WO-006 Current-GO CFD Completion Evidence

Current-GO main-wing no-BL mesh-native CFD completion case 已產出，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006_current_go_cfd_completion/`。
Completion gate 是 `pass`：重新從 `avl_parity/current_avl_compromise_conservative_closed`
section table 產生 full-span mesh，保留 `98.5 kg` mass authority、`34.332286 m` full span /
`17.166143 m` half span，mesh 有 `490,116` tets、`wing_wall` / `farfield` marker audit pass、
no negative / zero / inverted volume gate pass，SU2 跑完 `159` iterations 並寫出 finite
force history（`CL=1.106421874`、`CD=0.4752310368`、residuals finite、no NaN/Inf）。

工程判讀：這讓 Baseline A current-GO main-wing CFD route 有了可追溯的 mesh/config/history
force evidence，不再只是 prepared/smoke/blocker package。但它是 no-BL RANS route-level
evidence，`CD` 明顯偏高，不能升格成 BL/y+ viscous drag calibration、power truth、
mesh-converged SU2 aero model、Baseline A reopen evidence、RFQ/procurement truth 或 final
aircraft sign-off。BL/core route 仍需另外修 conformal topology、near-wall/y+ 與 grid V&V。

## 2026-05-13 WO-006H Reopened CFD Campaign

WO-006H 已重新打開並補做 serious local CFD/mesh campaign，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_reopened_cfd_campaign/`。
接受 verdict 是 `su2_local_hard_limit_proven_with_executable_hpc_case`。

工程判讀：這不是 Baseline A SU2 aerodynamic result。本機 no-BL HXT control 可到
`3,790,657` cells、`675,820` nodes，marker / quality gate 通過；但這仍是 no-BL
resource / marker / sign-control evidence，不是 viscous HPA drag truth。更細 rung 不是硬體
記憶體牆：`h=0.05` HXT 在約 `1.65 s` 失敗、`h=0.04` Delaunay 在約 `8.43 s` 失敗且 peak
memory 低，錯誤分別是 `HXT 3D mesh failed` 與 boundary overlapping facets。BL/core 方向也
沒有可用 handoff：full BL boundary preserved-core probe 跑約 `325 s` 後以 PLC segment/facet
intersection 失敗；preserved-interface Alg1 mesh 可完成，但有 `173` non-positive volumes、
`158` unmatched core interface faces 與 `4672` unmatched BL boundary faces。因此目前沒有
physically credible 或 low-confidence SU2 CL/CD/Cm、沒有 postprocessed y+、沒有
mesh-sensitivity-controlled viscous result。

可交付的是 executable HPC package
`wo006h_reopened_cfd_campaign/hpc_executable_case/`。它針對缺口重跑 `h=0.05` / `h=0.04`
HXT、`h=0.04` Delaunay，以及 preserved-interface BL/core routes；不是只重跑已成功的小一點
no-BL mesh。

## 2026-05-13 WO-006G SU2 CFD V&V Reset

WO-006G 已把 Baseline A main-wing SU2 線升級成工具鏈 escalation verdict，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006g_su2_toolchain_escalation/`。
Allowed verdict 是 `su2_toolchain_escalation_required_after_exhaustive_failure`。

工程判讀：目前沒有 physically credible 或 low-confidence SU2 aerodynamic result。這不是因為單一
小網格或單一 solver knob 失敗，而是因為 current OpenVSP geometry 不是乾淨 watertight CFD solid，
current BL/core topology 還沒有 conformal / quality-passing final mesh，現有 no-BL / multizone
coefficients 沒有 force-stable、wall-resolved、transition-aware、grid-independent evidence。後續若要
可信 SU2，必須先升級到 CFD-grade geometry cleanup、BL-resolved mesh family、足夠 compute
resource，以及 low-Re transition / grid-convergence V&V workflow；不能再把 10-iteration smoke、
no-BL drag、negative-drag Euler window 或 10k/100k/1M 級 debug mesh 當 aero calibration。

## 2026-05-13 Bounded WO-006 Data-Authority Gate

Baseline A data-authority 已恢復到足以讓 **WO-006 bounded SU2 aero calibration** 往下走；
這不是 release-ready、RFQ/procurement-ready 或 final aircraft sign-off。

WO-006 bounded current-pathfinder smoke 已完成第一輪，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/`。Verdict 是
`su2_baseline_needs_fix`：current pathfinder VSP3 provider 可 materialize，但
default bounded mesh 在 Gmsh 3D volume insertion timeout，coarse sensitivity 則卡在
boundary parametrization topology；沒有 current-pathfinder `mesh_handoff.v1`，因此沒有可用的
SU2 CL/CD/CDi/profile-drag delta。這是 SU2 route repair evidence，不是 Baseline A reopen、
release truth、RFQ/procurement truth 或 final aircraft sign-off。

WO-006R1 已新增 current GO mesh-native CFD bridge，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r1_go_cfd_bridge/`。
Verdict 是 `wo006r1_go_cfd_bridge_smoke_ready`：用 current production-inspection
`section_table.csv` + `airfoils/*.dat` 建出 marker-owned indexed wing/farfield surface，
產生 coarse HXT no-BL `mesh_handoff.v1`、SU2 case，並跑完 3-iteration solver readability
smoke。這只代表 current Baseline A 已有 repeatable mesh/SU2 smoke route；mesh 只有約
2.9k volume elements、無 BL/y+，且 smoke CD 為負，所以仍不能拿來做 CL/CD/CDi/profile-drag
calibration、drag/power reopen、release truth、RFQ/procurement truth 或 final aircraft sign-off。

WO-006R2 CFD recovery campaign 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign/`。
Verdict 是 `wo006r2_current_geometry_adapter_blocker_isolated`：改用 no-touch
`avl_parity/current_avl_compromise_conservative_closed` geometry，並重放舊 serious mesh-native
BL/HXT route；coarse no-BL adapter control 可寫出 marker-owned mesh，但 BL route、coarser
BL probe、high-mesh no-BL control 都在 Gmsh HXT PLC / surface-topology intersection 擋住。
因此目前沒有可解讀 SU2 coefficient，也沒有 Baseline A reopen evidence；接續修復仍必須讓
data-authority checker 作為 prerequisite，並且不得改外形來繞過 topology blocker。

WO-006R3 surface-topology repair campaign 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/`。
Verdict 是 `wo006r3_high_mesh_handoff_ready`：保留 current GO authority data，修正 DAE31
near-TE airfoil-loop ordering，並把 shorter panel diagonalization 限定在 no-BL faceted SU2
handoff route。現在 current-GO no-BL `wing_h=0.12 m` mesh 可產生 `936,017` volume cells、
marker audit pass，且 SU2 readability smoke 可讀到 iteration 75；但 CFD evidence gate 仍 fail，
BL/HXT route 仍在 DAE31-family PLC segment/facet intersections 擋住。因此這是 serious
high-mesh no-BL handoff，不是 BL handoff、不是可解讀 CL/CD、不是 Baseline A reopen evidence。

WO-006R4 BL ownership repair campaign 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/`。
Verdict 是 `wo006r4_adapter_limitation_proven`：R4 沒有產生 `bl_mesh_handoff.v1.json`。
Gmsh topological BL route 仍在 R3 的 DAE31-family PLC points 擋住；盲目把 shorter
diagonalization 套到 BL 仍是 rejected workaround，因為它暴露 `Unknown curve -1550`。
mesh-native owned-BL block 可以在 current GO 幾何上產生正體積近壁 block
（first layer `5e-5 m`、24 layers、estimated y+ 約 `1.04`），且 R4 未新增外形 cleanup
或改 authority source；但 preserved core probe 同時有 core quality fail 與 wake/span-cap
coupling partial，remeshed core probe 則會改掉 BL-core interface，不能當 conformal viscous
handoff。因此目前最小 blocker 是「缺 conformal owned BL block + core merge / SU2 mixed-element
writer」，不是 solver tuning 或可用係數問題。

WO-006R5 BL+core merge campaign 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`。
Verdict 是 `wo006r5_core_merge_limitation_proven`：R5 沒有產生
`bl_mesh_handoff.v1.json`，也沒有 conformal mixed BL+core SU2 handoff。Preserved-core
probe 可保留 core interface envelope（`bl_outer_interface`、`wake_cut`、`span_cap`
沒有被 remesh），但 core quality gate 仍 fail（non-positive SICN/SIGE/volume），且
BL/core coupling 仍只有 partial：`wake_cut` 與 `span_cap` 還有 unmatched interface faces。
把全部 non-wall BL boundary 直接當 core inner boundary 的捷徑也被證明不是 watertight
surface（124 bad edges）。因此目前最小 blocker 是 conformal core interface / mesh-quality
repair，不是係數、solver tuning 或資料權威問題。

WO-006R6 core-interface repair campaign 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/`。
Verdict 是 `wo006r6_core_quality_limitation_proven`：R6 仍沒有產生
`bl_mesh_handoff.v1.json`，也沒有 real merged mixed-element BL+core SU2 mesh。Preserved-core
route 仍可保留 interface envelope，但 core mesh quality gate 仍 fail
（non-positive SICN/SIGE/volume）；同時 interface topology audit 仍顯示 zero-unmatched
未達成：`wake_cut` / `span_cap` 還有 94 個 core interface unmatched faces 與 3136 個
BL boundary unmatched faces，full non-wall boundary 仍是 124 bad edges。下一步不能把這當
writer 小修；要先修 preserved-core quality，且後續仍要重做 wake/span-cap 的真實 conformal
BL/core topology contract。

WO-006R7 core-quality hotspot diagnosis 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r7_core_quality_hotspot_diagnosis/`。
R7 把 R6 的 core quality fail 定位成 `91` 個 non-positive `Pyramid 5` transition
elements，全部貼在 preserved `bl_outer_interface` quads；`87` 個在 aft/TE，`21` 個落在
`dae31 -> cst_tip_nsga2_g05_child_0032_70ef8136` transition。這表示下一步應修
quad-to-tet pyramid transition / orientation / warped-face interface，不是增加 SU2
iteration 或重跑 no-BL medium。

WO-006F SU2 engineering-result recovery campaign 已新增，artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/`。
Verdict 是 `wo006f_campaign_incomplete`：SU2 有跑出 sign-correct 但不可採信的 no-BL
RANS final pair（`CL=1.289421542`、`CD=0.5555196327`），drag 比 AVL + Tier2
profile-proxy / old VSPAERO sanity bounds 高太多且未收斂；Euler 曾短暫穿過正 lift/drag
區間，但會漂到負 drag。OpenVSP/Gmsh 替代 route 仍被 thin-wing topology 擋住；R6 BL/core
兩區 multizone route 可啟動，但 core quality / wake-span-cap coupling / force coefficient
ownership 未過 gate。因此 WO-006F 不是 SU2 calibration success、不是 Baseline A reopen
evidence；下一步應從 R6 preserved-core quality 與 multizone/merged coefficient ownership 下手。

目前 gate 讀法：

- `98.5 kg` 是目前 design gross mass authority，除非使用者明確改掉。
- `106.828608 kg` 是 suspect P1 screening aggregate，不是目前 Baseline A design mass truth。
- 目前 pipeline span evidence 是 `34.332286 m` full span / `17.166143 m` half-span，除非新的 authority manifest 取代它。
- `16.5 m` 只能當 local/splice screening reference，不是 current pipeline half-span、RFQ control span、shop span 或 procurement truth。
- WO-005 carbon tube RFQ pack 只能當 draft/vendor-screening；不能下單、選 vendor、放 shop drawing。
- WO-006 只能做 bounded aero calibration；不是 release truth、不是 RFQ/procurement truth、不是 final aircraft sign-off。
- WO-006 必須使用 `98.5 kg` 與 current pipeline span authority，除非明確標成 sensitivity study。
- WO-006 第一輪 verdict 是 `su2_baseline_needs_fix`；WO-006R1 已打通 current GO mesh-native coarse smoke route；WO-006R2 已把 current high-mesh / BL blocker 定位到 surface topology；WO-006R3 已產出 serious high-mesh no-BL handoff；WO-006H reopened campaign 已達 accepted `su2_local_hard_limit_proven_with_executable_hpc_case`；current-GO no-BL completion case 已產出 finite SU2 force history，但只能作 route-level force evidence，仍不是 BL/y+ drag calibration 或 performance truth。
- WO-006R6 verdict 是 `wo006r6_core_quality_limitation_proven`；current GO 已有 owned-BL topology basis 和 preserved-interface core evidence，但 core quality 與 wake/span-cap conformal topology 仍未達成，沒有 conformal mixed BL+core SU2 handoff，沒有 `bl_mesh_handoff.v1.json`，沒有 postprocessed y+，也沒有可解讀係數。
- WO-006R7 verdict 是 hotspot diagnosis blocked：R6 core bad cells 目前定位為 `91` 個貼在 preserved `bl_outer_interface` 的 non-positive pyramid transition elements；優先修 quad-to-tet pyramid transition/interface orientation，不要把這解讀成 solver iteration 問題。
- WO-006F verdict 是 `wo006f_campaign_incomplete`；目前沒有 physically credible SU2 CL/CD 可用於 Baseline A aero calibration。`attempt_10` 證明 SU2 multizone 是開放修復 route，但還不是 coefficient evidence。
- WO-007 QPROP/XROTOR、RFQ procurement 與任何 Baseline A release claim 仍不得把 screening evidence 升格成 current truth。
- P1/C04 仍是 coupon/local FEM readiness；screening pass 不是 final aircraft sign-off。

先讀：

- [docs/reports/baseline_A_data_authority_audit.md](docs/reports/baseline_A_data_authority_audit.md)
- [docs/reports/baseline_A_data_authority_conflict_register.md](docs/reports/baseline_A_data_authority_conflict_register.md)
- [output/baseline_A_team_release/data_authority_table.csv](output/baseline_A_team_release/data_authority_table.csv)
- [docs/reports/repo_channel_hygiene_plan.md](docs/reports/repo_channel_hygiene_plan.md)

這個 repo 目前服務的是一條 **全新人力飛機設計 pipeline**，不是 Black Cat 004 舊機體的補強案。
Black Cat 004 / dual-beam / OpenMDAO spar optimizer 仍保留為歷史基礎與可重用工具，但不再是 root
README 的主敘事，也不應被新 agent 當成目前 candidate 的設計真相。

目前正式主線以 Phase J pipeline 為準：

```text
Mission contract
-> tail / CG / trim / stability contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check with full-aircraft trim / stability context
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape and all-moving tail trim
-> Tier2 full-alpha airfoil selection plus discrete tail-airfoil screening
-> aero-structure closure with tail control DOFs
-> FEM/APDL / shell buckling / load-factor / tailboom / hardware checks
```

這條線的目標是把任務需求、spanload、可製造幾何、loaded shape、翼型選擇、結構預算與候選驗證
放在同一條可追溯的工程鏈上。它目前產出的 `current_avl_compromise_conservative_closed` 是
**conservative screening candidate**，可以拿去做幾何 / 結構 / 製造審查，但還不是 final
production aircraft。

如果要看這條 pipeline 每一步現在實際用到哪些 artifact、candidate、關鍵數字與 trust boundary，
先讀 [docs/reports/2026-05-09_phase_j_evidence_map.md](docs/reports/2026-05-09_phase_j_evidence_map.md)。
這份 evidence map 已重新審核 source chain：`sample_1476` / `233 W` / `8642.9 m`
屬於舊 medium-search 診斷資料，不是目前 Phase J 上游證據。commit history 顯示
mission-to-airfoil 線確實存在：pilot power / thermal derate、mission design-space scan、
drag budget、MissionContract / FourierTarget、airfoil sidecar、smooth geometry、loaded-Z、
Tier2 airfoil 與 closure 都已接出來。現在缺的是一份 promoted trace manifest，把 current
mission handoff 乾淨追到 `current_avl_compromise_conservative_closed`；所以目前 go-mode
candidate 是 conservative screening candidate，不是 final aircraft。

如果要看目前 pathfinder 本身的 basis lock，讀
[docs/reports/2026-05-09_pathfinder_basis_lock.md](docs/reports/2026-05-09_pathfinder_basis_lock.md)。
它把 `current_avl_compromise_conservative_closed` 的 downstream artifact chain、
beam-line proxy / aerodynamic surface / clearance / loaded-Z 一致性、以及下一步
tail contract / rib sensitivity / ASWing-like coupling / FEM detail 的優先順序鎖清楚。

如果要做 rib / rear-spar sensitivity，先讀
[docs/reports/2026-05-09_conservative_load_mapper_foundation.md](docs/reports/2026-05-09_conservative_load_mapper_foundation.md)。
`ConservativeLoadMapper` 是 aero grid -> structural grid 的 opt-in conservative remap foundation；
它守恆 total lift、root bending moment、total pitching torque，並輸出 correction diagnostics。
它是 sensitivity 前置基礎，不是 aeroelastic sign-off。

如果要把 horizontal tail / vertical tail 接進目前主線，先讀
[docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md](docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md)。
尾翼不是最後才補的 FEM 件；對 all-moving horizontal tail / all-moving vertical tail 來說，它是
trim、stability、control authority、tailboom load、mission drag/mass 的共同 contract。主翼
Fourier spanload 仍由主翼主導，但 mission contract 必須先有 tail / CG / stability 邊界，
AVL realization 之後必須進 full-aircraft trim / stability context，aero-structure closure 之後
all-moving tail 才能作為控制自由度。

目前 current pathfinder 的 tail contract v0 foundation 已建立，讀
[docs/reports/2026-05-09_tail_contract_v0_foundation.md](docs/reports/2026-05-09_tail_contract_v0_foundation.md)
和 [configs/current_pathfinder_tail_contract_v0.yaml](configs/current_pathfinder_tail_contract_v0.yaml)。
它只完成 tail volume / reserve bookkeeping，screening output 仍是 `required_inputs_missing`；
all-moving full-aircraft AVL audit v0 則在
[docs/reports/2026-05-09_full_aircraft_tail_avl_audit_v0.md](docs/reports/2026-05-09_full_aircraft_tail_avl_audit_v0.md)
與 `output/current_pathfinder_tail_avl_audit_v0/`。本機 AVL runner 已產生 9 個全機 deck /
`.st` sweep artifact，但 verdict 是 `blocked_by_directional_stability_or_vtail_authority`：
longitudinal trim 仍被 missing CG / wing AC 擋住，`V_V = 0.010145` 且
`C_n_beta = 0.002236` 太小。下一步要先回 tail sizing / CG / reference-moment contract，
不要直接跳 rib sensitivity。
目前這一步已往下接出 V-tail / CG reference sizing sensitivity v0，讀
[docs/reports/2026-05-09_vtail_cg_reference_sensitivity_v0.md](docs/reports/2026-05-09_vtail_cg_reference_sensitivity_v0.md)
和 `output/current_pathfinder_vtail_sensitivity_v0/`。它只做 bounded V-tail area / aft-position
AVL sensitivity，不做 rib / rear spar / ASWing-lite / FEM / tail airfoil NSGA2。結果顯示較大的
V-tail area / tail arm 能把 `C_n_beta` 和 `C_n_deltaV` 往合理方向推，但 final verdict 仍是
`blocked_by_missing_cg_or_reference_moment`：`Xref` 只是 AVL coefficient reference，`Xnp` 只是
未驗證 convention 的 neutral-point candidate，current pathfinder 還沒有 promoted aircraft CG range。

接著已建立 tail / CG / trim / stability screening v1，讀
[docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md](docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md)
與 `output/current_pathfinder_tail_cg_trim_stability_v1/`。這一步明確把 AVL `Xref`
設為每個 screening CG row，不把原始 `Xref` 當 CG；`Xnp` 只有在
`Xnp = Xref - Cma/CLa*Cref` 自洽時才使用。verdict 是
`ready_for_tail_aware_rib_rear_spar_sensitivity`，但只限 screening：推薦下一步使用
CG range `[0.68, 0.75] m`、H-tail `S_H=4.5 m^2 / x_ac_H=8.281 m`、V-tail
`S_V=3.36 m^2 / x_ac_V=8.350 m`，並把 tail drag/mass penalty 帶進 sensitivity；
這不是 measured CG manifest、tail polar sign-off、FEM 或硬體認證。

tail-aware bounded rib / rear-spar sensitivity 已完成，讀
[docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md)。
目前 verdict 是 `ready_for_tail_aware_aeroelastic_closure`，選定 screening basis 是
`0.30 m` rib target bay tied to `121` full-wing materialized rib/station count、
`bounded_50pct_screening` rear-spar participation、warping knockdown `0.50246`。
同一個 runner 現在也會重跑 rib material family sensitivity：`balsa_sheet_3mm` 保留為 baseline，
新增 foam-only EPS / XPS / structural foam families。v1 verdict 是
`foam_only_families_do_not_clear_current_aeroelastic_closure`：EPS/XPS 的 projected twist 約
`33.16 deg`，structural foam 約 `9.32 deg`，都高於 `3 deg` screening bound；第一版沒有
EPS+balsa / glass / carbon hybrid stiffness credit。runner 也新增下一輪
`stiffness_rework_candidates`：balsa baseline 保留比較用，hybrid EPS+balsa/cap、
structural-foam+glass-face 與 stronger rear-spar participation / shear-transfer rows 是
下一輪 closure rerun candidates，不能把 foam-only rows 硬升級成 pass。
重要限制：未補償的 tail+ribs mass bookkeeping 會把 CG 推到 `0.801 m`，所以 aeroelastic
closure 只能使用 final CG 管理後的 `0.75 m` screening row；不能把 tail/rib mass 加上去後還
沿用舊 ready verdict。

tail-aware aeroelastic closure baseline 已完成第一輪，讀
[docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md](docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md)。
baseline verdict 是 `needs_aeroelastic_geometry_or_stiffness_rework`：fixed-point loop 收斂，final
managed CG `0.75 m`、H-tail trim reserve、static margin、V-tail authority、mass/drag/power
charge 與 conserved load remap 都保留；但 direct spar-pair rotation -> AVL incidence stress-test
給出 `5.413 deg` max twist，超過 `3 deg` screening bound。新增 twist-source audit 顯示
elastic-axis / quarter-chord consistent projection 仍約 `5.413 deg`，conservative bounded
physical projection 仍約 `3.256 deg`，peak station 在 y≈`2.328 m`，主要來源是 aerodynamic
torque-only 分量，lift 在該站反而部分抵消。clear verdict 是
`ready_for_hybrid_rib_stiffness_rework`：這是 rework baseline，不是目前最新 closure-owned
hybrid result；不要把 direct projection 當 final measurement。

current pathfinder materialized rib contract audit 已建立，讀
[docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md](docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md)
與 `output/current_pathfinder_materialized_rib_contract_audit/`。這一步把 current balsa
screening basis 展成可重跑的 `121` full-wing rib/station trace 與 `120` bays；max
materialized bay 是 `0.297063 m`，所以 `0.30 m` bay 已被 physical ribs materialized。
但 report verdict 仍是 `blocked_needs_materialized_bond_shape_data`：transport joint、
control station、airfoil transition、twist transition 都是 `missing_contract`；skin sag
是 `unknown_requires_test`，bond/collar/spar contact 是 `needs_data`，y=`2.327757 m`
附近被標成 torque-critical local FEM / hybrid reinforcement zone。下一輪 hybrid stiffness
sweep 應使用這些 local zones；不能跳過 materialized audit 直接把 EPS/XPS foam-only 或
warping-knockdown tuning 宣稱成 closure pass。

rib / torsion rework verdict 已完成第一輪，讀
[docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md)
與 `output/current_pathfinder_rib_torsion_rework_verdict/`。目前 verdict 是
`candidate_ready_for_local_FEM_and_coupon_before_FEM_package`，不是
`ready_for_FEM_loadcase_package`。下一個可用候選是
`eps_balsa_cap_hybrid_10mm + bounded_65pct_screening`。這一輪已讓 closure runner 真正吃到
hybrid main/rear torsion-cell screening surrogate：actual closure bounded physical twist
降到 `2.070 deg`，低於 `3 deg` bound；direct stress-test 從 baseline `5.413 deg`
降到 `3.449 deg`，仍高於 `3 deg`，所以它是 conservative aero-surface mapping / local FEM
檢查項，不是 final twist signoff。rib mass 約 `5.365 kg`，比 balsa baseline 多
`2.335 kg`，CG/rebalance 已計入。P1 C04 bond/collar blocker 已往下推進到
load-path closure；但 final FEM/APDL 或 aircraft sign-off 仍要等 transition/control
stations、C07 skin sag process、coupon/local FEM 與 hardware/laminate detail 關閉。

rib / torsion fast design-search loop 已重新校準，讀
[docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md)
與 `output/current_pathfinder_rib_torsion_design_search/`。這是可重跑的 revised fast model search，
不是單點 patch：它掃 rib/core thickness、material family、zone spacing、cap/face/collar
local reinforcement、rear-spar participation `0.50 / 0.65 / 0.75`，並輸出 candidate table、
Pareto / shortlist、FEM calibration sample set 與 APDL/CalculiX calibration skeletons。
fast physical model 現在是 `link_limited_torsion_cell_v2`：rib thickness、spacing 與
collar credit 被視為 shear-transfer link terms，不再把 carbon collar / relaxed spacing
當成完整 torsion-cell GJ 乘數。revised fast-loop selected row 變成
`eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`；
fast bounded twist 約 `1.674 deg`。原本的 relaxed 10 mm carbon-collar row 仍保留為
representative `selected_hybrid_10mm` FEM sample，另加 revised selected candidate sample；
EPS/XPS foam-only 仍只可當 shape-core / lightweight reference，不可當 structural bracing pass。

rib / torsion fast-loop CCX local-frame physical alignment 已完成，讀
[docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md)
與 `output/current_pathfinder_rib_torsion_fem_calibration/`。這一步把 CalculiX/CCX 從
2-node smoke 升級成 local beam-frame calibration：main/rear spar segment、torque-zone
collar、rib shear-transfer / diagonal shear-transfer beams、y=`2.327757 m` local lift
與 main/rear torque-couple 都寫進 sample decks，並輸出
`output/current_pathfinder_rib_torsion_fem_calibration/fast_model_calibration_update.json`
和 `surrogate_feedback.csv`。這次不再把 family correction factor 當作 fast truth：
`family_correction_factors` 保持空值，alignment artifact 只保留 legacy diagnostic factors。
CCX local model audit 判定 `ccx_local_model_reasonable_for_fast_physics_alignment`，反力平衡
closed，變形模式是 torsion / shear-transfer dominant。代表 structural rows 的 revised
fast-vs-CCX error 已壓到 `<=5%`：原 relaxed 10 mm selected row `4.554%`、aggressive
carbon/glass collar row `1.171%`、revised selected row `1.950%`。verdict 是
`fast_physical_model_verified_within_5pct`，但這只代表 local CCX beam-frame 對齊；
y≈`2.328 m` bond/collar/tube-wall 仍是 `watch`，不是 adhesive / collar / tube-wall /
skin sag / buckling / flight-load final sign-off。

rib / torsion detailed local validation shortlist 已鎖定，讀
[docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md](docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md)。
目前 verdict 是 `selected_candidate_ready_for_detailed_local_validation`，不是 final pass。
P1 是 revised fast-loop selected row
`eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`，
bounded twist `1.673592 deg`；P2 是 12 mm uniform carbon-collar heavier reserve；P3 是
10 mm uniform glass-face collar lower-complexity alternate。下一層要做 y≈`2.328 m`
rib/collar/bond/tube-wall detailed FEM、skin sag、rib-to-spar shear/peel、collar/cap load path、
tube crush/ovalization、ordinary bay 和 coupon/allowable，不是再調 fast model。

positive y≈`2.328 m` torque-critical local validation package 已建立，讀
[docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md](docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md)
與 `output/current_pathfinder_positive_torque_zone_validation/`。這份 package 鎖定
R067 / R068 / R069 與 B066 / B067 / B068 / B069，並把 R066 / R070 當 local model
boundary；critical R068 的 local load row 約為 main lift `21.202 N`、kernel torque
`-12.716 N*m`，轉成 main/rear torque-couple `-23.839 / +23.839 N`。它輸出 APDL guarded
skeleton、station/bay manifest、load decomposition、coupon matrix 與 missing-data register；
verdict 是 `positive_zone_ready_for_local_FEM_and_coupon_definition_not_margin_pass`，不是 FEM
margin pass。下一步是填 adhesive/collar/tube-wall/cap/skin supplier 或 coupon allowables，
再跑 positive-zone local margin；穩定後 mirror/compare negative zone。

P1 local detail validation Steps 1 and 2 已完成（2026-05-11）：**Step 1** geometry and
allowable freeze sheet（`scripts/current_pathfinder_rib_local_detail_geometry_freeze.py`）從
config 推導 y≈2.328 m 的 spar tube OD/wall，填入全 8 個 missing-data items，對 7 個
failure modes 做 preliminary margin screen，並填入 APDL skeleton。詳讀
[docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md](docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md)。
**Step 2** refined analytical margin run（`scripts/current_pathfinder_rib_local_detail_margin_run.py`）
套用精化力學模型：**C04 bond peel margin = −0.893（critical blocker）**，eccentric moment
model 顯示現有 collar tab 偏心力臂是根本原因；C07 skin sag nominal margin 0.026，min viable
pre-strain ≈ 0.05%，製程規格仍是未關閉事項。詳讀
[docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md](docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md)。

C04 架構修正方向已確立（2026-05-12）：C04 peel 問題根本原因是偏心力臂，不是 adhesive
強度不足。`scripts/collar_joint_modes.py` 提供五種 collar joint mode 的 Strategy Pattern
library（59 unit tests），`scripts/current_pathfinder_rib_collar_joint_design_search.py`
執行多模式設計搜尋（11 integration tests）。推薦架構：**saddle ring yoke**（conformal bonded
ring + 切向 lug pair，消除 outward peel moment）+ friction clamp = `recommended_c04_fix()`。
peel bond 現有構型 fail，saddle ring yoke fast-model 估算 pass。這仍是 analytical screening，
不是 coupon test 或 FEM 簽核。

3 m 翼板運輸接頭設計已完成（2026-05-12）：`scripts/current_pathfinder_spar_splice_design.py`
針對 Step-1 freeze 的 structural half-span `16.5 m` 設計 5 個 splice joints
（y = 3 / 6 / 9 / 12 / 15 m），全翼展共 10 個，採 CFRP spigot + ferrule + shear dog。
所有接頭 pass，y = 3 m 需 spigot wall 1.02 mm（自動 upsize），全翼展接頭總質量
**3.85 kg**。注意：aero closure / materialized rib station grid 可延伸到約
`17.3 m`；splice runner 的半翼展敘事以 structural freeze `16.5 m` 為準。翼板 3 m
限制確認鎖定（台灣自有貨車 + 空運雙重收斂）。13 tests pass。

Baseline A carbon tube RFQ screening pack 是舊 WO-005 generated evidence under data-authority
repair，讀
[output/baseline_A_team_release/carbon_tube_rfq_pack.md](output/baseline_A_team_release/carbon_tube_rfq_pack.md)。
舊 verdict `carbon_tube_rfq_pack_ready` 是 historical/generated evidence under data-authority repair, not active current truth。WO-005 目前只能當 draft/vendor-screening 草稿：可整理 vendor
OD/ID、layup、tolerance、ovality、straightness、surface prep、QA coupon、3 m shipping、
spigot/ferrule fit 與 lead time 問題；不能當 purchase order、supplier selection、shop drawing
release、RFQ control truth 或 final aircraft sign-off。`16.5 m` 是 local/splice screening only，
不是 RFQ control span、shop span 或 procurement truth；3 / 6 / 9 / 12 / 15 m splice stations 與
0.30 m materialized rib basis 也只是 draft screening reference，不能被 vendor 當 drawing control。

P1 local load-path closure + mass-integrated pathfinder update 已完成（2026-05-12），讀
[docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md](docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md)
與 `output/current_pathfinder_p1_load_path_mass_closure/`。final verdict 是
`p1_local_load_path_ready_for_coupon_fem`：baseline C04 eccentric peel margin `-0.893`
仍被保留為 fail evidence，但 installed fix 改成 `saddle_ring_yoke_plus_secondary_clamp`
後 local surrogate pass，governing 是 secondary clamp torque margin `0.8876`（saddle
ring yoke adhesive shear margin `65.0672`）。C04 fix mass `0.093839 kg` 與 3 m splice
mass `3.847 kg` 已回灌到 current pathfinder mass / CG / tail / closure；updated
screening mass basis `106.828608 kg`，managed final CG `0.75 m`，需要 `0.057304 m`
forward rebalance on 56 kg equivalent mass。tail trim/stability pass，bounded physical
twist `1.906952 deg`，root bending ratio `0.971590`；direct spar-pair stress-test
仍是 conservative mapping warning。這代表 P1 C04 可進 coupon/local FEM，不是 final
adhesive、laminate、buckling、tail hardware 或 aircraft sign-off。QPROP/XROTOR 是獨立
propulsion lane，不參與這個 structural blocker verdict。

Baseline A team release system 的舊 WO-001 generated package 已建立（2026-05-12），讀
[docs/AI_WORK_ORDER_PROTOCOL.md](docs/AI_WORK_ORDER_PROTOCOL.md)、
[docs/work_orders/QUEUE.md](docs/work_orders/QUEUE.md) 與
`output/baseline_A_team_release/`。舊 verdict `baseline_A_release_system_ready` 是 historical/generated evidence under data-authority repair, not active current truth；current
release status 是 `baseline_A_data_authority_restored_wo006_unblocked`，只放行 bounded WO-006
aero calibration。這包只能當施工 / 結構 / 控制 /
傳動 / 製造分工的 screening evidence 與 coordination material，不是 Baseline A release authority、
也不是 procurement truth 或 final aircraft sign-off；P1 只到 coupon/local FEM readiness，C04 fix 是
architecture-selected 但仍需 coupon/local FEM，QPROP/XROTOR 保持獨立 propulsion lane。
WO-002 mass / CG / margin ledger 已補進同一個 release builder，但舊 verdict
`mass_cg_margin_ledger_ready` 是 historical/generated evidence under data-authority repair,
not active current truth。`98.5 kg` 才是目前 design mass authority；`106.828608 kg` 是 suspect
P1 screening aggregate。`mass_budget.csv`、`cg_summary.json`、`margin_budget.md` 和
`mass_cg_margin_daily_review.md` 只能當 screening ledger / 每日審查入口；所有現有 mass rows
仍是 `estimate`，不是 measured/frozen weight-and-balance。

WO-003 design-space freeze audit 已完成，讀
`output/baseline_A_team_release/design_space_freeze_audit/design_space_freeze_audit.md`。
verdict 是 `baseline_A_freeze_reasonable`：目前沒有看到 nearby manufacturable candidate
明確觸發 Baseline A reopen；最強 fast-model nearby row 約省 `4.63%` crank power，低於
5-8% reopen trigger，且沒有 downstream geometry / CG / torsion / splice / P1 load-path chain。
但 release mass + tail CD0 charge 丟回 Stage-0 quick-screen 會出現約 `-9 W` power margin，
所以這是 power-budget watch item，不是 final mission sign-off。

WO-004 manufacturable smoothness / discretization audit 已完成，讀
`output/baseline_A_team_release/manufacturable_geometry_audit/manufacturable_geometry_audit.md`。
verdict 是 `geometry_freeze_needs_fix`：目前 smooth pathfinder 沒有看到會強迫 Baseline A
reopen 的大型外形不連續，但連續尺寸還不能直接當 shop/RFQ 控制尺寸。WO-005 RFQ pack
已把 0.30 m rib basis、3 m splice、materialized station、structural `16.5 m` half-span
與 aero/rib station extent 的差異收成 controlled station/span/splice manifest；inboard
splice zero bending margin 是 vendor/RFQ warning，不是已失敗的 Baseline A mission verdict。

## 主線操作協議：Pathfinder First, Then Expansion

目前策略不是一次把 `22464` 個 mission design-space cases 全部推到最終 FEM，也不是把單一
candidate 當成全域最佳解。正確做法是先選一條最可信的 **pathfinder candidate**，把
mission、Fourier/AVL、smooth geometry、loaded-Z、loaded-shape AVL、Tier2 airfoil、
aero-structure closure、FEM/APDL spot-check 全部串通。

這條 pathfinder 的用途是：

- 先證明整條工程 pipeline 可以從任務需求一路走到可審查候選。
- 在每個 stage 做局部工程修正與局部最佳化，暴露真實 blocker。
- 讓 rib、rear spar、wire attach、root joint、beam-line / aero-surface、airfoil query
  以及 empennage trim / stability 這些問題有同一個候選與同一組 load / geometry / mass basis 可以討論。
- 等閉環穩定後，再擴大 search space：更多 span / AR / speed / airfoil / structure family /
  rib-bracing 方案，而不是一開始就把所有維度全部打開。

因此 `current_avl_compromise_conservative_closed` 應讀成目前的 pathfinder /
conservative screening candidate：它是工程閉環的先行者，不是 final aircraft、不是全域最佳，
也不是硬 gate 標準。

---

## 先看哪裡

| 目的 | 文件 | 定位 |
|---|---|---|
| 判斷目前真正主線 | [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md) | 單一真相文件 |
| 理解主線為什麼變成 Phase J | [docs/reports/2026-05-08_commit_history_report.md](docs/reports/2026-05-08_commit_history_report.md) | commit-derived pipeline report |
| 看 Phase J 每一步目前到底靠哪些 artifact / candidate / trust boundary | [docs/reports/2026-05-09_phase_j_evidence_map.md](docs/reports/2026-05-09_phase_j_evidence_map.md) | stage-by-stage evidence map |
| 看目前 pathfinder 的 locked basis / geometry-state 一致性 / 下一步優先序 | [docs/reports/2026-05-09_pathfinder_basis_lock.md](docs/reports/2026-05-09_pathfinder_basis_lock.md) | candidate basis lock |
| 看 conservative load remap / rib sensitivity 前置 load gate | [docs/reports/2026-05-09_conservative_load_mapper_foundation.md](docs/reports/2026-05-09_conservative_load_mapper_foundation.md) | load conservation foundation |
| 看 tail-aware rib / rear-spar sensitivity verdict 與 material-family compare | [docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md) | balsa baseline ready-for-closure basis; foam-only families stay low-stiffness references; hybrid rework candidates are listed |
| 看 tail-aware aeroelastic closure verdict | [docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md](docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md) | converged; twist-source audit points to hybrid rib/stiffness rework |
| 看 current pathfinder rib station/bay 是否真的 materialized | [docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md](docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md) | 121 station / 120 bay trace; shape, bond, collar, transition data still blocked |
| 看 rib / rear-spar / torsion blocker 下一階段 verdict | [docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md) | hybrid closure-owned bounded twist clears 3 deg; P1 local load-path has since moved to coupon/local FEM readiness |
| 跑 rib / torsion fast design-search loop 與 FEM calibration sample set | [docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md) | revised link-limited physical model; selected fast candidate is uniform 0.30 m carbon-collar rear75; FEM samples include original selected, aggressive, foam reference, and revised selected |
| 看 rib / torsion fast-loop CCX local-frame physical alignment | [docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md) | representative structural rows aligned within 5% against local CCX beam-frame; no hidden family correction; not final bond/tube-wall/buckling sign-off |
| 看 rib / torsion detailed local validation shortlist | [docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md](docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md) | selected 10 mm uniform carbon-collar basis locked; 12 mm reserve and 10 mm glass-collar fallback listed; no final aircraft pass |
| 接 positive torque-zone local FEM / coupon package | [docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md](docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md) | R067/R068/R069 + B066-B069 package; APDL skeleton and coupon/missing-data register; no FEM margin claimed |
| 看 P1 local detail Step 1 geometry/allowable freeze sheet | [docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md](docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md) | spar tube OD/wall from config; 8 missing-data items filled; 7 preliminary margins; APDL skeleton filled |
| 看 P1 local detail Step 2 refined analytical margin run | [docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md](docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md) | C04 bond peel margin −0.893 (critical blocker); C07 skin sag pre-strain sweep; C02-C06 analytical margins large |
| C04 collar joint 架構修正方向 + multi-mode design search | `scripts/collar_joint_modes.py` (59 tests) + `scripts/current_pathfinder_rib_collar_joint_design_search.py` (11 tests) | saddle ring yoke confirmed as C04 fix direction; recommended_c04_fix() = saddle ring + clamp; analytical screening only |
| 3 m 翼板 spar splice 設計 | `scripts/current_pathfinder_spar_splice_design.py` (13 tests) | 5 joints per half-wing on structural freeze half-span 16.5 m; all pass; 3.85 kg full-wing; inboard spigot wall 1.02 mm; 3 m limit locked |
| 看 P1 C04 load path 與 mass/CG/tail/closure 回灌後 verdict | [docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md](docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md) | final verdict `p1_local_load_path_ready_for_coupon_fem`; C04 saddle/yoke/clamp + splice mass charged to closure; coupon/local FEM next |
| 接 Baseline A team release package | `output/baseline_A_team_release/` | old `baseline_A_release_system_ready` is historical/generated evidence under data-authority repair, not active current truth; current release status is `baseline_A_data_authority_restored_wo006_unblocked` for bounded WO-006 only |
| 看 Baseline A mass / CG / margin ledger | `output/baseline_A_team_release/margin_budget.md` + `mass_cg_margin_daily_review.md` | old `mass_cg_margin_ledger_ready` is historical/generated evidence under data-authority repair, not active current truth; `98.5 kg` is authority, `106.828608 kg` is suspect screening |
| 看 Baseline A design-space freeze audit | `output/baseline_A_team_release/design_space_freeze_audit/design_space_freeze_audit.md` | `baseline_A_freeze_reasonable`; no explicit nearby dominance trigger; power-budget watch item remains |
| 看 Baseline A manufacturable geometry audit | `output/baseline_A_team_release/manufacturable_geometry_audit/manufacturable_geometry_audit.md` | `geometry_freeze_needs_fix`; smooth enough for release engineering, not shop/RFQ drawing control |
| 看 carbon tube RFQ screening pack | `output/baseline_A_team_release/carbon_tube_rfq_pack.md` | old `carbon_tube_rfq_pack_ready` is historical/generated evidence under data-authority repair, not active current truth; WO-005 is draft/vendor-screening only |
| 讓 AI thread 自動接任務 | [docs/AI_WORK_ORDER_PROTOCOL.md](docs/AI_WORK_ORDER_PROTOCOL.md) + [docs/work_orders/QUEUE.md](docs/work_orders/QUEUE.md) | work-order lifecycle, required report shape, reviewer prompt, priority queue |
| 看 all-moving tail / trim / stability 要怎麼進目前 pathfinder | [docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md](docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md) | empennage contract insertion |
| 找所有文件入口 | [docs/README.md](docs/README.md) | 文件索引 |
| 看近期優先順序 | [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md) | 近期 roadmap，可能需要再按 Phase J 更新 |
| 接續任務包 | [docs/task_packs/current_parallel_work/README.md](docs/task_packs/current_parallel_work/README.md) | 多 agent handoff |
| 查舊 Black Cat / OpenMDAO 內容 | [docs/legacy_blackcat004_downstream_reference.md](docs/legacy_blackcat004_downstream_reference.md) | 歷史參考，不是目前主線 |
| 接續 mesh-native CFD 支線 | [hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md](hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md) | product-route handoff; separate from WO-006 bounded calibration |

---

## 目前能做什麼

- 用 mission design-space / drag-budget contract 建立 Stage-0 search bounds、mission gate 與 seed pool；
  committed config dry-run 為 `22464` cases，local generated handoff 目前是 ignored output。
- Fourier-AVL calibration 工具與資料格式已存在；目前 committed calibration rows 仍是 legacy diagnostic，
  要做 current candidate ordering 前必須建立 current trace，而不是重用舊 medium-search top exports。
  `scripts/fourier_avl_calibration_mvp.py` 現在要求明確 `--report-json`，舊 medium-search 來源預設封鎖。
- Stage-2 Fourier spanload / MissionContract / FourierTarget machinery 已存在，但還缺一份 promoted
  current trace manifest 連到 go-mode candidate；不要把「缺 trace」誤讀成「Stage 0-2 不存在」。
- 現有 downstream chain 可從 `smooth_tier2_production_baseline` 進入 smooth production geometry / AVL realization。
- 對 realized geometry 做 AVL realization check。
- 做 structure-budgeted loaded-Z search，檢查 mass、clearance、wire、loaded shape 的折衝。
- 對 realizable loaded shape 重跑 AVL，避免拿 requested shape 的漂亮結果當真。
- 用 `ConservativeLoadMapper` 將 AVL/aero grid loads remap 到 structural grid，並檢查 total lift、
  root bending moment、torque 的 conservation diagnostics；large correction 要降級 load basis
  confidence，不能直接進 rib sensitivity。
- 建立 tail / CG / trim / stability 低階 contract，讓 all-moving horizontal tail / vertical tail
  在 mission、full-aircraft AVL recheck、tail-aware closure、tailboom/hardware validation 中有明確位置。
  Current pathfinder v0 foundation、all-moving full-aircraft AVL audit v0、V-tail sensitivity v0
  和 tail / CG / trim / stability screening v1 已存在；tail-aware rib / rear-spar
  sensitivity 已選出可進 aeroelastic closure 的 balsa baseline screening basis，且 material
  family sensitivity 顯示 foam-only EPS/XPS/structural foam 不能直接解除 twist blocker；twist-source
  audit 的 baseline 判定為 `ready_for_hybrid_rib_stiffness_rework`；rib/torsion rework
  verdict 已讓 selected hybrid closure-owned bounded twist 清到 `2.070 deg`，但 direct
  stress-test 仍是 conservative mapping warning；final CG 必須被管理在 `[0.68, 0.75] m`。
- 用 Tier2 full-alpha airfoil database 依 actual loaded-shape local `Cl/Re` 做翼型選擇。
- 做 aero-structure closure，確認氣動、翼型、loaded shape、結構、clearance、wire 在同一個候選上閉合。
- 做 FEM/APDL、shell buckling、load-factor candidate spot-check。
- 用 Phase J 後續 guardrails 防止局部 pass 被誤寫成 final aircraft sign-off。

---

## 不要誤會的地方

- 這不是「Black Cat 004 舊設計補強」的 root workflow。
- `configs/blackcat_004.yaml`、`examples/blackcat_004_optimize.py`、舊 OpenMDAO component DAG、11 根管材描述等都是歷史 / downstream reference。
- FEM/APDL / shell / load-factor checks 目前是 candidate-relevant equivalent-physics validation / spot-check，不是 final composite、root fitting、wire hardware、rib joint 或 flight sign-off。
- Rib / rear spar / wire attach / root joint 是 downstream physical-realization 與 validation 問題；除非它們會改變 aero-structure closure candidate 排序，否則不要把它們升成上游主線。
- Horizontal / vertical tail 不是最後才補的外觀件；current pathfinder 已有 all-moving tail
  AVL audit v0、tail / CG / trim / stability screening v1 與 tail-aware closure evidence。
  目前 CG / trim / static / directional authority 可以在 managed CG row 下成立；P1 C04
  load-path surrogate 也已可進 coupon/local FEM。但 direct spar-pair stress-test、C07
  skin sag process、hardware/laminate detail 和 local FEM/coupon 尚未 sign-off，不能宣稱
  整機 aircraft-feasible。
- 主翼 mesh-native CFD / SU2 線仍暫停，不能拿來當 performance claim truth。

---

## 主要指令

### Mission / upstream concept

```bash
PYTHONPATH=src ./.venv/bin/python scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_upstream_concept_run \
  --worker-mode julia
```

快速 plumbing smoke，不能當工程證據：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir .tmp/birdman_upstream_concept_stubbed \
  --worker-mode stubbed
```

### Phase J pipeline sidecars

這些 script 主要用來重建或刷新 Phase J 目前的候選證據。執行前請先看
[CURRENT_MAINLINE.md](CURRENT_MAINLINE.md) 和 commit-history report，確認輸入 artifacts 是你要的版本。

```bash
PYTHONPATH=src ./.venv/bin/python scripts/fourier_avl_calibration_mvp.py \
  --report-json path/to/current_mission_coupled_spanload_search_report.json
PYTHONPATH=src ./.venv/bin/python scripts/structure_budgeted_z_state_search.py
PYTHONPATH=src ./.venv/bin/python scripts/loaded_shape_avl_recheck_mvp.py
PYTHONPATH=src ./.venv/bin/python scripts/tier2_loaded_shape_airfoil_mvp.py
PYTHONPATH=src ./.venv/bin/python scripts/aero_structure_closure_mvp.py
PYTHONPATH=src ./.venv/bin/python scripts/full_aircraft_tail_avl_audit_v0.py
PYTHONPATH=src ./.venv/bin/python scripts/vtail_cg_reference_sensitivity_v0.py
PYTHONPATH=src ./.venv/bin/python scripts/tail_aware_rib_rear_spar_sensitivity.py
PYTHONPATH=src ./.venv/bin/python scripts/tail_aware_aeroelastic_closure.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_rib_torsion_design_search.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_rib_collar_joint_design_search.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_spar_splice_design.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_p1_load_path_mass_closure.py
PYTHONPATH=src ./.venv/bin/python scripts/build_baseline_a_release.py
PYTHONPATH=src ./.venv/bin/python scripts/baseline_a_manufacturable_geometry_audit.py
```

只有在明確做歷史診斷時，才可以加
`--allow-legacy-medium-search` 讀 `birdman_mission_coupled_medium_search_20260503`；
輸出必須標成 legacy diagnostic，不能當 current Phase J evidence。

### Candidate structural spot-checks

```bash
PYTHONPATH=src ./.venv/bin/python scripts/phase15_candidate_load_factor_buckling_check.py
PYTHONPATH=src ./.venv/bin/python scripts/phase16_ccx_buckling_wire6_ramp.py
PYTHONPATH=src ./.venv/bin/python scripts/phase17_candidate_shell_buckling_tip_review.py
```

---

## 安裝

需要 Python 3.10 以上版本。

```bash
git clone https://github.com/Prosper1030/hpa-mdo.git
cd hpa-mdo
uv venv --python 3.10 .venv
source .venv/bin/activate
uv pip install -e ".[all]"
```

外部 VSPAero / OpenVSP / 翼型資料路徑請放在 `configs/local_paths.yaml`，不要直接改主 config：

```bash
cp configs/local_paths.example.yaml configs/local_paths.yaml
```

---

## 目前信任邊界

| 層級 | 目前定位 |
|---|---|
| Mission / concept search | 可用於新設計探索，但仍依賴 proxy 與 worker quality |
| Fourier-AVL / AVL realization | 目前主線氣動篩選與 spanload authority |
| Conservative load remap | rib / rear-spar sensitivity 前置 load gate，不是 aeroelastic sign-off |
| Empennage / trim / stability | 已有 tail contract v0、all-moving AVL audit v0、V-tail sensitivity v0，以及 tail/CG/trim/stability screening v1；tail-aware closure 顯示 managed CG、H-tail trim reserve、static margin、V-tail authority 保留，但 twist-source audit 指向 hybrid rib/stiffness rework；不可用未補償 mass shift |
| V-tail / CG reference sensitivity | v0 顯示 directional derivatives 可被 area/arm 推高；v1 進一步用 explicit CG-referenced AVL rows 驗證 Xnp convention、longitudinal trim、static margin 與 yaw authority |
| Loaded-Z / aero-structure closure | 目前 candidate 是否可推進的核心審查層 |
| Tier2 airfoil selection | 依 actual loaded-shape local `Cl/Re` 做 full-alpha 查表，但 query quality warning 必須保守處理 |
| Manufacturable geometry / discretization | WO-004 判定 smooth pathfinder 可供 release engineering 使用，但連續尺寸仍不是 shop drawing；WO-005 已補 RFQ screening station/span/splice manifest，尚未變成 drawing release |
| FEM/APDL / shell / load-factor | candidate spot-check，不是 final sign-off |
| Rib / root / wire hardware / composite detail | 開放 validation blockers，需要後續實體化與 detail evidence |
| SU2 / mesh-native CFD | WO-006 current-GO no-BL completion case 已有 finite 159-iteration SU2 force history，可作 route-level force evidence；WO-006H reopened campaign 仍標示 BL/core 與 finer no-BL hard limits。下一步是 BL/core conformal topology、near-wall/y+、force ownership 與 grid V&V；目前仍不是 drag/power performance truth |

---

## 給 AI Agent 的規則

- 先讀 [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md)，再讀本 README。
- 接 Baseline A / team work 時，再讀 [docs/AI_WORK_ORDER_PROTOCOL.md](docs/AI_WORK_ORDER_PROTOCOL.md)
  與 [docs/work_orders/QUEUE.md](docs/work_orders/QUEUE.md)。
- 不要從舊 Black Cat 004 文件、舊 OpenMDAO DAG 或 `examples/blackcat_004_optimize.py` 反推目前主線。
- 不要把 ignored output 或 legacy diagnostic 直接升格成 current evidence；要先建立 promoted trace。
- 如果完成一系列同屬同一個 idea 的任務，且它改變了目前主線、可用狀態、信任邊界或下一步優先順序，必須同步更新 README / CURRENT_MAINLINE。
- 工程輸出拿到後，要用航空工程角度檢查物理合理性，不要只說測試通過。

---

## License

MIT
