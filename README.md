# HPA-MDO：人力飛機新概念設計管線

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

## 2026-05-14 WO-006R15 Prism-Split Handoff Compatibility Probe

`scripts/probe_wo006r15_prism_split_handoff_compatibility.py` 把 R14 的 handoff
triangle mismatch 往下拆一層：檢查「把每個 near-wall hexa cell 切成兩個 prism，並逐 cell
選最佳對角線」是否足以讓 BL/core interface conformal。artifact 在
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r15_prism_split_handoff_compatibility_probe/`。

實跑 Baseline A current-GO 幾何結果：near-wall/receiver candidate 有 `26,880` 個 cells，
其中 `2,638` 個 touch core-facing boundary；最佳 per-cell prism split 只 match
`3166 / 5658` 個 R13 core interface triangles。unmatched markers 仍包含
`bl_outer_interface=2048`、`wake_edge_receiver=192`、`core_outer_edge_receiver=128`、
`core_wake_outer_match=64`、`core_wall_loop_cap=60`。WO-006I preflight 現在會優先讀 R15，
active blocker 是 `near_wall_prism_split_handoff_not_compatible`。

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
有 `60` 張 polygon 沒有 near-wall owner。R15 再證明逐 cell 兩-prism split 也只能 match
`3166/5658` core triangles，`bl_outer_interface` 仍有 `2048` triangles unmatched。因此
WO-006I preflight 現在把 active blocker 定位成
`near_wall_prism_split_handoff_not_compatible`；舊 direct-stageback PLC failure 只保留為
superseded diagnostic。下一步是讓 near-wall 與 core 共用同一個 interface tessellation，
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
