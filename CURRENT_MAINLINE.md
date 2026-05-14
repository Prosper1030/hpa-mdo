# HPA-MDO Current Mainline

## 0. Current Gate: Bounded WO-006 Data-Authority Restored

**更新日期：2026-05-14。** Baseline A data-authority 已恢復到足以讓 WO-006 進行 bounded
SU2 aero calibration；這不是 release truth、RFQ/procurement truth 或 final aircraft sign-off。
舊的 `baseline_A_release_system_ready` 是 historical/generated evidence under data-authority repair,
not active current truth；舊的 `carbon_tube_rfq_pack_ready` 也是 historical/generated evidence under
data-authority repair, not active current truth。`baseline_A_freeze_reasonable` 只能當舊 generated
screening evidence 讀，不是現行 release / procurement truth。

目前 authority 讀法：

- `98.5 kg` 是 current design gross mass authority，除非使用者明確改掉。
- `106.828608 kg` 是 suspect P1 screening aggregate，不是 current design mass truth、mission mass truth 或 RFQ truth。
- `34.332286 m` / `17.166143 m` 是 current pipeline span evidence，除非新的 authority manifest 取代。
- `16.5 m` 是 local/splice screening reference，不是 pipeline half-span、RFQ control span、shop span 或 procurement truth。
- WO-005 carbon tube RFQ pack 是 draft/vendor-screening only；不得當 purchase-ready、drawing-control 或 vendor-selection package。
- WO-006 只能作 bounded aero calibration；必須使用 `98.5 kg` 與 current pipeline span authority，除非明確做 sensitivity。
- WO-006 output 不是 release truth、不是 RFQ/procurement truth、不是 final aircraft sign-off。
- WO-006 active CFD route 已重設為 `canonical_hybrid_halfwing_v0`；唯一 active
  route state 是
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/manifest.yaml`。
  `scripts/check_canonical_hybrid_cfd_release.py` 會檢查這個 manifest。WO-006R25 到
  WO-006R30 只保留為 forensic evidence：R27/R28/R29/R30 證明 custom all-tet /
  global-star / owner-pyramid mixed handoff 不能再作 active CFD delivery。後續不得再開
  R31/R32 類型的 diagnostic commit，除非 `canonical_hybrid_halfwing_v0` 在 named phase
  gate 失敗且 manifest 指向該 gate。新 route 必須保留 prism/hexa BL + tetra core
  hybrid mesh，closure/tip/TE forces 必須分開，初始 3D viscous smoke 使用 geometry
  incidence + `AOA=0`，且保守 numerics 跑完不算成功。
  GPT Pro rescue 方向保存於
  `docs/reports/wo006_cfd_external_rescue_reference.md`；它只能作 stuck 時的工程參考，
  不能取代 manifest gate。
- WO-006 Phase 1 `TOOLCHAIN_PASS` 已通過。Artifact 在
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/toolchain_sanity/`；
  三個 2D wall-resolved `INC_RANS/SA` sanity cases 全部 completed
  且 force window stable：NACA4412 `CD=0.0207559`、current root DAE31
  `CD=0.0211785`、current tip `CD=0.0204750`。root DAE31 的 closed/cusped TE 會讓
  Gmsh BL 產生負品質 quad；Phase 1 只在 2D sanity mesh 將 closed TE 正規化成
  `0.002c` finite TE cap。這是工具鏈 sanity，不是 3D CFD performance claim。
- WO-006 Phase 2 `PRESSURE_SANITY_PASS` 已通過，`manifest.yaml` 現在是
  `passed_gate_statuses=[TOOLCHAIN_PASS, PRESSURE_SANITY_PASS]`，下一個 gate 是
  `ROUTE_SMOKE_PASS`。Artifact 在
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/pressure_sanity/`：
  half-wing、root symmetry、Euler/slip pressure-only、`AOA=0`，primary force 只監測
  `wing_upper + wing_lower`。正式 run 在 `383` iterations 收斂，最後
  `CL=0.365344`、`CD=0.0177873`、`CMy=-0.0706675`，last-100 `CL/CD` relative span
  約 `0.00445` / `0.00553`。SU2 dual quality gate 也過：min orthogonality
  `19.4086 deg`、max CV face-area aspect ratio `7487.37`、max CV sub-volume ratio
  `186725`。這只清掉 pressure/geometry/marker/reference sanity；不是 viscous BL
  route-smoke、不是 y+、不是 grid ladder，也不能被讀成 final drag。
- WO-006 Phase 3 `ROUTE_SMOKE_PASS` gate 已實作，但目前未通過。第一個
  canonical Gmsh topological BL extrusion path 有 hybrid topology（default case
  `15,600` prism BL cells + `2,857` core tets），且 marker split 保持
  `wing_upper` / `wing_lower` / `tip_wall` / `te_wall` / `closure_wall`；但
  SU2 `INC_RANS/SA` 快速發散，solver dual quality 仍有 max CV sub-volume ratio
  約 `1.81024e8`。Phase 3 gate 現在會把這種 `1e8` 等級 sub-volume ratio 擋下，
  避免被誤讀成只差 solver tuning。pps12/s6 one-iteration force breakdown 顯示
  `tip_wall`、`te_wall`、`closure_wall` 的 CD contribution 很小，主要不合理 drag
  來自 `wing_upper + wing_lower` primary wall；AOA=-4、laminar、low-CFL、Green-Gauss
  diagnostics 也沒有讓 route 變成可接受 viscous smoke。下一步不是 R31-style
  local patch，而是 mesh-native owned BL topology / direct hybrid SU2 handoff。
- WO-006 Phase 3 direct surface-prism/core handoff 已有 topology 原型，但仍是 blocked
  evidence，不是 route pass。新增的 writer 會以 mesh-native surface triangles 直接長出
  prism BL，再把 `bl_outer_interface` 併入 Gmsh tetra core；輸出的 SU2 mesh 保留
  `wing_upper` / `wing_lower` / `tip_wall` / `te_wall` / `closure_wall` /
  `root_symmetry` / `farfield` marker ownership，且不輸出 internal
  `bl_outer_interface` marker。default 24-layer probe 是 `15,600` prism BL cells +
  約 `4,750` core tets，node tag integrity pass。Gmsh core 改用
  `Algorithm3D=1`，因為 `Algorithm3D=10` 在這個 discrete-interface/geo-farfield
  mix 會產生含 node `0` 的 invalid tetra。工程判讀：這只清掉 writer/topology
  blocker；SU2 還沒過。該 probe 的 dual quality 仍是 min orthogonality
  `1.60111 deg`、max CV face-area aspect ratio `122600`、max CV sub-volume ratio
  `158295`；Euler/slip 以初始 `CD≈0.2555` 開場並在 iter 10 divergence，RANS 以
  初始 `CD≈0.3741` 開場並在 iter 9 divergence。下一個 named blocker 應鎖定
  surface-normal/prism distortion/root-symmetry-hole/pressure-only stability，而不是
  numerics tuning 或 closure marker repair。
- WO-006R8 新增 Basic airfoil BL sanity benchmark，專門回答「工具鏈在簡單 viscous case
  上是否先把 drag 量級算壞」：2D `NACA4412`、`Re≈5.03e5`、`alpha=4 deg`、
  Gmsh BL quads + SU2 `INC_RANS/SA` no-slip wall。最新 `solver_5000` case 在
  `4597` iterations 達成 SU2 `Cauchy[CD] < 1e-6`，mesh `25,168` cells /
  `15,190` nodes / BL quads `4,833`，最後 `CL=0.887615`、`CD=0.021682`、
  `CMz=0.100707`。最後 100 iter `CL/CD/CMz` relative span 約 `0.0046%` /
  `0.0456%` / `0.0038%`，所以它通過簡單 route 的 `0.0XX` drag-order 與
  force-stability sanity；但它仍是 2D diagnostic，不是 Baseline A CFD evidence
  或 mesh ladder completion。
- WO-006R9 已把 R7 bad-pyramid core blocker 改成 checkable Baseline A evidence：
  preserved core boundary 以 triangulated representation 實跑 HXT tet-fill，core mesh
  `28,410` nodes / `6,005` cells，全部 tetra，`pyramid=0`，non-positive SICN/SIGE/volume
  皆 `0`，mesh quality gate `pass`。這只修掉 core quad-to-pyramid quality family；
  BL/core coupling 仍 `partial`，`wake_cut=64` 與 `span_cap=62` core faces unmatched，
  BL block 端還有 `6272` 個非 wall boundary faces 未 match，且沒有 merged mixed SU2 mesh。
  因此仍不能跑 medium/fine CFD ladder 或解讀 CL/CD/Cm。
- WO-006K 已修正 mesh-native SU2 incompressible RANS coefficient normalization：
  runtime config 現在使用 `INC_NONDIM=INITIAL_VALUES`，WO-006 grid setup gate 也會拒絕
  非 `INITIAL_VALUES` 的 CFD ladder。這是必要修正，但不是 high-CD 的唯一原因：
  修正後 no-BL route smoke 仍是 alpha 5 deg `CD≈0.439`、alpha 0 deg `CD≈0.291`；
  同一 large-domain BL mesh 的 RANS/SA force-breakdown probe 仍是 `CD≈0.571`，其中
  pressure 約 `0.401`、friction 約 `0.170`。因此 `CD≈0.5-0.6` 不能被視為收斂 CFD；
  必須先修 pressure/near-wall/BL prism shape，再談 medium/fine ladder。
- WO-006K 也把 BL quality gate 補成 CFD ladder blocker：boundary-layer
  `p01 minSICN < 0.005` 現在會 fail，而不只是 warning。舊 larger-domain BL sanity mesh
  用新 gate 判讀為 fail（`p01_min_sicn=1.47e-4`、`min_sicn=8.91e-6`）。低成本 BL
  參數 probe 顯示減層、變薄、或改 `max_min_angle` triangulation 仍有 non-positive
  SICN/SIGE；spanwise subdivision 從 1 提到 4 會改善最壞負 SICN，但仍 fail。worst
  hotspot 在 `y≈±12.36, ±12.87, ±13.39 m`、`x≈0.81-0.85 m`，對應 `y=12.016 m`
  DAE31 到 `y=14.076 m` CST tip airfoil transition band。下一步仍是修
  TE/tip/transition 近壁幾何與 prism shape，不是硬跑更多 solver iterations。
  `scripts/diagnose_wo006k_bl_hotspots.py` 現在可把 Gmsh BL element quality hotspots
  映射回 Baseline A section table；目前
  `wo006k_bl_hotspot_diagnosis/` artifact status 是 `blocked`。
- WO-006L 把 mesh-native Gmsh BL writer 的 experimental stageback selector 從
  global-x 誤判修成 local-chord targeting：wall surface records 現在有
  `centroid/min/max x/c` 與 `abs y`，並可用 `x_reference=max` 加 `abs_y` band
  鎖定 DAE31 -> CST tip transition aft/TE hotspot。pps16/span4 selector-only probe
  顯示 `3900` 個 wall surface records、`540` 個在 `|y|=12.0-14.2 m` transition
  band；`max x/c >= 0.995` 且只限該 band 會排除 `52` 個 faces（`0.998` 為 `36`）。
  artifact 在 `wo006l_te_stageback_selector_probe/`。但直接 Gmsh 3D localized
  stageback probe 超過 6 分鐘仍零 artifact，觀察 CPU 約 `100%`、RSS 約 `865 MB`；
  這是 topology/runtime closure 問題，不是 memory hard limit，也不是 CFD evidence。
  下一步仍是 topology-preserving transition/interface closure；不得把它當 medium/fine
  SU2 ladder 起點。
- WO-006M 進一步把 stageback selector 改成 face-coherent：同一個 source face 只要有一個
  triangle hit，就整個 face 一起排除，避免半個 source face 形成 BL/core seam；同時
  BL side surfaces 現在只保留接觸 excluded-wall boundary curves 的 surfaces，並在
  Gmsh failure 中輸出 surface-role diagnostic。這修掉了 side-vs-side overlap family，
  但 current-GO direct no-BL-hole stageback 仍失敗：`x/c>=0.998, |y|=12.0-14.2 m`
  和較窄的 `|y|=12.3-13.0 m` 都落到 `stageback_plc_segment_facet_intersection`。
  因此直接挖 no-BL hole 不是 runtime 修法；下一步必須是 receiver/sleeve/staged
  transition topology。舊 span8 BL meshes 也不能被拿來補完成：用目前 gate 重判，
  `wing005` 11.28M cells 雖然沒有 non-positive BL elements，但 `BL p01 minSICN=0.00219`
  低於 `0.005` blocker threshold，仍不是 CFD-grade ladder rung。
- WO-006N 已把上述 direct stageback artifact 接進
  `scripts/run_wo006i_grid_convergence_campaign.py` setup gate：campaign 會讀
  `wo006m_face_coherent_stageback_mesh_probe/summary.json` 與
  `wo006m_narrow_stageback_mesh_probe/summary.json`，若 raw Gmsh error 是
  `PLC Error` / segment-facet intersection，即使舊 artifact 的 diagnostic family
  名稱較粗，也會轉成 `direct_stageback_topology_plc_segment_facet` blocker。這是 solver
  preflight blocker，不是可忽略 warning；下一步仍是 receiver/sleeve/staged transition
  topology，而不是用 direct no-BL-hole route 硬跑 medium/fine。
- WO-006 current-GO no-BL CFD completion evidence 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006_current_go_cfd_completion/`。
  Completion gate 是 `pass`：newly generated full-span current-GO mesh 有 `490,116`
  tets、`wing_wall` / `farfield` marker audit pass、no non-positive volume/SICN/SIGE，
  SU2 跑完 `159` iterations 並寫出 finite force history（`CL=1.106421874`、
  `CD=0.4752310368`、residuals finite、no NaN/Inf）。這是 route-level force
  evidence，不是 BL/y+ viscous drag calibration、grid-converged aero model、Baseline A
  reopen evidence 或 performance truth；`CD` 明顯偏高，必須保留 no-BL trust boundary。
- WO-006R11 新增 core-facing loop closure probe：
  `scripts/probe_wo006r11_core_facing_loop_closure.py` 接在 R10 wall-edge gap audit 後，
  把 `64` 條 core-facing open edges 拆成左右兩個 `32`-node loops，materialize 成
  `core_wall_loop_cap` surface。Baseline A artifact 在
  `wo006r11_core_facing_loop_closure_probe/`；實跑 pre-cap topology 是
  `not_watertight` / `64` bad edges，post-cap topology 是 `watertight` /
  `bad_edge_count=0`，cap face count `64`，non-positive cap area `0`。判讀：這修到
  core-facing surface topology 可進 core mesh probe，但還不是 merged BL/core SU2 handoff；
  core/farfield mesh、merged quality、SU2 marker/readability、y+、solver ladder 都未完成。
- WO-006R12 新增 loop-cap core mesh probe：
  `scripts/probe_wo006r12_loop_cap_core_mesh_probe.py` 直接把 R11 materialized
  `core_wall_loop_cap` surface 作為 inner boundary 交給 Gmsh core tet writer。Baseline A
  實跑 artifact 在 `wo006r12_loop_cap_core_mesh_probe/`，結果是
  `loop_cap_core_mesh_probe_blocked`：HXT core fill 約 `96.6 s` 後失敗，Gmsh log 顯示
  duplicate point filtering、missing facets recovery 與 exactly self-intersecting facets。
  R12 幾何 audit 定位到 `70` 組 exact duplicate coordinates；座標 weld 後會有 `8` 條
  non-manifold bad edges，sample 位在 `wake_edge_receiver` / `core_wall_loop_cap` /
  `core_tip_receiver_outer` 的 tip/wake loop-cap seam。這代表 R11 的 index topology
  watertight 還不是 PLC-valid core surface；下一步要修 sharp-TE/tip/wake seam 的幾何重合，
  不能跑 SU2 ladder。
- WO-006R13 新增 loop-cap geometric seam repair：
  `scripts/probe_wo006r13_loop_cap_geometric_seam_repair.py` 對 R12 blocker 做最小修復：
  exact duplicate coordinates weld，並移除 weld 後同 marker / 同 node set 的重合 seam
  faces。Baseline A artifact 在 `wo006r13_loop_cap_geometric_seam_repair_probe/`。實跑
  repair 從 `28,877` vertices / `2,868` faces 變成 `28,807` vertices / `2,860` faces，
  drop `8` 張 duplicate seam faces，post-repair duplicate groups `0`、welded bad edges
  `0`。HXT core fill 成功，core mesh `29,993` nodes / `9,677` tetra cells，SU2 boundary
  ownership `pass`，non-positive SICN/SIGE/volume 都是 `0`；但仍有
  `very_low_min_gamma`、`very_low_min_sicn`、`low_p01_gamma` quality warnings。這是
  core/farfield mesh-probe progress，不是 merged BL/core handoff 或 CFD evidence。
- WO-006I CFD setup gate reset 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006i_setup_preflight_reset/`。
  Verdict 是 `GOAL_STATUS=INCOMPLETE`、`CFD_STATUS=mesh_ladder_incomplete`，且
  `baseline_a_wall_resolved_bl_preflight_gate_v1` 在 solver 前 blocked：目前 no-BL
  setup 缺 conformal BL/core handoff、postprocessed near-wall y+ 與 CFD-grade setup
  gate。這個 gate 現在會優先讀 WO-006R17 hybrid tet/prism split artifact：R13 已把
  core mesh probe 推到 quality/marker pass，舊 direct-stageback PLC failure 也只保留為
  superseded diagnostic，不再當 active blocker。R14 顯示 R13 core surface 與
  near-wall volume 雖有 `2800/2860` polygons 對上，active triangulated interface 只有
  `1808/5658` triangles conformal；R15 單軸 prism split 只能 match `3166/5658`，
  R16 三軸 split search 可提升到 `5274/5658` 並清掉 `bl_outer_interface=2048`，但
  `wake_edge_receiver=192`、`core_outer_edge_receiver=128`、`core_wall_loop_cap=60` 仍
  unmatched；R17 hybrid tet/prism split 可提升到 `5590/5658`，但仍有
  `core_wall_loop_cap=60` 無 candidate owner，以及 `wake_edge_receiver=4` /
  `core_tip_receiver_outer=4` split 不相容。WO-006R18 現在把這些 residual 定位成
  兩個 `core_wall_loop_cap` fan，每個 `30` triangles / `31` nodes，位在
  `y≈±17.201-17.202 m` tip 外側，另有兩個 `tip_receiver/left_tip` cells
  (`26110`、`26111`) 各自 target `6` triangles、只 match `4`。WO-006R19 驗證
  loop-cap owner pyramid repair basis：`60` 個 `physical_wall_edge_receiver`
  quads 可形成 `60` 個 owner pyramids，`60/60` match `core_wall_loop_cap`
  triangles，且 owner volume 全為正（約 `6.26e-7` 到 `6.52e-5 m^3`）。WO-006R20
  接著只針對 R17 hybrid audit 中 `unmatched_triangle_count > 0` 的兩個
  `tip_receiver/left_tip` cells 做 cell-center star tessellation：target triangles
  `12/12` matched，`core_outer_edge_receiver=4`、`core_tip_receiver_outer=4`、
  `wake_edge_receiver=4`，star-tet volume 全為正（約 `2.71e-7` 到 `3.45e-7 m^3`），
  R19/R20 後的 R17 residuals 為 `{}`。因此前置狀態已推進到
  `handoff_repair_basis_ready_mixed_mesh_pending`。WO-006R21 又補上 writer 前的全域 assembly
  gate：把 R17 selected tet/prism patterns 套到 `26880` 個 candidate cells 後，會形成
  `161280` 個 local split elements，但目前有 `7960` 個 internal split leak faces 和
  `64` 個 non-manifold split faces。這表示 local core-face match 不能直接升級成 final mixed
  mesh。WO-006R22 進一步測試全域一致 cell-center star split：同一批 `26880`
  candidate cells 可產生 `322432` 個非退化 tet elements，target triangles
  `5594/5594` match，internal split leaks `0`，non-manifold split faces `0`，
  non-positive tets `0`；剩下 `128` 個 degenerate star triangles 需要 sharp-edge
  cell-type reduction。active blocker 現在是
  `near_wall_global_star_split_degenerate_cells`，不是 R21 的全域 split nonconformal、
  R10 wall-edge dependency、R12 geometric self-intersection、舊 direct-stageback route，
  或仍未知的 left-tip residual；WO-006I preflight 的 data-authority-restored mesh repair
  target 是 `reduce_degenerate_star_cells_before_mixed_mesh_writer`。WO-006R23 已把這個
  blocker 定位成 `32` 個 `wake_receiver` cells / `128` 個 degenerate triangles，marker
  皆為空字串，bounds 約 `x=0.6569-1.2772 m`、`y=-17.166143..17.166143 m`、
  `z=-0.0950..2.5975 m`；下一刀應是 wake-receiver local cell-type reduction /
  degenerate-cell special casing，不是 SU2 iteration、BL physics 或全域 split assignment。
  WO-006R24 已驗證這些退化 triangles 全部可當空 marker wake-receiver zero-area
  cull/reduction basis；WO-006I preflight 現在的 active topology state 是
  `handoff_degenerate_cull_basis_ready_mixed_mesh_pending`，blocker 變成
  `near_wall_merged_mesh_handoff_missing`，recommended repair 是
  `write_culled_global_star_mixed_su2_handoff_and_yplus_probe`。這仍不是 mixed SU2 mesh、
  marker/quality pass、y+ 或 solver ladder。
- WO-006R25 已把 R24 basis 寫成第一個 culled mixed SU2 handoff probe：
  `culled_global_star_mixed_handoff.su2` 有 `56,873` nodes / `332,221` volume
  elements，全部 tetra；mixed volume quality `pass`，non-positive volume `0`。
  R25 同時把 `68` 個已由 final boundary audit 證明為 exterior 且可回對到
  `wing_wall` / `physical_wall_edge_receiver` 的 closure faces 補入 `wing_wall`
  marker，因此 marker counts 是 `wing_wall=1924`、`farfield=2366`。但 final
  volume-boundary marker audit 仍 `fail`：還有 `68` 個 exterior faces 沒有 SU2
  marker，unmarked area 約 `0.0759 m^2`，集中在 loop-cap fan / wake-edge 對接區。
  WO-006I preflight 現在會把 active blocker 推進成
  `near_wall_mixed_su2_boundary_marker_blocked`，recommended repair 是
  `localize_and_close_remaining_mixed_su2_boundary_leaks_before_solver`。這代表 writer
  路線已活、BL first-layer 估算仍是 `y+≈1.04` 量級，但仍不能跑 medium/fine solver
  ladder，也不能解讀 Baseline A CL/CD/Cm。
- WO-006R26 已把 R25 剩餘 `68` 個 unmarked exterior volume faces 做成 marker
  ownership localization / repair-plan artifact：
  `wo006r26_remaining_boundary_leak_localization_probe/`。實跑結果沒有 unclassified
  face，總 unmarked area `0.075898249 m^2`；adjacent source 是
  `loop_cap_owner_pyramid_tet_split=64`、`core_tet_mesh=2`、
  `culled_global_star_near_wall=2`，幾何分類是
  `loop_cap_owner_pyramid_exterior=60`、`loop_cap_physical_wall_edge_closure=4`、
  `candidate_wake_edge_receiver_boundary=2`、`core_wake_edge_receiver_boundary=2`。
  repair plan 是只把這些已定位的 solid closure faces 補到 `wing_wall`。WO-006I
  preflight 現在會把 active blocker 推進成
  `near_wall_mixed_su2_boundary_marker_repair_not_applied`，並把舊 direct-stageback PLC
  blocker 視為已由 core/mixed route supersede。下一步是把 R26 repair 寫回 mixed SU2
  writer 並重跑 marker/quality audit；在 audit pass 前仍不能跑 medium/fine solver ladder
  或解讀 Baseline A CL/CD/Cm。
- WO-006R27 已套用 R26 bounded marker repair，寫出
  `wo006r27_apply_boundary_marker_repair_probe/culled_global_star_mixed_handoff_r27_repaired.su2`。
  mesh 仍是 `56,873` nodes / `332,221` tetra volume elements；marker counts 是
  `wing_wall=1992`、`farfield=2366`。final boundary marker audit 已 `pass`：
  exterior boundary faces `4358/4358` marked，`unmarked=0`、`extra=0`、duplicate
  marker faces `0`、nonmanifold volume faces `0`；mixed volume quality `pass`，
  non-positive volume `0`。WO-006I preflight 現在不再報 R25/R26 marker blocker，也會把
  direct-stageback PLC failure 視為已由 core/mixed route supersede。active blockers 回到
  solver setup 層：目前預設 setup 仍是 no-BL diagnostic、缺 solver-postprocessed y+，
  且沒有 coarse/medium/fine rungs。問題/解法 register 在
  `docs/reports/wo006_cfd_problem_solution_register.md`。
  先前 `wo006i_grid_convergence_campaign/`
  的 `0.49M`、`1.61M`、`3.05M`、
  `3.63M` finite no-BL RANS/SA histories 已被 quarantine 成 diagnostic evidence；
  它們 force stability fail，且沒有 BL/y+，所以不能當 low-confidence CFD、grid convergence、
  drag/power truth 或 Baseline A reopen evidence。後續若要跑 medium/fine，必須先修
  BL/BC/near-wall setup；重放 no-BL 只能用 diagnostic flag，不能完成 CFD goal。
- WO-006R28 已把 R27 repaired mesh 接到 wall-resolved SU2 route-smoke：
  `scripts/probe_wo006r28_r27_su2_route_smoke.py` 產生 `INC_RANS/SA`、
  `INC_NONDIM=INITIAL_VALUES`、`MARKER_HEATFLUX=(wing_wall,0.0)`、
  `MARKER_FAR=(farfield)` 的 config，並 gate config marker match、SU2 history
  stability、CD-order sanity，以及 solver log 的 dual-control-volume quality。FDS/MUSCL
  case 可讀 R27 mesh/markers，但 iteration `5` divergence；SU2 log 給出
  min orthogonality `0.00108069 deg`、max CV face-area aspect ratio `5.15199e8`、
  max CV sub-volume ratio `2.07841e11`。保守 JST、`MUSCL_FLOW=NO`、`CFL=0.02`
  case 可跑滿 `180` rows，但 `CD=0.3916`，last-100 force/residual stability fail。
  因此 active blocker 已從 marker ownership 推進到 BL/core transition sizing /
  mixed-mesh dual-volume quality；在這個 mesh-quality blocker 修好前，不能推
  medium/fine ladder，也不能把有限 CL/CD/Cm 當 low-confidence CFD。
- WO-006R29 是 R28 後的 mesh-source diagnostic：
  `scripts/probe_wo006r29_dual_quality_source_localization.py` 重建 R25/R27 mixed
  mesh provenance，掃描 internal shared-face adjacent tet volume jump。實跑 artifact
  在 `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r29_dual_quality_source_localization_probe/`：
  `1,432` 個 internal faces 有 volume ratio `>=1000`，最大 ratio `29263.77`，
  最差 source pair 是 `culled_global_star_near_wall|culled_global_star_near_wall`。
  這低於 `1e6` blocker threshold，無法解釋 R28 SU2 log 的 max CV sub-volume ratio
  `2.07841e11`。工程判讀是 R29 排除了「單純 primal adjacent tet volume jump」
  這條解釋路線；下一步要定位 SU2 dual/control-volume metric 本身，而不是把 R29
  當 mesh repair 或 CFD evidence。
- WO-006R30 已把 R28 的 `CV Sub-Volume Ratio` 病灶 localization 到 SU2-style
  vertex dual subvolume 層級：
  `scripts/probe_wo006r30_su2_dual_subvolume_localization.py` 依照 SU2
  `CPhysicalGeometry::ComputeMeshQualityStatistics` 的 max/min sub-element volume
  思路掃 R25/R27 mixed mesh provenance。實跑 artifact 在
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r30_su2_dual_subvolume_localization_probe/`：
  `max_cv_sub_volume_ratio=207840927876.89658`，對上 R28 solver log 的
  `2.07841e11`；最壞 point `56784` 位於
  `(-2.684534382258478, 21.21191727545568, 1.867804964000869)`，
  marker 是 `farfield`，incident source counts 是 `{"core_tet_mesh": 1704}`。
  這份 evidence 現在是 forensic-only：它說明 R27/R28 custom all-tet handoff 的
  core/farfield tet construction 已經不適合作 active route。不得把它解讀成 R31 繼續
  local patch 的入口；下一步回到 `canonical_hybrid_halfwing_v0` 的 phase gate。
- WO-006I grid-convergence gate 也會拒絕短尾段 force stability：CL/CD/Cm stability
  summary 必須至少覆蓋 `100` 個 iterations，CL/CD relative spread 需在 `1%` 內、Cm
  absolute spread 需在 `0.005` 內；舊 summary 若只用 25-row tail 宣稱 pass，會被
  `*_force_stability_window_too_short` blocker 擋下。這只是數值穩定最低門檻，不會覆蓋
  BL/y+ 或 CD-order sanity gate。
- WO-006J faceted BL setup probe 已把 Gmsh BL writer 接上 `surface_triangulation_policy`，
  預設 `shorter_diagonal`，不改 Baseline A 外形。低成本 current-GO BL probe 顯示 fixed
  diagonal 有 `93` 個 non-positive BL volumes；shorter diagonal 把 non-positive volume 清為
  `0`，但仍有 `10` 個負 SICN/SIGE prism，對稱集中在 `y≈±13.88 m`、`x≈0.790 m` 的
  DAE31 -> CST tip airfoil transition aft/TE 附近。BL 厚度 sweep 不會消掉這 10 個壞 shape，
  pps32/span2 反而回到已知 `Unknown curve -1550`。因此這是 BL setup repair progress，
  不是 CFD coefficient evidence；下一步是 transition surface / TE local BL prism shape 修復。
- WO-006J BL/no-slip ladder 不能只看 force-history stability：目前 0.48M 到 2.51M
  rungs 的 `CD≈0.61`，4.53M partial rung 到 772 iterations 仍在 `CD≈0.593`，
  比 HPA main-wing expected `0.0XX` drag order 高一個數量級以上。這些結果一律當
  high-drag setup/domain diagnosis，不是 low-confidence CFD。新的 gate 會拒絕
  `CD > 0.15` 的 HPA main-wing rung，即使尾段 CL/CD/Cm 看似穩定；BL stability ladder
  預設 farfield 從 route-smoke `2c/4c` 改為 `20c/40c`，但 larger-domain sanity case
  仍是 `CD≈0.642`。新增 `scripts/diagnose_wo006j_drag_source.py` 可重跑 force-breakdown /
  surface-pressure localization；目前診斷顯示 Euler/slip-wall `CD≈0.298` 是 pressure-only，
  RANS/BL `CD≈0.642` 分解成 pressure `≈0.492` + friction `≈0.150`。新增
  `scripts/probe_wo006j_numerics_sensitivity.py` 可重用同一 large-domain Euler mesh
  做 FDS/MUSCL 敏感度診斷：原 source config 的 `FDS + MUSCL_FLOW=NO` 只能當
  low-order diagnostic，無限制 MUSCL 在 12 iter 內發散；保守
  `FDS + MUSCL + VENKATAKRISHNAN`、`CFL=0.02` 跑滿 300 iter 後仍是
  `CL=0.715715`、`CD=0.447702`、`CMy=-0.198644`，CD gate fail。因此下一步不能
  只跑更大網格、更多 iteration，或只把 MUSCL 打開；要先修 pressure/geometry/numerics
  artifact 與 BL friction setup，之後才重跑同幾何、同 physics 的 coarse/medium/fine ladder。
- WO-006O 已把 local force-stability 判讀從短尾段 `25` rows 改成 `100` iteration
  window，CL/CD relative spread 門檻收緊到 `1%`，Cm 仍用 `0.005` absolute spread。
  這表示 CFD 不必機械式跑滿 1000 iteration 才能判穩，但最後 100 iteration 必須證明
  force history 沒有明顯漂移；同時這只代表數值穩定，不能覆蓋 `CD≈0.5-0.6` 的物理
  量級錯誤或 BL/near-wall/setup blocker。
- WO-006P 已把 spanwise refinement repair 假設改成 bounded runtime probe：
  `scripts/probe_wo006p_bl_span_refinement_runtime.py` 對 `pps16_span8_thin12_g118` 與
  `pps16_span16_thin12_g118` 各跑 `240 s` timeout，artifact 在
  `wo006p_bl_span_refinement_runtime_probe/`。兩者都 timeout，peak sampled RSS 約
  `205 MB` / `227 MB`，沒有 BL gate pass candidate；這不是 RAM hard limit，也不能拿來
  啟動 medium/fine CFD ladder。span subdivision 對先前 span2/span4 的最壞 SICN 有改善
  趨勢，但 span8/span16 local Gmsh runtime 不成立，下一步仍是 topology/near-wall shape
  修復。
- WO-006Q 已把 transition-band near-wall root cause 量化成純 geometry probe：
  `scripts/probe_wo006q_transition_normal_jump.py` 對 current Baseline A station airfoils
  計算相鄰 station wall normal / aft shape jump。artifact 在
  `wo006q_transition_normal_jump_probe/`。DAE31 ↔ CST tip transition interval
  `|y|=12.0163` 到 `14.076237 m` 在 aft `x/c>=0.75` 有 `45.57 deg` max normal jump
  與 `0.0543` normalized aft shape delta，超過 `20 deg` / `0.03` blocker threshold。
  這和 WO-006K BL hotspot 位置一致；下一步應做 receiver/sleeve 或 local
  airfoil-transition smoothing 的 near-wall topology repair，再重新嘗試 BL quality gate。
- WO-006R 已測 local transition sleeve BL quality：`scripts/probe_wo006r_local_transition_sleeve_bl_quality.py`
  只在 DAE31 ↔ CST transition interval 插入線性 intermediate stations，不改 authority
  wall surface（`external_shape_changed=false`）。artifact 在
  `wo006r_local_transition_sleeve_bl_quality_probe/`。`transition_subdivisions=4` 仍有
  `6` 個 non-positive BL SICN；`8` 與 `16` 已把 non-positive BL SICN 清成 `0`，
  但 `BL p01 minSICN` 仍只有約 `7.02e-05` / `6.74e-05`，未接近 `0.005` CFD gate。
  判讀：local sleeve 消掉最壞 inversion，是必要進展，但單靠線性插站不足；下一步要做
  near-wall receiver surface / local airfoil-transition smoothing，目標是把 p01 SICN 提升
  兩個數量級以上後才可重啟 SU2 route smoke。
- WO-006S 用既有 hotspot tool 重判 WO-006R `local_transition_subdiv8_thin12_g118`
  mesh，artifact 在 `wo006r_subdiv8_hotspot_diagnosis/`。結果 status 仍是
  `blocked`：worst BL `minSICN=8.91e-06`、worst `minSIGE=0.00710`，top 80
  hotspots 全部在 aft/TE（`x/c≈0.99`），其中 6 個仍在 DAE31 ↔ CST tip
  airfoil-transition band。這把目前 blocker 從「可能是 span/iteration 不夠」收斂成
  TE/wake/transition receiver topology 或 owned-BL/core envelope 問題；`subdiv8`
  和 `subdiv16` 不能當 medium/fine CFD ladder 起點。
- WO-006T 已把全展向 TE stageback 修法做成 bounded runtime probe：
  `scripts/probe_wo006t_te_stageback_runtime.py` 對 `x/c>=0.99, x_reference=max`
  跑 HXT 與 non-HXT alg1，artifact 在 `wo006t_te_stageback_runtime_probe/`。HXT 約
  `15.1 s` 失敗於 `stageback_hxt_requires_triangle_boundary_surfaces`
  （HXT only supports triangles），alg1 約 `15.1 s` 失敗於
  `stageback_boundary_recovery_failed`；兩者 peak sampled RSS 約 `110 MB`，不是
  hardware/RAM limit。判讀：直接 global TE stageback 不能當 CFD mesh 修法；下一步
  必須是 owned TE/wake receiver 或 BL/core envelope repair，先讓 TE/wake/transition
  拓樸 watertight 且 quality gate pass。
- WO-006U 已把 R5 BL/core envelope blocker 拆成純 topology evidence：
  `scripts/probe_wo006u_bl_core_envelope_topology.py` 不跑 Gmsh / SU2，直接檢查 owned
  BL block boundary，artifact 在 `wo006u_bl_core_envelope_topology_probe/`。current
  core-interface surface 是 watertight（`0` bad edges），但 tempting
  `full_non_wall_boundary` 不是 watertight，有 `124` 條 bad edges；全部分類為
  `candidate_open_edge_touches_wing_wall`，marker combo 是 `span_cap=60`、`wake_cut=64`。
  判讀：R5 的 next repair 不是盲掃 Gmsh algorithm，也不是把 all non-wall faces 直接
  丟給 core mesh；必須先建 owned TE/wake receiver/envelope，把 wall-touching
  wake/span-cap edge closure 定義清楚，再重跑 core tetra / mixed SU2 handoff gate。
- WO-006V 已把 TE/wake receiver route 變成可數 topology candidate：
  `scripts/probe_wo006v_wake_receiver_topology.py` 建立 receiver cells 連接 upper/lower
  wake connector gap，artifact 在 `wo006v_wake_receiver_topology_probe/`。實跑建出
  `768` 個 receiver cells，可 match `1536 / 1600` 個 BL wake-cut faces，並 match
  `32 / 32` 個 core wake-cut faces；但剩下 `64` 個 BL wake-cut faces 全部 touch
  `wing_wall`，receiver 也留下 `32` 個 TE-base faces。判讀：wake receiver 是正確修路方向，
  但 TE-base ownership 仍未定義；在它解掉前不能宣稱 BL/core handoff ready，不能跑
  medium/fine SU2 ladder 當 CFD evidence。
- WO-006W 已把 TE-base ownership 從 blocker 變成 stitchability evidence：
  `scripts/probe_wo006w_te_base_pairing.py` 檢查 WO-006V 剩下的 TE-base wake-cut faces
  是否為 sharp trailing-edge 幾何重合 wake seam pair，artifact 在
  `wo006w_te_base_pairing_probe/`。實跑結果 `64` 個 TE-base faces 形成 `32` 組
  coincident pairs，`unpaired=0`；`32` 個 receiver-base faces 全部 degenerate，
  `max_receiver_base_area_m2=0.0`。判讀：下一步可以嘗試 explicit seam stitching/removal，
  但不能把它當新的 physical wall 或 SU2 boundary，也尚未達到 BL/core handoff ready。
- WO-006X 已把 wake ownership 做成 stitched accounting gate：
  `scripts/probe_wo006x_stitched_wake_handoff_gate.py` 合併 WO-006V receiver matching 與
  WO-006W sharp-TE seam pairing，artifact 在 `wo006x_stitched_wake_handoff_gate/`。實跑
  `1600` 個 BL wake-cut faces 中，`1536` 個由 receiver match、`64` 個由 TE-base seam
  stitch account，`remaining_unowned_bl_wake_cut_face_count=0`；core wake-cut 也
  `32 / 32` match。判讀：wake ownership 可進入 stitched topology 實作，但 span-cap
  ownership 仍 `pending`，merged mesh quality / SU2 readability 未過 gate，因此不能跑
  medium/fine SU2 ladder。
- WO-006Y 已把 span-cap ownership blocker 量化：
  `scripts/probe_wo006y_span_cap_ownership.py` 檢查 owned BL span-cap faces 與 core
  interface span-cap faces 的 native match，artifact 在 `wo006y_span_cap_ownership_probe/`。
  實跑 owned BL block 有 `1536` 個 BL span-cap faces，core interface 只有 `62` 個
  triangulated span-cap faces，native matched 是 `0`；其中 `60` 個 touch `wing_wall`、
  `64` 個 touch `bl_outer_interface`、`96` 個 touch `wake_cut`。判讀：span-cap 需要明確
  tip/span-cap ownership policy 或 receiver topology，不能直接丟成 SU2 boundary 或 CFD
  completion。
- WO-006Z 新增 BL physical wall surface basis：
  `build_boundary_layer_wall_surface(...)` 與
  `scripts/probe_wo006z_bl_physical_wall_surface.py` 現在只從 layer-0 wall nodes 建
  physical wall；finite TE 會新增非零面積 TE-base wall，sharp TE 只做 duplicate-node
  seam stitch，terminal tip cap 只由 wall-layer nodes 三角化。Baseline A current geometry
  artifact 在 `wo006z_bl_physical_wall_surface_probe/`；實跑 `points_per_side=16`、
  `spanwise_subdivisions=2`、BL `layer_count=24` 得到 watertight `wing_wall=1016`：
  source spanwise wall faces `960`、tip-cap triangles `56`、sharp-TE seam pairs `33`、
  finite TE-base wall faces `0`。判讀：這修的是 wall marker 物理 ownership basis，
  不是 BL/core handoff ready；wake receiver / span-cap conformal merge、mesh quality、
  marker match 與 near-wall/y+ gate 仍要過，才可以跑 medium/fine SU2 ladder。
- WO-006AA 新增 tip receiver topology probe：
  `scripts/probe_wo006aa_tip_receiver_topology.py` 將 WO-006Y 的 span-cap blocker
  推進成 virtual receiver accounting candidate。Baseline A current geometry artifact 在
  `wo006aa_tip_receiver_topology_probe/`；實跑 `points_per_side=16`、
  `spanwise_subdivisions=2` 可 account `1536 / 1536` 個 BL span-cap faces，remaining
  `0`。side boundary role counts 是 `physical_wall_edge_receiver=60`、
  `wake_edge_receiver=100`、`core_outer_edge_receiver=64`。判讀：span-cap ownership
  已有可實作 receiver topology，但不是 final BL/core handoff；必須把 receiver side
  boundaries 真正接到 physical wall、wake receiver、core outer interface，並通過
  merged mesh quality / SU2 marker readability，才可以跑 medium/fine CFD ladder。
- WO-006AB 新增 BL/core topology accounting gate：
  `scripts/probe_wo006ab_bl_core_topology_accounting_gate.py` 將 WO-006Z physical
  wall、WO-006X stitched wake、WO-006AA tip receiver 與 native `bl_outer_interface`
  match 合成同一 gate。Baseline A current geometry artifact 在
  `wo006ab_bl_core_topology_accounting_gate/`；實跑 physical wall `watertight`、wake
  accounting pass、tip receiver accounting pass、outer interface `1024 / 1024` match，
  verdict 是 `topology_accounting_ready_not_handoff`。判讀：這是完整 pre-mesh ownership
  accounting contract，不是 handoff；blockers 仍是 receiver geometry 未 materialize、
  final merged mesh missing、merged mesh quality / SU2 marker readability / near-wall y+ /
  solver ladder 未跑。下一步是把 virtual receiver 實作成真幾何/mesh，不是直接跑 CFD。
- WO-006AC 新增 receiver geometry materialization probe：
  `scripts/probe_wo006ac_receiver_geometry_materialization.py` 將 WO-006AA virtual tip
  receiver materialize 成明確座標與 positive-volume cells。Baseline A current geometry
  artifact 在 `wo006ac_receiver_geometry_materialization_probe/`；實跑
  `points_per_side=16`、`spanwise_subdivisions=2` 得到 status
  `tip_receiver_geometry_materialized_quality_pass`、`1536` 個 receiver cells、`1650`
  個 virtual nodes、receiver thickness `0.03617304985338918 m`、min receiver volume
  `1.1070816511539737e-08 m^3`、non-positive volume `0`、`external_shape_changed=false`。
  判讀：`receiver_geometry_not_materialized` blocker 已解成 geometry candidate，但仍未有
  final merged mesh、mesh quality、SU2 marker/readability、near-wall/y+ 或 solver ladder；
  因此仍不能跑 medium/fine SU2 或解讀 CL/CD/Cm。
- WO-006AD 新增 near-wall merged volume candidate probe：
  `scripts/probe_wo006ad_near_wall_merged_volume_candidate.py` 將 owned BL block、wake
  receiver、sharp-TE stitch accounting 與 materialized tip receiver 合成同一個 pre-core
  volume accounting object。Baseline A current geometry artifact 在
  `wo006ad_near_wall_merged_volume_candidate_probe/`；最新實跑 status 是
  `near_wall_volume_candidate_ready_core_mesh_pending`，有 `28875` nodes、`26880`
  near-wall volume cells（owned BL `24576`、wake receiver `768`、tip receiver `1536`），
  original exposed span-cap `0`、original exposed wake-cut `0`、stitched TE-base faces
  `64`、removed degenerate receiver-base faces `32`、non-positive receiver volumes `0`。
  layer-0 sharp-TE wall/wake seam stitch 已套用 `66` 個 coincident node remaps，external
  boundary topology 現在 `watertight`、`bad_edge_count=0`。判讀：near-wall local ownership
  accounting 與 external surface closure 已可進入 core/farfield mesh probe；mesh quality、
  SU2 marker/readability、near-wall/y+ 與 solver ladder 都還沒過，因此不能跑 medium/fine
  SU2 或解讀 CL/CD/Cm。
- WO-006R10 新增 near-wall core closure probe：
  `scripts/probe_wo006r10_near_wall_core_closure.py` 接在 WO-006AD sharp-TE seam repair
  後，檢查 watertight near-wall candidate 是否可安全升級成 core/farfield inner
  interface。Baseline A current geometry artifact 在
  `wo006r10_near_wall_core_closure_probe/`；實跑 full near-wall boundary 是 `watertight`
  且 `bad_edge_count=0`，但排除 physical-wall roles 後的 core-facing subset 仍
  `not_watertight`，有 `64` 條 bad edges（`core_tip_receiver_outer=60`、
  `wake_edge_receiver=4`）。full-shell policy 是 `forbidden`，因為 full shell 含
  `wing_wall=960` 與 `physical_wall_edge_receiver=60`，不能借 physical wall 來補 core
  interface。edge-gap audit 進一步確認這 `64` 條 bad edges 全部由
  `physical_wall_edge_receiver` 解釋（tip pair `60`、wake pair `4`，
  `unexplained_bad_edge_count=0`）。判讀：下一步必須 materialize 真正 core-facing
  closure，不能改 Baseline A
  external wall shape，也不能把 physical wall 誤標成 core interface；在此之前仍不能跑
  medium/fine SU2 或解讀 CL/CD/Cm。
- WO-006 第一輪 current-pathfinder bounded smoke 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/`，verdict 是
  `su2_baseline_needs_fix`。Current pathfinder VSP3 provider materializes，但 default
  mesh timeout、coarse sensitivity boundary parametrization topology failed，沒有 usable
  current-pathfinder SU2 CL/CD delta；這是 route repair evidence，不是 Baseline A reopen
  或 performance claim。
- WO-006R1 current GO mesh-native bridge 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r1_go_cfd_bridge/`，
  verdict 是 `wo006r1_go_cfd_bridge_smoke_ready`。它選擇 current production-inspection
  `section_table.csv` + `airfoils/*.dat`，而不是繼續盲修舊 STEP/BREP route；已寫出
  marker-owned coarse no-BL `mesh_handoff.v1`、SU2 case，並跑完 3-iteration SU2 readability
  smoke。這仍不是 usable CL/CD/CDi/profile-drag calibration，因為 mesh underresolved、無 BL/y+、
  solver 未收斂且 smoke CD sanity failed。
- WO-006R2 current GO CFD recovery campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign/`，
  verdict 是 `wo006r2_current_geometry_adapter_blocker_isolated`。它改用 no-touch
  `avl_parity/current_avl_compromise_conservative_closed` geometry，保留外形不變；coarse
  adapter control 只證明 marker-owned no-BL mesh 可寫出，不是 CFD evidence。舊 serious
  mesh-native BL/HXT template 與 coarser BL probe 都在 Gmsh HXT PLC intersection 擋住，
  high-mesh no-BL control 也在 surface topology 擋住，所以目前沒有可解讀 SU2 coefficient、
  沒有 Baseline A reopen evidence；下一步必須在 data-authority checker 仍為 prerequisite
  的條件下，定位並修 current GO surface panel / section-transition topology，不能改外形來繞過。
- WO-006R3 current GO surface-topology repair campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/`，
  verdict 是 `wo006r3_high_mesh_handoff_ready`。它修正 DAE31 near-TE airfoil-loop ordering，
  新增 same-station loop preflight，並把 shorter panel diagonalization 限定在 no-BL faceted
  SU2 handoff route；current-GO no-BL `wing_h=0.12 m` mesh 目前有 `936,017` volume cells、
  marker audit pass，SU2 readability smoke 到 iteration 75。這是 serious high-mesh no-BL
  handoff，不是 BL/y+ viscous handoff；BL/HXT 仍卡在 DAE31-family PLC segment/facet
  intersections，CFD evidence gate 仍 fail，所以沒有可解讀 SU2 coefficient、沒有 Baseline A
  reopen evidence。
- WO-006R4 BL ownership repair campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/`，
  verdict 是 `wo006r4_adapter_limitation_proven`。R4 沒有寫出 `bl_mesh_handoff.v1.json`：
  Gmsh topological BL extrusion 仍被 R3 定位的 DAE31-family PLC points 擋住，BL shorter
  diagonalization 仍因 `Unknown curve -1550` 被拒絕。current GO mesh-native owned-BL block
  可以建立正體積近壁 block（first layer `5e-5 m`、24 layers、estimated y+ 約 `1.04`）且
  R4 未新增外形 cleanup；但 preserved-interface core probe 有 core quality fail 與
  wake/span-cap coupling partial，remeshed core probe 會改掉 BL-core interface，不能當
  conformal viscous handoff。下一步若要 BL handoff，必須實作 conformal owned BL block +
  core merge / mixed-element SU2 writer，再跑 marker / quality / readability gate。
  R4 沒有 postprocessed y+、沒有可解讀 SU2 coefficient、沒有 Baseline A reopen evidence。
- WO-006R5 BL+core merge campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`，
  verdict 是 `wo006r5_core_merge_limitation_proven`。R5 沒有寫出
  `bl_mesh_handoff.v1.json`：preserved-core probe 保留了 core interface envelope，
  但 core quality gate fail（non-positive SICN/SIGE/volume），BL/core coupling 仍是
  partial，且全部 non-wall BL boundary 不能直接作為 watertight core inner boundary
  （124 bad edges）。因此目前 blocker 已縮小為 conformal core interface / mesh-quality
  repair；R5 仍沒有 postprocessed y+、沒有可解讀 SU2 coefficient、沒有 Baseline A reopen evidence。
- WO-006R6 core-interface repair campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/`，
  verdict 是 `wo006r6_core_quality_limitation_proven`。R6 沒有寫出
  `bl_mesh_handoff.v1.json`：preserved-core route 仍保留 interface envelope，但 core
  quality gate 仍 fail（non-positive SICN/SIGE/volume），而且 wake/span-cap coupling
  還是 partial。`core_interface_topology_audit.json` 顯示 zero-unmatched interface 未達成：
  core side 還有 94 個 unmatched faces（`span_cap` 62、`wake_cut` 32），BL boundary side
  還有 3136 個 unmatched faces（`span_cap` 1536、`wake_cut` 1600），full non-wall boundary
  仍不是 watertight（124 bad edges）。因此目前 blocker 不是 SU2 coefficient 或 solver
  tuning，而是 preserved-core quality repair 加上 wake/span-cap 真正 conformal topology
  contract；R6 仍沒有 postprocessed y+、沒有可解讀 SU2 coefficient、沒有 Baseline A reopen
  evidence。
- WO-006R7 core-quality hotspot diagnosis 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r7_core_quality_hotspot_diagnosis/`。
  R7 把 R6 的 core quality fail 定位成 `91` 個 non-positive `Pyramid 5` transition
  elements，全部貼在 preserved `bl_outer_interface` quads；`87` 個在 aft/TE，`21` 個落在
  `dae31 -> cst_tip_nsga2_g05_child_0032_70ef8136` transition。下一步應先修
  quad-to-tet pyramid transition / orientation / warped-face interface，再談 merged 或
  multizone CFD ladder；這不是 SU2 iteration 數或 no-BL solver tuning 問題。
- WO-006F SU2 engineering-result recovery campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/`，
  verdict 是 `wo006f_campaign_incomplete`。它嘗試 no-BL NS/RANS/Euler、OpenVSP/Gmsh、
  OpenVSP CFDMesh 與 R6 BL/core multizone probe。唯一 final sign-correct pair 是 no-BL
  RANS `CL=1.289421542`、`CD=0.5555196327`，但 drag 比 AVL + Tier2 profile-proxy /
  old VSPAERO sanity bounds 高太多且未收斂，不能當 aero calibration；Euler positive
  window 不是 final/stable。R6 multizone 可啟動，代表 SU2 route 仍開放，但目前仍沒有
  physically credible SU2 CL/CD、沒有 Baseline A reopen evidence。下一步是修 R6
  preserved-core quality、wake/span-cap coupling 與 multizone/merged force coefficient
  ownership。
- WO-006G SU2 CFD V&V reset / escalation dossier 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006g_su2_toolchain_escalation/`，
  allowed verdict 是 `su2_toolchain_escalation_required_after_exhaustive_failure`。這會取代
  「繼續小網格 solver iteration」作為目前 WO-006 SU2 線的工程結論：current OpenVSP geometry
  不是乾淨 watertight CFD solid，current BL/core route 沒有 conformal / quality-passing final mesh，
  現有係數沒有 wall-resolved、transition-aware、force-stable、grid-independent evidence；因此
  目前本機 OpenVSP/Gmsh/SU2 工具鏈不能產出可用 Baseline A SU2 aero calibration。後續必須先升級
  CFD-grade geometry cleanup、BL-resolved mesh family、足夠 compute resource，以及 low-Re
  transition / grid-convergence V&V workflow，不能把 route/debug evidence 升格成性能真相。
- WO-006H reopened CFD campaign 已產出
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_reopened_cfd_campaign/`，
  verdict 是 `su2_local_hard_limit_proven_with_executable_hpc_case`。這仍不是 SU2
  aerodynamic result；它取代先前只到 larger-compute package 的 H 結論。本機 no-BL HXT
  control 可到 `3,790,657` cells / `675,820` nodes 且 marker / quality pass，但 no-BL
  只能當 resource / marker / sign-control evidence。更細 no-BL rung 以 topology/PLC 類錯誤
  快速失敗（`h=0.05` HXT、`h=0.04` Delaunay），不是 memory 接近上限；BL/core route 也仍未
  過 conformal handoff gate（full BL boundary preserved-core PLC fail，preserved-interface
  Alg1 mesh 有 `173` non-positive volumes、`158` unmatched core interface faces 與 `4672`
  unmatched BL boundary faces）。因此沒有 conformal BL-resolved handoff、沒有 postprocessed
  y+、沒有可解讀 CL/CD/Cm。可用輸出是 directly runnable
  `wo006h_reopened_cfd_campaign/hpc_executable_case/`，它會針對 `h=0.05` / `h=0.04` no-BL
  topology probes 與 BL/core preserved-interface cases 重跑，不是 Baseline A drag/power
  calibration。
- WO-007 QPROP/XROTOR 不能混入 structural blocker verdict。
- P1/C04 是 coupon/local FEM readiness，screening result 不是 final aircraft sign-off。

現行 audit artifacts：

- `output/baseline_A_team_release/data_authority_claim_inventory.csv`
- `output/baseline_A_team_release/data_authority_conflict_register.csv`
- `output/baseline_A_team_release/data_authority_table.csv`
- `docs/reports/baseline_A_data_authority_audit.md`
- `docs/reports/baseline_A_gate_debt_register.md`
- `docs/reports/repo_channel_hygiene_plan.md`

> **文件性質**：目前正式主線的單一真相文件。當 README、GRAND_BLUEPRINT、
> 舊報告、歷史 prompt 互相衝突時，以這份文件為準。
> **更新基準**：2026-05-09 repo 現況；核心基準來自
> `docs/reports/2026-05-08_commit_history_report.md` 的 Phase J pipeline，
> `docs/reports/2026-05-09_phase_j_evidence_map.md` 的 stage-by-stage artifact mapping，
> `docs/reports/2026-05-09_pathfinder_basis_lock.md` 的 pathfinder geometry/load basis lock，
> `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md` 的 all-moving tail /
> trim / stability contract insertion，
> 並納入 Phase J 後續結構宣稱 / FEM claim-boundary 補強。
> **適用對象**：使用者、協作開發者、AI agent。

## 1. 一句話版本

這個 repo 目前的正式主線不是單純的 spar sizing，也不是舊的
`VSP -> inverse design -> jig shape -> CFRP` 粗略敘事；目前主線是：

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

這條線的工程目的，是把 mission requirement、spanload、可製造 smooth
geometry、loaded-Z、翼型選擇、結構預算與候選驗證收成同一條可追溯的設計鏈。

## 2. 主線操作模式：Pathfinder First, Then Expansion

目前不是要把所有 mission scan cases 一次全部推到 final FEM，也不是把單一候選說成全域最佳。
主線的正確運作模式是：

```text
pick one credible pathfinder candidate
-> make every stage physically and semantically coherent on that candidate
-> expose and repair local engineering blockers
-> only then widen the search space and rerun broader candidate families
```

這個 pathfinder candidate 的角色是「先行者」：

- 它必須能從 mission contract 追到 geometry、load、airfoil、structure、closure。
- 它用來驗證整條 pipeline 的資料契約、單位、load ownership、geometry basis 和工程語言。
- 它可以在每個 stage 做局部最佳化和局部修正。
- 它不是 hard gate、不是 final aircraft、也不是全域 optimum。
- 它閉環後，下一步才是擴大 span / AR / speed / airfoil / structure / rib-bracing search space。

目前 `current_avl_compromise_conservative_closed` 就是這個 pathfinder /
conservative screening candidate。若後續有更好的 candidate，應該用同一套 pathfinder
trace protocol 取代它，而不是另外開一條不相容敘事。

## 3. 現在主線在解什麼

目前核心問題不是「給定一個漂亮幾何後把 spar 做到 pass」，而是：

- mission contract 能否導出可信的 Fourier / AVL spanload 候選；
- 候選能否落成 smooth production geometry，而不是只停在數學分布；
- smooth geometry 經 AVL realization check 後，是否仍符合氣動 / trim / 載荷需求；
- structure-budgeted loaded-Z search 能否找到 mass、clearance、wire、shape 都能接受的
  realizable loaded shape；
- Tier2 full-alpha airfoil selection 是否在 actual loaded-shape 的 local `Cl/Re`
  上仍有足夠查表品質與失速裕度；
- aero-structure closure 是否真的閉合，而不是氣動和結構各自 pass 不同狀態；
- 最後的 FEM/APDL、shell buckling、load-factor checks 能否支持 candidate-relevant
  review，同時避免把 spot-check 誤寫成 final aircraft sign-off。

## 4. Canonical Workflow

未來 agent 進 repo 後，請先用下面這條 pipeline 判斷任何任務的位置：

1. **Mission contract**
   - 定義任務、速度 / 功率 / span cap / mass budget / performance target。
   - 不要在 mission 還沒定義清楚時先改下游 rib、wire、tail hardware 或 FEM。
2. **Tail / CG / trim / stability contract**
   - 定義 CG range、水平尾 / 垂尾 design box、all-moving control travel、tail volume、
     static stability、control authority、tail drag/mass placeholder 與 pass/fail criteria。
   - 主翼 Fourier spanload 仍由主翼主導；尾翼在這一層是全機 feasibility / trim / stability contract。
3. **Fourier-AVL calibration**
   - 把 Fourier spanload command 與 AVL actual spanload 對齊。
   - 這是下游 structure-budgeted search 的 load authority 來源。
4. **Fourier spanload candidate generation**
   - 產生可比較的 spanload / planform / distribution 候選。
   - 這裡仍是候選生成，不是 manufacturable aircraft；尾翼只做 trim / authority feasibility filter。
5. **Smooth production geometry realization**
   - 把候選落成 smooth、可製造、可匯出的幾何語言。
   - 不能把連續 optimum 直接當圖紙；此處也要 instantiate all-moving H-tail / V-tail 幾何與 pivot axes。
6. **AVL realization check**
   - 對 realized geometry 做 full-aircraft AVL trim / stability / spanload 檢查。
   - 若 realized geometry 不能維持原本氣動意義，要回上游修正。
7. **Structure-budgeted loaded-Z search**
   - 在結構質量、clearance、wire support、beam-line Z proxy 與 loaded shape 間找可行區。
   - 這是目前 candidate 可不可推進的核心卡點之一；tail mass、trim-load envelope、tailboom load 不能被丟到最後。
8. **AVL recheck on realizable loaded shape**
   - 對真正可實現的 loaded shape 重做 full-aircraft AVL 檢查，並求 all-moving H-tail trim。
   - 不要用 requested shape 的漂亮數字替代 realizable shape。
9. **Tier2 full-alpha airfoil selection**
   - 用 actual loaded-shape 的 local `Cl/Re` 做 full-alpha airfoil selection。
   - 不能只用 seed airfoil 或單點 polar 決定全翼翼型；尾翼翼型先用 NACA 00xx / curated symmetric set 做 discrete screening，不先開 NSGA2。
10. **Aero-structure closure**
   - 檢查氣動、loaded shape、翼型、結構、clearance、wire、tail trim/control DOFs 是否在同一個候選上閉合。
   - 這一步通過才適合進更重的 FEM/APDL review。
11. **FEM/APDL / shell buckling / load-factor / tailboom / hardware checks**
    - 目前定位是 candidate-relevant equivalent-physics validation / spot-check。
    - 不等於 final composite aircraft、root fitting、wire hardware、rib joint、tail pivot 或 tailboom sign-off。

## 5. 目前做到哪裡

目前最接近 production-facing engineering review 的候選仍應理解為：

```text
current_avl_compromise_conservative_closed
```

這個 candidate 的價值是「可以拿去做幾何、結構、製造、外部審查討論的
conservative screening candidate」，不是 final design。

目前已經收斂到主線內的能力：

- Phase J pipeline 已把 mission contract、Fourier-AVL、smooth geometry、
  loaded-Z、Tier2 airfoil、aero-structure closure 與 FEM/APDL spot-check 串成同一條路。
- `ConservativeLoadMapper` 已建立 aero-grid -> structural-grid 的 opt-in conservative remap foundation；
  它守恆 total lift、root bending moment、total pitching torque，並輸出 correction / sign reversal /
  peak ratio diagnostics。它是 rib / rear-spar sensitivity 前置基礎，不是 aeroelastic sign-off。
- Empennage / trim / stability contract insertion 已建立，位置在
  `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md`。它把 all-moving
  horizontal tail / vertical tail 定位成 trim、static stability、control authority、tailboom load、
  mission drag/mass 的共同 contract，並規定 tail airfoil 先以 discrete symmetric candidates 進入。
- Current pathfinder tail contract v0 foundation 已建立，位置在
  `configs/current_pathfinder_tail_contract_v0.yaml` 與
  `docs/reports/2026-05-09_tail_contract_v0_foundation.md`；目前 screening status 是
  `required_inputs_missing`，只完成 tail volume / reserve bookkeeping，尚未完成 full-aircraft
  trim / stability pass。
- All-moving full-aircraft tail AVL audit v0 已建立，位置在
  `docs/reports/2026-05-09_full_aircraft_tail_avl_audit_v0.md` 與
  `output/current_pathfinder_tail_avl_audit_v0/`；本機 AVL runner 已產生 9 個全機 deck /
  `.st` sweep artifact。判讀是 `blocked_by_directional_stability_or_vtail_authority`：
  `delta_H_required` 仍被 CG / wing AC 缺口擋住，`V_V = 0.010145` 且
  `C_n_beta = 0.002236` 太小，下一步應先回 tail sizing / CG / reference-moment contract，
  不應直接進 rib sensitivity。
- Current pathfinder V-tail / CG reference sizing sensitivity v0 已建立，位置在
  `scripts/vtail_cg_reference_sensitivity_v0.py`、
  `docs/reports/2026-05-09_vtail_cg_reference_sensitivity_v0.md` 與
  `output/current_pathfinder_vtail_sensitivity_v0/`；它只掃描 bounded V-tail area /
  aft-position authority，不做 rib、rear spar、ASWing-lite、FEM 或 tail airfoil NSGA2。
  15 個 AVL geometry variant 顯示放大 V-tail / 增加 tail arm 會讓 `C_n_beta` 和
  `C_n_deltaV` 往合理方向上升，但 final verdict 仍是
  `blocked_by_missing_cg_or_reference_moment`，因為 `Xref` 不是 wing AC、`Xnp` 仍只是未驗證
  neutral-point candidate，且 promoted aircraft CG range 尚未存在。
- Current pathfinder tail / CG / trim / stability screening v1 已建立，位置在
  `scripts/current_pathfinder_tail_cg_trim_stability_screening.py`、
  `docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md` 與
  `output/current_pathfinder_tail_cg_trim_stability_v1/`。它把 AVL `Xref` 明確設為每個
  screening CG row，並用 `Xnp = Xref - Cma/CLa*Cref` 驗證 neutral-point convention。
  v1 verdict 是 `ready_for_tail_aware_rib_rear_spar_sensitivity`，推薦 screening CG range
  `[0.68, 0.75] m`、H-tail `S_H=4.5 m^2 / x_ac_H=8.281 m`、V-tail
  `S_V=3.36 m^2 / x_ac_V=8.350 m`。這是 screening basis，不是 measured CG manifest、
  tail polar、tailboom/hardware、FEM 或 final aircraft sign-off。
- `scripts/fourier_avl_calibration_mvp.py` 提供 Fourier-AVL calibration artifacts；它現在要求
  明確 `--report-json`，舊 medium-search report 預設封鎖，只能用
  `--allow-legacy-medium-search` 做明確標示的歷史診斷。
- `scripts/structure_budgeted_z_state_search.py` 提供 structure-budgeted loaded-Z search。
- `scripts/aero_structure_closure_mvp.py` 提供 Tier2 後的 aero-structure closure。
- Phase 14 Mac-local FEM / APDL package route 已建立，且修掉早期 FEM offset-rigid
  export 類錯配。
- Phase 15/16/17 load-factor、wire6 ramp、candidate shell buckling / tip limit review
  已把一部分候選驗證包接起來。

目前仍不能宣稱完成的地方：

- FEM/CalculiX 仍有 model-basis / displacement-scale mismatch 風險，不能當 final validation。
- Composite local buckling、root fitting、wire/cable termination、attach hardware 仍需要更高可信度的
  detail model、coupon、外部工程審查或 FEM。P1 C04 rib joint 已有 saddle-ring/yoke/clamp
  local load-path closure，可進 coupon/local FEM；這仍不是 rib-joint final sign-off。
- Ground clearance margin 對製造誤差、跑道不平、wire setup、joint compliance 仍偏薄。
- Beam-line Z proxy 還不能直接等同 aerodynamic surface / final aircraft dihedral。
- Current pathfinder 已有 all-moving horizontal tail / vertical tail 的 full-aircraft AVL deck /
  derivative audit、tail/CG/trim/stability screening、tail-aware closure 與 P1 mass-integrated
  closure evidence。managed CG row 下 trim / static / directional authority pass，但 tailboom/pivot
  hardware、measured mass manifest 與 final flight-dynamics sign-off 尚未完成。
- WO-006 SU2 current-GO no-BL route 已可跑出 finite 159-iteration force history；這是
  route-level CFD evidence，但仍不是目前 performance claim truth。下一步要補
  near-wall/BL/y+、grid V&V 與 drag sanity，不能把 no-BL high-drag result 當 drag/power
  evidence。
- Rib 目前是下游 bracing / shell bay / load-transfer 實體化問題，不是主線 candidate
  generation 的短線最大優先，除非它被證明會改變 aero-structure closure 的候選排序。

## 6. Phase J 後續補強的定位

Phase J 之後新增了一系列 structural claim-boundary / engineering guardrail。這些工作有價值，
但要正確理解：

- 它們主要防止 repo 把局部 pass 誤寫成 full-wing / final aircraft pass。
- 它們把 rear spar stiffness、rib bracing、wire attach、root joint、torsion/twist、
  wire termination、rib spacing、tip deflection、full-wing buckling、failure ordering
  的 evidence gap 明確化。
- 它們不是把所有 detail FEM / joint / hardware validation 做完。

已補強的工程檢查族群：

- structural claim readiness：避免把 local / screening evidence 升格成 final sign-off。
- local load path ledger：拆出 wire attach、root joint、termination、tube wall 等 detail path。
- rear spar / rib bracing diagnostics：檢查 rear spar、rib spacing、braced subassembly 證據是否足以支撐 buckling bay assumption。
- torsion / twist closure inputs：要求 aeroelastic twist / torsional stiffness 的來源可追溯。
- full-wing buckling claim boundary：要求 1.5G / 1.75G full-wing claim 有 global evidence，而不是只靠 local wall pass。
- tip deflection claim boundary：把 2.5 m gate 定位成 design-validity / submission gate，不是斷裂點。
- failure mode ordering：wire 升級後，不再假設 wire 一定是第一 blocker，必須由 global bracing / joint FEM 排序。

工程判斷：這一波補強使 candidate review 更安全、更不容易過度宣稱；但下一個大步仍應回到主
pipeline，確認目前 candidate 的 mission / Fourier-AVL / smooth realization / loaded-Z / airfoil /
closure 是否該繼續推進，而不是直接把 rib detail FEM 當作新主線。

## 7. 下一步優先順序

目前已同意的短線順序如下：

Phase J evidence map 已重新深度審核，位置在
`docs/reports/2026-05-09_phase_j_evidence_map.md`。它現在是判斷每個 stage
目前 artifact / candidate / trust boundary 的對照表，也是舊 medium-search source 的
quarantine 文件。

Pathfinder Basis Lock 已建立，位置在
`docs/reports/2026-05-09_pathfinder_basis_lock.md`。它把
`current_avl_compromise_conservative_closed` 鎖定為 downstream screening pathfinder：
從 `smooth_tier2_production_baseline` 經 loaded-Z、loaded-shape AVL、Tier2 airfoil、
aero-structure closure 到 final candidate package 的 artifact chain 是可追溯的；但
current mission -> promoted Fourier/Fourier-AVL trace -> 這個 exact candidate 尚未鎖定，
physical aerodynamic surface / quarter-chord / clearance 也還不能等同 beam-line Z proxy。

Conservative load mapper foundation 已建立，位置在
`docs/reports/2026-05-09_conservative_load_mapper_foundation.md`。目前 current pathfinder
AVL spanload -> structural grid smoke 的 projection status 是 `conserved`，correction 很小且沒有
sign reversal；但這只代表 remap conservation foundation 可用，不代表 aeroelastic / rib / rear-spar
stiffness 已經 sign-off。

最新判讀：目前 Stage 0 mission design-space / drag-budget contract 是可用 source，且
commit history 已包含 pilot power / thermal derate、mission design-space scan、drag budget、
MissionContract / FourierTarget、airfoil sidecar、smooth geometry、loaded-Z、Tier2 airfoil
與 closure。Stage 1 Fourier-AVL calibration artifact 仍綁著 legacy medium-search top candidates；
Stage 2 machinery 存在，但還沒有一份 promoted current trace manifest 把 current mission
handoff 乾淨追到 go-mode candidate。因此 go-mode candidate 應讀成 conservative screening
candidate，而不是完整 mission -> Fourier -> smooth end-to-end final aircraft。

1. **先建立或明確標示 pathfinder promoted trace**
   - 目的：從 current mission design-space / drag-budget handoff 產生一份可提交的
     Fourier/Fourier-AVL candidate trace manifest，或明確寫出目前 go-mode candidate 是從
     `smooth_tier2_production_baseline` 開始的 downstream screening surrogate。
   - 原因：如果上游來源不清，後續 beam-line、rib、FEM 都可能在替錯誤的 candidate narrative 背書。
2. **再處理 beam-line / aerodynamic surface / clearance 對齊**
   - 目的：釐清 beam-line Z proxy、真實 aerodynamic surface、clearance、dihedral 定義是不是在同一個幾何語言下。
   - 原因：如果這層沒對齊，後面的 rib、root、wire、FEM 可能都在驗證錯對象。
3. **之後才看 aero-structure closure 的工程可信度**
   - 目的：確認 `current_avl_compromise_conservative_closed` 是否真的在同一個 geometry / load /
     airfoil / structure state 上閉合。
4. **tail contract v0 -> all-moving audit 已完成第一輪 artifact**
   - 目前：tail contract v0 foundation 已建立，且 all-moving full-aircraft AVL audit v0 已跑出
     9 個 deck / `.st` derivative artifacts。
   - 讀法：這是 blocker report，不是 pass report；它把 missing CG / wing AC 和低 V-tail 方向穩定
     evidence 變成可審查 artifact。
   - 原因：如果全機不能配平或方向穩定不足，主翼 loaded-Z / rib / FEM 局部 pass 沒有 aircraft-level
     意義。尾翼不應干擾 Fourier spanload generation，但從 mission contract 起必須存在。
5. **回補 tail sizing / CG / reference moment，再重跑 all-moving full-aircraft AVL audit**
   - 目前：v0 all-moving full-aircraft AVL audit 仍是 blocker report；v1 screening 已把
     `Xref` 明確設成 CG row，驗證 `Xnp` convention，並在 CG `[0.68, 0.75] m` 上解出
     longitudinal trim / static margin / yaw authority。v1 verdict 是
     `ready_for_tail_aware_rib_rear_spar_sensitivity`。
   - 目的：把 rib/rear-spar sensitivity 的全機 basis 固定成 screening assumption contract，
     而不是把 missing CG blocker 靜音。下一步 sensitivity 必須把 CG range、tail geometry、
     deflection reserve、tail drag/mass penalty 當輸入。
   - 原因：原始 `V_V = 0.010145` / `C_n_beta = 0.002236` tail 偏弱；v1 bounded redesign
     選用 H-tail `S_H=4.5 m^2`、V-tail `S_V=3.36 m^2`、tail x_le `8.0 m` 才讓 CG row
     有 screening margin。這不是 final geometry sign-off，只是讓下一步 stiffness sensitivity
     不再建立在一個配平/穩定性未知的 aircraft reference 上。
6. **tail-aware bounded rib/rear-spar sensitivity 已完成**
   - 目前：`scripts/tail_aware_rib_rear_spar_sensitivity.py` 與
     `docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md` 已建立。
     current pathfinder balsa baseline verdict 是 `ready_for_tail_aware_aeroelastic_closure`；
     同一個 report 現在也輸出 material family sensitivity verdict。
   - 目的：用同一個 locked pathfinder load/Z basis 跑 rear-soft/rear-stiff、finite-rib-link、
     no-rib/limited-rib 等 bounded sensitivity，確認 loaded tip Z、root-offset-removed AVL section Z、
     clearance、twist、tube mass、wire tension、`delta_H_required`、tail CL utilization、
     trim residual 與 closure ranking 會不會被 bracing 假設改變。
   - 選定 basis：`0.30 m` rib target bay 只有在 Phase24 physical station basis 下成立，
     對應 `61` half-wing stations / `121` full-wing ribs or stations、`balsa_sheet_3mm`、
     warping knockdown `0.50246`、`bounded_50pct_screening` rear-spar participation；
     對 finite-rib rear=1.0 upper-bound，選定 case 約為 `EI_flap 0.599x / GJ 0.568x`。
   - material family sensitivity：`balsa_sheet_3mm` 保留為 baseline；新增 foam-only
     `eps_hd_foam_cnc_10mm`、`xps_high_compressive_cnc_10mm`、`structural_foam_cnc_10mm`。
     v1 不包含 EPS+balsa、glass cap 或 carbon cap hybrid credit。latest verdict 是
     `foam_only_families_do_not_clear_current_aeroelastic_closure`：EPS/XPS effective GJ 約為
     balsa selected basis 的 `0.163x`、projected twist 約 `33.16 deg`；structural foam 約
     `0.581x`、projected twist 約 `9.32 deg`。三者都沒有過 `3 deg` twist screening bound。
   - stiffness rework candidates：同一 runner 現在另外輸出
     `stiffness_rework_candidates`，把 foam-only reference 與下一輪 stiffness rework 分開。
     balsa baseline 保留比較用；`eps_balsa_cap_hybrid_10mm`、
     `structural_foam_glass_face_10mm` 和 stronger rear-spar participation / shear-transfer
     rows 是可重跑的下一版 candidate family，不是 final closure pass。
   - CG 限制：未補償的 selected tail delta + physical rib pack 會把 CG 推到約 `0.801 m`；
     aeroelastic closure 只能使用 final CG 管理後的 `0.75 m` screening row。需要約
     `0.091 m` forward rebalance on 56 kg equivalent pilot/cockpit mass；不能把 tail/rib mass
     加上去後還沿用舊 ready verdict。
   - load 前提：使用 conservative remap diagnostics 檢查 total lift、root bending moment、torque
     是否守恆；如果出現 large correction 或 unphysical status，先降級 loading confidence，不要直接進 rib sensitivity。
   - 原因：現有 Phase32 / structural closure evidence 已顯示 rear spar / rib assumptions
     會大幅移動 response；若先跑 ASWing，可能只是把錯的 stiffness basis 耦合得更漂亮。
     FEM detail 則應吃已鎖定的 load/geometry envelope，不應先決定哪個 beam-line / aero-surface
     state 才是真正設計狀態。
   - tail-aware aeroelastic closure baseline 已完成第一輪：`scripts/tail_aware_aeroelastic_closure.py`
     與 `docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md` 顯示 fixed-point loop
     3 次收斂，final managed CG `0.75 m`、H-tail reserve、static margin、V-tail authority、
     mass/drag/power charge 與 conserved load remap 都保留；但 direct spar-pair rotation
     -> AVL incidence stress-test 給出 max twist 約 `5.413 deg`，超過 `3 deg` screening
     bound。新增 twist-source audit 顯示 elastic-axis / quarter-chord consistent projection
     仍約 `5.413 deg`，conservative bounded physical projection 約 `3.256 deg`，peak
     y≈`2.328 m`，主因是 aerodynamic torque-only 分量；lift 在該 station 部分抵消。
     baseline closure verdict 仍是 `needs_aeroelastic_geometry_or_stiffness_rework`，但
     clear twist-source verdict 是 `ready_for_hybrid_rib_stiffness_rework`。
   - 後續順序：tail / CG / trim / stability screening v1 basis ->
     tail-aware bounded rib/rear-spar sensitivity (done) -> tail-aware aeroelastic closure baseline
     (done, twist-source audit done) -> materialized rib station/bay contract audit (done) ->
     hybrid rib / shear cap / skin / bounded rear-spar participation rerun (done for selected
     hybrid screening surrogate) -> qualified aero-surface mapping plus local FEM/coupon package ->
     root/wire/termination/rib/tail hardware FEM detail。
   - Current pathfinder materialized rib contract audit 已建立：`scripts/current_pathfinder_materialized_rib_contract_audit.py`
     與 `docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md`
     會輸出 `rib_station_table.csv`、`rib_bay_table.csv`、mandatory/missing contract、
     skin sag、bond/collar risk 與 `local_fem_trigger_report.json`。它確認 `121` full-wing
     stations / `120` bays 已 materialized，max bay `0.297063 m`；但 verdict 是
     `blocked_needs_materialized_bond_shape_data`，因為 transport joint、control station、
     airfoil/twist transition 是 `missing_contract`，skin sag 是 `unknown_requires_test`，
     bond/collar/spar contact 是 `needs_data`，y≈`2.328 m` 附近必須作 torque-critical
     local FEM / hybrid reinforcement zone。這一步是 hybrid stiffness rework 的前置基礎，
     不能被 warping-knockdown tuning 或 foam-only EPS/XPS pass claim 取代。
   - Current pathfinder rib / torsion rework verdict 已建立：
     `scripts/current_pathfinder_rib_torsion_rework_verdict.py` 與
     `docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md`
     把 sensitivity、tail-aware closure、materialized rib audit 接成下一階段 gate。
     verdict 是 `candidate_ready_for_local_FEM_and_coupon_before_FEM_package`，不是
     `ready_for_FEM_loadcase_package`。選出的下一個 local FEM/coupon candidate 是
     `eps_balsa_cap_hybrid_10mm + bounded_65pct_screening`。closure runner 現在會把
     selected hybrid effective-GJ 當作 main/rear torsion-cell screening surrogate 消耗，
     actual closure bounded physical twist 是 `2.070 deg`，低於 `3 deg` bound；direct
     stress-test 從 baseline `5.413 deg` 降到 `3.449 deg`，仍是 conservative mapping
     warning，不是 final aero-surface twist signoff。rib mass 約 `5.365 kg`，比 balsa
     baseline 多 `2.335 kg`，且 CG/rebalance 已計入。後續 P1 closure 已把 C04
     bond/collar blocker 推進到 saddle-ring/yoke/clamp load-path pass 並回灌 splice/collar
     mass；但 transition/control stations、C07 skin sag process、coupon/local FEM 和
     hardware/laminate detail 仍不是 final sign-off。positive-zone package 已推進到
     `scripts/current_pathfinder_positive_torque_zone_validation_package.py` 與
     `docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md`：
     R067/R068/R069 與 B066-B069 是 active validation set，R066/R070 是 local model
     boundary；critical R068 的 extracted local load row 是 main lift `21.202 N`、
     kernel torque `-12.716 N*m`，轉成 main/rear torque-couple `-23.839 / +23.839 N`。
     package verdict 是
     `positive_zone_ready_for_local_FEM_and_coupon_definition_not_margin_pass`，並輸出
     guarded APDL skeleton、station/bay manifest、load decomposition、coupon matrix、
     missing-data register。這不是 FEM margin pass；下一步是補 supplier/coupon
     allowables 與 collar/tube-wall/bond/cap/skin dimensions 後跑 local margin，再 mirror
     negative zone。
   - Current pathfinder rib / torsion fast design-search loop 已重新校準：
     `scripts/current_pathfinder_rib_torsion_design_search.py` 與
     `docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md`。
     這一步把 rib/core thickness、material family、zone spacing、local cap/face/collar
     reinforcement、rear-spar participation `0.50 / 0.65 / 0.75`、mass/CG/tail-trim
     trade 和 manufacturability 接成可重跑 search runner，並輸出 Pareto / shortlist、
     FEM calibration samples、APDL/CalculiX calibration skeletons 與 FEM-result 回填
     interface。fast physical model 現在是 `link_limited_torsion_cell_v2`：rib thickness、
     spacing 與 collar credit 被視為 shear-transfer link terms，不再把 carbon collar /
     relaxed spacing 當成完整 torsion-cell GJ 乘數。revised fast-loop selected row 變成
     `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`；
     fast bounded twist 約 `1.674 deg`。原本 relaxed 10 mm carbon-collar row 仍保留為
     representative `selected_hybrid_10mm` FEM sample，另加 revised selected candidate sample。
     EPS/XPS foam-only 仍只可作 shape-core / lightweight reference，不可作 structural bracing pass。
   - Rib / torsion fast-loop CCX local-frame physical alignment 已建立：
     `scripts/current_pathfinder_rib_torsion_fem_calibration.py` 與
     `docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md`。
     這一步已把 CalculiX/CCX 從 2-node smoke 升級成 local beam-frame calibration
     solver：main/rear spar segment、torque-zone collar、rib shear-transfer /
     diagonal shear-transfer beams、y=`2.327757 m` local lift 與 main/rear
     torque-couple 都寫進 sample decks，並新增 local bay-end reaction print / audit。
     CCX local model audit 判定 `ccx_local_model_reasonable_for_fast_physics_alignment`：
     load couple recovers `12.716 N*m` torque、reaction force balance closed、deformation
     mode 是 torsion / shear-transfer dominant、selected/aggressive stiffness ratio
     符合工程直覺。這次不再使用 hidden family correction factor；`family_correction_factors`
     保持空值，只保留 legacy diagnostic factors。代表 structural rows 的 revised
     fast-vs-CCX error 已壓到 `<=5%`：原 relaxed 10 mm selected row `4.554%`、
     aggressive carbon/glass collar row `1.171%`、revised selected row `1.950%`。
     verdict 是 `fast_physical_model_verified_within_5pct`。y≈`2.328 m`
     bond/collar/tube-wall 仍是 `watch`，tube-wall margin 約 `2.304`；這個 simplified
     CCX model 只代表 local torsional stiffness / shear-transfer response，不是 bond peel /
     buckling / tube-wall / skin sag / flight-load final truth。
   - Current pathfinder rib / torsion detailed local validation shortlist 已鎖定：
     `docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md`。
     verdict 是 `selected_candidate_ready_for_detailed_local_validation`，不是 final pass。
     鎖定 basis 是 revised fast-loop selected row
     `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
     with revised bounded twist `1.673592 deg`。detailed validation shortlist 只保留三個
     local FEM/coupon cases：P1 selected 10 mm uniform carbon-collar row、P2 12 mm
     uniform carbon-collar heavier reserve、P3 10 mm uniform glass-face collar lower-complexity
     alternate。8 mm dense torque-zone row 雖較輕，但因 manufacturability score 降到
     `0.38` 且 direct fast twist 接近 `3 deg`，不升為 detailed validation priority。下一層
     必須針對 y≈`2.328 m` rib/collar/bond/tube-wall、skin sag、rib-to-spar shear/peel、
     carbon/glass collar與 balsa cap load path、tube crush/ovalization，以及代表 ordinary bay
     做 detailed FEM/coupon/allowable；這仍不是 aircraft, FEM/APDL, adhesive, tube-wall,
     skin sag, buckling, or manufacturing sign-off。

針對已鎖定的 downstream pathfinder engineering lane，`ConservativeLoadMapper` foundation
是 load ownership 前置基礎且已完成；tail / CG / trim / stability contract v0、all-moving
full-aircraft AVL audit v0、V-tail / CG reference sizing sensitivity v0、以及 tail / CG /
trim / stability screening v1 也已完成。tail-aware bounded rib / rear-spar stiffness
sensitivity 已完成並選出下一階段 basis；tail-aware aeroelastic closure baseline 第一輪已收斂但
verdict 是 `needs_aeroelastic_geometry_or_stiffness_rework`。rib / torsion rework verdict
已把 selected hybrid effective-GJ 接進 structural kernel / closure rerun，bounded physical
twist 實際清到 `2.070 deg`；positive y≈`2.328 m` package 已定義 local FEM/coupon
handoff，但還不能進 FEM/APDL margin package。下一步不是擴大 search，而是填這份
positive-zone package 的 supplier/coupon allowables 與 geometry detail，跑
rib cap/face/collar/bond/tube-wall local margin、skin sag coupon/panel evidence，之後
mirror/compare negative zone；同時 direct `3.449 deg` stress-test 仍要做 qualified
aero-surface mapping。
新的 fast design-search loop 已完成 CCX local-frame physical alignment：代表 structural
rows 已在 local CCX beam-frame 內對齊到 `<=5%`，revised search 選出 uniform `0.30 m`
carbon-collar / rear75 的 10 mm hybrid row，bounded twist 約 `1.674 deg`。這仍不能取代
positive-zone local margin、coupon work、skin sag evidence 或 APDL/CalculiX final sign-off。
Detailed local validation shortlist 已把這個 selected row 鎖成 P1，並把 12 mm carbon-collar
reserve 與 10 mm glass-face collar manufacturability fallback 列成 P2/P3；目前 verdict 只到
`selected_candidate_ready_for_detailed_local_validation`。

**Step 1 — Geometry and allowable freeze sheet 已完成（2026-05-11）：**
`scripts/current_pathfinder_rib_local_detail_geometry_freeze.py` 已從 config
thickness-fraction 推導出 y≈2.328 m 的 spar tube OD/wall（main CF-HM-100x98 100 mm /
rear CF-HM-80x78 80 mm），填入全部八個 missing-data-register items（adhesive、
bondline、collar、balsa cap、EPS、skin），並對 7 個 local failure modes 做 preliminary
margin screen。所有 preliminary margin 均 pass；最緊的是 **C07 skin sag（margin 0.03）**
與 **C04 bond peel（margin 2.57）**。C07 的緊是因為 process-sensitive pre-strain 假設，
不是強度不足；adhesive / tube-wall / collar bearing 的裕度極大，這與 HPA 超輕載荷
吻合。APDL skeleton 的所有 `= -1` placeholder 已用 v1 freeze 值填入，guarded flag
改成 `SUPPLIER_DATA_REQUIRED = 0`。freeze sheet 位於
`output/current_pathfinder_rib_local_detail_geometry_freeze/geometry_allowable_freeze.json`
與 `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md`。
12 個 tests 通過。

**Step 2 — Refined analytical margin run 已完成（2026-05-11）：**
`scripts/current_pathfinder_rib_local_detail_margin_run.py` 讀入 Step 1 freeze JSON，
對 7 個 failure modes 套用精化力學模型：C02/C03 Goland-Reissner 簡化 SCF（bond shear
端部集中）、C04 偏心力矩模型（M = F × r_spar）取代 0.20 fraction proxy、C05 Hertz
曲率修正（π/4）、C06 Lamé 厚壁筒 hoop stress、C07 parametric pre-strain sweep（找
最小可行 pre-strain 與 2× 製程目標）。**關鍵工程發現：**

- **C04 bond peel：margin = −0.893（fail）**。偏心力矩模型顯示 rib collar tab 與
  spar tube 的 peel load 約 3,740 N/m，遠超過估算允許值 400 N/m。Step 1 的 margin
  2.57（用 0.20 fraction proxy）低估了 peel eccentricity。這是真實工程發現，不是
  程式錯誤；rigid adherend 模型可能偏保守（collar 撓性、adhesive fillet 未計入），
  但在 Step 4 margin 宣稱之前必須先做 **C04 物理 coupon 試驗**。
- **C07 skin sag：nominal margin 0.026**，min viable pre-strain 約 0.05%，
  process target（2×）約 0.10%。製程規格（覆膜收縮協定、預緊量、
  代表性 0.30 m bay panel 試驗）仍是未關閉事項。
- C01/C02/C03/C05/C06 analytical margins 均大（>100），在 HPA 超輕載荷下不是
  governing failure modes。

Step 2 verdict：`step2_analytical_concern_review_needed`（因 C04 為 negative margin）。
輸出位於 `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.json`
與 `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md`。
12 個 tests 通過（24/24 兩個 Step 合計）。

**Step 3 — C04 架構修正方向確立 + collar joint 設計搜尋（2026-05-12）：**
Step 2 eccentric moment model 顯示 C04 問題的根本原因是**偏心力臂**（M = F × r_spar ≈ 0.050 m），
不是 adhesive 強度不足。`scripts/collar_joint_modes.py`（Strategy Pattern library，5 種 collar joint
mode：PeelBond、LoadLineYoke、FrictionClamp、ExternalShearKey、SaddleRingYoke，59 unit tests）與
`scripts/current_pathfinder_rib_collar_joint_design_search.py`（multi-mode design search，11 integration
tests）已把設計搜尋結果確立如下：
- **peel bond（現有構型）**：margin < 0，fail；bondline 需 > 50 mm 才 viable，超出幾何可行範圍
- **load-line yoke**：viable 但需 r_eff < 20 mm；在現有翼肋幾何下可行性偏緊
- **friction clamp**：N_c < 2000 N 即 viable；split clamp 構型幾何上可直接實施
- **external shear key**：兩片合計面積 < 500 mm² 即 viable；輕量替代方案
- **saddle ring yoke（推薦架構）**：conformal bonded ring 繞 spar OD + 一對切向 lug，消除
  outward peel moment；governing mode 改為 lug foot adhesive shear（不是 peel）；fast-model
  估算 pass，recommended fix = `HybridJoint(SaddleRingYoke + FrictionClamp)`

推薦 fix 見 `collar_joint_modes.py::recommended_c04_fix()`。這仍是 analytical / fast-model 估算，
不是 coupon test 或 FEM 簽核；C04 物理 coupon 仍是 Step 4 margin sign-off 的先決條件。

**3 m 翼板運輸接頭設計（2026-05-12）：**
`scripts/current_pathfinder_spar_splice_design.py` 針對 Step-1 freeze 的 structural half-span
`16.5 m`，在 3 m 翼板限制下設計 5 個 splice joints（y = 3 / 6 / 9 / 12 / 15 m），
全翼展共 10 個。接頭採用 CFRP internal spigot（4D overlap each side）+ external ferrule +
shear dog（承 torsion，不鑽穿主管壁）。注意：aero closure / materialized rib station grid
仍可延伸到約 `17.3 m`；splice report 與本段敘事以 structural freeze `16.5 m` 為準。
設計摘要（13 tests pass）：
- 所有接頭在 screening runner 中 pass，但 worst reported governing margin rounded to `0.000`
- y = 3 m 最重站：factored bending moment 4,437 N·m，spigot wall 自動 upsize 至 1.02 mm
  （預設 0.8 mm 不足）；這是 vendor/detail warning，不是 final splice margin sign-off
- torsion margin 全站 >> 1（shear dog 設計遠超 torsion 需求）
- 全翼展接頭總質量 **3.85 kg**，在 HPA 文獻 2.5–6 kg 範圍內
- 3 m 翼板限制確認鎖定：台灣自有貨車（普通小型車駕照 → GVW ≤ 3,500 kg → 貨台 2.7–3 m）
  與空運標準件限制雙重收斂；日本競賽可用 6 噸貨車，但 3 m 更保守

**Step 4 — P1 local load-path closure + mass-integrated pathfinder update（2026-05-12）：**
`scripts/current_pathfinder_p1_load_path_mass_closure.py` 把 Step 2 C04 fail evidence、Step 3
saddle-ring/yoke/clamp fix、3 m spar-splice mass 與 current closure basis 接成同一個
screening runner。輸出位於
`docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md` 與
`output/current_pathfinder_p1_load_path_mass_closure/`。final verdict 是
`p1_local_load_path_ready_for_coupon_fem`：

- baseline C04 eccentric peel margin `-0.893` 保留為現有 peel path fail；installed fix
  `saddle_ring_yoke_plus_secondary_clamp` 轉成 tangential lug / saddle ring load path 後 local
  surrogate pass。governing mode 是 secondary clamp torque，margin `0.8876`；saddle ring yoke
  adhesive shear margin `65.0672`。
- C04 fix mass `0.093839 kg` 與 spar-splice mass `3.847 kg` 已回灌 mass / CG / tail /
  closure。updated screening mass basis `106.828608 kg`；uncompensated CG `0.780039 m`
  明確 rejected，managed final CG `0.75 m` 需要 `0.057304 m` forward rebalance on 56 kg
  equivalent mass。
- tail trim/stability 仍 pass；updated bounded physical twist `1.906952 deg`，root bending
  ratio `0.971590`，closure verdict 仍是 `ready_for_fem_apdl_loadcase_package`。direct
  spar-pair stress-test 超過 3 deg 是 conservative mapping warning，不是 qualified
  aero-surface twist。
- QPROP/XROTOR 是獨立 propulsion lane，不用於 P1 structural blocker pass/fail。

工程邊界：這代表 P1 selected rib/torsion candidate 的 C04 load path 可以進 coupon/local
FEM；不是 final adhesive allowables、laminate buckling、tail hardware、splice production
detail 或 aircraft sign-off。下一步優先是 saddle-ring/yoke coupon + local FEM、secondary
clamp preload/friction protocol、lug/bond fillet detail，以及 C07 skin sag process coupon。

**Baseline A team release system 的舊 WO-001 package 已建立（2026-05-12）：**
`scripts/build_baseline_a_release.py` 會把目前 P1 mass-integrated closure source 收成
`output/baseline_A_team_release/`。舊 release verdict `baseline_A_release_system_ready` 是 historical/generated evidence under data-authority repair, not active current truth；current
release status 是 `baseline_A_data_authority_restored_wo006_unblocked`，只表示 bounded WO-006
可往下做，不是 release-ready。輸出的 geometry freeze、
mass budget、CG summary、drag/power budget、interface packs、manufacturing plan、carbon tube RFQ
screening spec、change-control rules 和 team work packages 只能當 screening evidence / coordination
material；它不新增物理功能，也不能被解讀成 current release authority、procurement truth 或 final
aircraft sign-off。AI work-order protocol 位於 `docs/AI_WORK_ORDER_PROTOCOL.md`，priority queue 位於
`docs/work_orders/QUEUE.md`。

**WO-002 — Baseline A mass / CG / margin ledger 已建立（2026-05-12）：**
`scripts/build_baseline_a_release.py` 現在會在同一個 release package 內輸出
`mass_budget.csv`、`cg_summary.json`、`margin_budget.md` 與
`mass_cg_margin_daily_review.md`。舊 ledger verdict `mass_cg_margin_ledger_ready` 是 historical/generated evidence under data-authority repair, not active current truth；current ledger
verdict 是 `mass_cg_authority_bounded_wo006_ready`。`98.5 kg`
是 current design mass authority；`106.828608 kg` 是 suspect P1 screening aggregate。computed
uncompensated CG `0.780039 m` 仍 `explicitly_rejected`、managed CG `0.75 m` 與
required forward rebalance `0.057304 m` 保留；C04 original peel margin `-0.893` 與
installed saddle/yoke/clamp governing margin `0.8876` 同時可見。所有目前 component
mass rows 都是 `estimate` confidence，不能被讀成 measured/frozen weight-and-balance；
QPROP/XROTOR 仍是獨立 propulsion lane，不參與 C04 / rib structural blocker verdict。

**WO-003 — Baseline A design-space freeze audit 已完成（2026-05-12）：**
審核 artifact 位於
`output/baseline_A_team_release/design_space_freeze_audit/`，verdict 是
`baseline_A_freeze_reasonable`。結論是目前沒有 nearby manufacturable candidate 明確觸發
Baseline A reopen：最佳 nearby fast-model row 約省 `4.63%` crank power，低於 5-8%
power reopen trigger，而且沒有 current downstream geometry / CG / torsion / splice /
P1 load-path chain。重要 watch item 是 release mass + tail CD0 charge 丟回 Stage-0
quick-screen 時約有 `-9 W` margin；這要在 WO-006 / WO-007 / WO-008 繼續收斂，不能被讀成
final mission sign-off，也還不是 explicit reopen evidence。

**WO-004 — Manufacturable smoothness / discretization audit 已完成（2026-05-12）：**
審核 artifact 位於
`output/baseline_A_team_release/manufacturable_geometry_audit/`，verdict 是
`geometry_freeze_needs_fix`。工程判讀是 Baseline A smooth pathfinder 沒有大型外形不連續或
explicit reopen trigger，可繼續作 team-release engineering basis；但連續尺寸尚未達到
shop/RFQ drawing control。這些是 manufacturability/RFQ gate，不是目前 Baseline A reopen 或
final aircraft sign-off。

**WO-005 — Carbon tube RFQ + procurement screening pack 已完成（2026-05-12）：**
artifact 位於 `output/baseline_A_team_release/carbon_tube_rfq_pack.md`、
`controlled_station_span_splice_manifest.csv`、`vendor_questionnaire.md`、
`procurement_risk_register.json`、`tube_splice_tolerance_requirements.csv` 與
`rfq_daily_review.md`。舊 verdict `carbon_tube_rfq_pack_ready` 是 historical/generated evidence under data-authority repair, not active current truth。WO-005 目前是 draft/vendor-screening only：
可用於整理 vendor screening questions，但不是 purchase order、supplier selection、shop drawing
release、RFQ control truth 或 final aircraft sign-off。`16.5 m` 是 local/splice screening only，
不是 RFQ control span、shop span 或 procurement truth；positive half-wing `y` convention、3 m splice
stations（3/6/9/12/15 m）與 0.30 m materialized rib basis 只能當 draft screening reference。
selected stiffness row `0.345 m` label、aero/rib extents `17.17-17.32 m`、airfoil/control/twist/transport
station contracts 都仍是 reference/open，不可被 vendor 當 drawing control。y = 3 m splice 的 zero bending
margin 被列為 vendor fit / ovality / knockdown / coupon-local-test warning；任何 vendor answer
若改變 tube OD/wall、layup/modulus、mass/CG、splice fit 或 3 m shipping feasibility，必須回
Baseline A change control，必要時觸發 spar-spec / procurement / reopen review。

## 8. 常用入口與角色

### A. Mission / upstream concept

- 入口：`scripts/birdman_upstream_concept_design.py`
- 角色：從 mission、pilot power、span cap、mass case、planform / twist / spanload bias
  產生上游概念候選。
- 注意：這條線是 mission contract 的上游來源之一，不是 FEM validation。

### B. Fourier-AVL / pipeline v2

- 入口：`scripts/fourier_avl_calibration_mvp.py`
- 角色：建立 Fourier command 與 AVL actual spanload 的 calibration evidence。
- 注意：必須明確指定 current `--report-json`。舊
  `birdman_mission_coupled_medium_search_20260503` 只可用於 legacy diagnostics，不能當 pathfinder evidence。

### C. Smooth geometry / loaded-Z / closure

- 入口：
  - `scripts/structure_budgeted_z_state_search.py`
  - `scripts/aero_structure_closure_mvp.py`
  - `scripts/direct_dual_beam_inverse_design.py`
- 角色：把 realized geometry、loaded-Z search、inverse route、Tier2 airfoil 與 closure 接起來。

### D. Empennage / trim / stability

- 入口：
  - `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md`
  - `docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md`
  - `scripts/current_pathfinder_tail_cg_trim_stability_screening.py`
  - `src/hpa_mdo/concept/safety.py::evaluate_trim_balance`
  - `src/hpa_mdo/aero/avl_exporter.py`
  - `src/hpa_mdo/aero/avl_stability_parser.py`
- 角色：把 all-moving horizontal tail / vertical tail 變成全機 trim、static stability、
  control authority、tail drag/mass、tailboom load 的 screening contract。
- 注意：v1 已可作為 tail-aware rib / rear-spar sensitivity 的 screening basis；仍不是 full
  flight dynamics、measured CG/mass manifest，也不是 tail hardware sign-off。

### E. Tail-aware rib / rear-spar sensitivity

- 入口：
  - `scripts/tail_aware_rib_rear_spar_sensitivity.py`
  - `docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md`
  - `scripts/tail_aware_aeroelastic_closure.py`
  - `docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md`
  - `scripts/current_pathfinder_materialized_rib_contract_audit.py`
  - `docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md`
  - `scripts/current_pathfinder_rib_torsion_rework_verdict.py`
  - `docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md`
  - `scripts/current_pathfinder_rib_torsion_design_search.py`
  - `docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md`
  - `scripts/current_pathfinder_rib_torsion_fem_calibration.py`
  - `docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md`
  - `docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md`
  - `scripts/current_pathfinder_positive_torque_zone_validation_package.py`
  - `docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md`
  - `scripts/current_pathfinder_rib_local_detail_geometry_freeze.py`
  - `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md`
  - `scripts/current_pathfinder_rib_local_detail_margin_run.py`
  - `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md`
  - `scripts/current_pathfinder_p1_load_path_mass_closure.py`
  - `docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md`
- 角色：把 committed tail/CG basis、physical rib station basis、rear-spar participation、
  warping knockdown、mass/CG bookkeeping 與 closure ranking 接成 tail-aware aeroelastic
  screening basis，並把 current pathfinder 的 rib station / bay / missing contract / skin sag /
  bond-collar / local FEM trigger materialize 成下一輪 hybrid rework 的前置 audit，再把
  candidate trade / closure rerun boundary / FEM package blockers 輸出成可重跑 verdict。
- 注意：rib/rear-spar sensitivity verdict 是 `ready_for_tail_aware_aeroelastic_closure`；
  material-family verdict 是 `foam_only_families_do_not_clear_current_aeroelastic_closure`；
  twist-source verdict 是 `ready_for_hybrid_rib_stiffness_rework`。closure baseline verdict 是
  `needs_aeroelastic_geometry_or_stiffness_rework`，但 rework verdict 已讓 selected hybrid
  basis 進入 closure-owned stiffness model。final CG managed row `0.75 m` 保留；
  早期未補償 tail+ribs mass CG 約 `0.801 m` 的警告不能靜音；P1 mass-integrated closure
  已把 tail/rib/C04 fix/splice mass 一起 charge，updated uncompensated CG `0.780039 m`
  仍 explicitly rejected，只能使用 managed final CG `0.75 m` row。direct spar-pair rotation -> AVL incidence
  目前只是 stress-test proxy，不是 qualified aero-surface twist；foam-only ribs cannot be used
  to claim the current closure blocker is solved。materialized rib audit 只確認 `121` stations /
  `120` bays 與 max bay `0.297063 m`，但 transport/control/airfoil/twist transition、
  skin sag、bond/collar/spar contact 和 torque-critical local FEM 仍是 blocked / needs-data。
  rework verdict 選出 `eps_balsa_cap_hybrid_10mm + bounded_65pct_screening` 作為 local
  FEM/coupon candidate；actual closure-owned hybrid rerun bounded physical twist 是
  `2.070 deg`，direct stress-test 是 `3.449 deg` 並保留為 conservative mapping warning。
  fast design-search loop 會掃 material / thickness / spacing / local reinforcement /
  rear participation 的 candidates，並把 selected fast row 送回 tail-aware closure rerun。
  目前 revised fast-loop selected row 是 10 mm uniform `0.30 m` carbon-collar/rear75，
  bounded twist `1.673592 deg`；CCX local-frame alignment verdict 是
  `fast_physical_model_verified_within_5pct`，代表 structural rows 的 revised fast-vs-CCX
  error 已壓到 `<=5%`，但 carbon/glass collar、bond/tube-wall、skin sag、buckling 仍不是
  final FEM truth。detailed local validation shortlist 已鎖 P1 selected row、P2 12 mm
  carbon-collar reserve、P3 10 mm glass-face collar manufacturability fallback；它只表示
  `selected_candidate_ready_for_detailed_local_validation`。
  positive y≈`2.328 m` local package 已建立：R067/R068/R069、B066-B069、R066/R070
  boundary、APDL guarded skeleton、coupon matrix 和 missing-data register 都已輸出；Step 4
  P1 closure 顯示 C04 saddle-ring/yoke/clamp load path 可以進 coupon/local FEM，且 collar/splice
  mass 已回灌到 closure。這仍不是 FEM signoff：transition/control station、C07 skin sag
  process、local FEM/coupon、hardware/laminate detail 還沒關。

### F. FEM/APDL / shell / load-factor spot-check

- 入口：
  - `scripts/phase14_maclocal_fem_package.py`
  - `scripts/phase15_candidate_load_factor_buckling_check.py`
  - `scripts/phase16_ccx_buckling_wire6_ramp.py`
  - `scripts/phase17_candidate_shell_buckling_tip_review.py`
- 角色：candidate-relevant equivalent-physics validation / review package。
- 注意：這不是 final composite/root/wire/rib/hardware certification。

### G. Drawing-ready package

- 入口：`scripts/export_drawing_ready_package.py`
- 角色：把可畫圖 artifact 收成 handoff package。
- 注意：drawing handoff boundary 不等於 external validation boundary。

### H. Producer / decision interface

- 入口：`python -m hpa_mdo.producer`
- 角色：提供外部 consumer / automation 用 machine-readable contract。
- 注意：它是 integration boundary，不是主 physics 問題本身。

### I. Collar joint analysis / C04 fix

- 入口：
  - `scripts/collar_joint_modes.py`（Strategy Pattern library：PeelBond、LoadLineYoke、
    FrictionClamp、ExternalShearKey、SaddleRingYoke + recommended_c04_fix()）
  - `scripts/current_pathfinder_rib_collar_joint_design_search.py`
- 角色：對 y≈2.328 m rib-to-spar collar joint 做多模式設計搜尋，識別 C04 bond peel 的架構修正
  方向；讀入 Step 1 freeze JSON，對 5 種 joint mode 執行 margin sweep 並輸出推薦構型。
- 注意：C04 現有 peel bond 構型 margin = −0.893（fail）；推薦架構為 saddle ring yoke + friction
  clamp，fast-model 估算 pass。P1 mass-integrated closure runner 已消耗這個 fix 並給出
  `p1_local_load_path_ready_for_coupon_fem`。59 unit tests + 11 integration tests pass。
  這是 analytical screening + local surrogate，不是 coupon test 或 FEM 簽核。

### J. 3 m 翼板 spar splice design

- 入口：`scripts/current_pathfinder_spar_splice_design.py`
- 角色：針對 Step-1 freeze structural half-span `16.5 m` 設計 3 m 翼板接頭（5 joints per
  half-wing，10 full-wing），採用 CFRP spigot + ferrule + shear dog，自動 upsize spigot wall，
  輸出 JSON + Markdown + CSV 接頭設計報告。不要把這裡的 16.5 m 與 aero closure /
  materialized rib station grid 的約 17.3 m station extent 混寫。
- 注意：所有接頭 pass，全翼展接頭質量 3.85 kg，y = 3 m 需自動 upsize spigot wall 至 1.02 mm。
  翼板 3 m 限制確認鎖定（台灣自有貨車 + 空運雙重限制）。13 tests pass。

### K. P1 load-path + mass-integrated closure

- 入口：
  - `scripts/current_pathfinder_p1_load_path_mass_closure.py`
  - `docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md`
  - `output/current_pathfinder_p1_load_path_mass_closure/`
- 角色：把 P1 C04 saddle-ring/yoke/clamp fix、3 m spar-splice mass、collar-fix mass、
  current closure basis、CG rebalance、tail trim/stability 和 calibrated fast-model boundary
  放進同一個可重跑 verdict。
- 注意：final verdict 是 `p1_local_load_path_ready_for_coupon_fem`。C04 可以進 coupon/local FEM；
  QPROP/XROTOR 是獨立 propulsion lane，不參與 structural blocker 判定。這不是 final adhesive、
  laminate、buckling、tail hardware、splice production detail 或 aircraft sign-off。

### L. Baseline A team release / AI work-order queue

- 入口：
  - `scripts/build_baseline_a_release.py`
  - `output/baseline_A_team_release/`
  - `docs/AI_WORK_ORDER_PROTOCOL.md`
  - `docs/work_orders/QUEUE.md`
  - `docs/work_orders/templates/work_order_template.md`
- 角色：把 current pathfinder / Baseline A 變成 team release package，讓施工、結構、控制、
  傳動、製造組能從同一組 freeze / interface / change-control artifacts 開始工作；同時讓
  後續 AI thread 依 priority queue 自動挑任務、驗證、更新文件、commit，並產生 reviewer prompt。
- 注意：old `baseline_A_release_system_ready` is historical/generated evidence under data-authority repair, not active current truth；current release status 是 `baseline_A_data_authority_restored_wo006_unblocked`，只放行 bounded WO-006 aero calibration。
  P1 仍只到 coupon/local FEM readiness；C04 fix 是 architecture-selected but coupon/local FEM
  pending；QPROP/XROTOR 保持 independent propulsion lane；大型 SU2、NSGA、propeller
  optimization、random disturbance simulator、full CAD automation 只進 queue，不在 release
  builder 任務中實作。WO-003 design-space freeze audit 的 verdict 是
  `baseline_A_freeze_reasonable`；WO-004 manufacturable geometry audit 的 verdict 是
  `geometry_freeze_needs_fix`，表示 release engineering 可繼續，但 RFQ/shop 前要補
  station/span/splice authority repair。old `carbon_tube_rfq_pack_ready` is historical/generated evidence under data-authority repair, not active current truth；WO-005 is draft/vendor-screening only。WO-006
  may proceed only as bounded aero calibration using `98.5 kg` and current pipeline span authority, not as release truth, RFQ/procurement truth, or final aircraft sign-off。

## 9. 現在不該再當主線的敘事

- `equivalent_beam` 作為正式 structural truth。
- 把 repo 描述成單純 OpenMDAO spar optimizer。
- 把 continuous wall-thickness optimum 直接當 manufacturable aircraft。
- 把 old README / old prompt 的 `VSP -> inverse design -> CFRP` 當完整主線。
- 把 producer / decision interface 當成 physics 主線本體。
- 把 rib、wire hardware、root fitting detail FEM 提前成上游 candidate-generation 主線，
  除非它們已被證明會改變 aero-structure closure 的候選排序。
- 把 horizontal / vertical tail 當成最後 FEM 才補的外觀件，或把 AVL hinged-control proxy
  當成 all-moving tail 的 production model。
- 把 QPROP/XROTOR propulsion sizing 混入 P1 C04 structural blocker 判定；它們只能是獨立
  propulsion lane。
- 把 `birdman_mission_coupled_medium_search_20260503`、`sample_1476`、`233 W`、`8642.9 m`
  當成 current mission evidence。
- 把舊的一維、舊 CFRP、legacy refresh、研究型 script output 當成目前 pathfinder 的 production truth。

## 10. 對未來 AI Agent 的工作規則

1. 先讀這份 `CURRENT_MAINLINE.md`，再讀 `README.md`。接 Baseline A team work 時，再讀
   `docs/AI_WORK_ORDER_PROTOCOL.md`、`docs/work_orders/QUEUE.md` 與
   `output/baseline_A_team_release/`。
2. 需要 commit-history truth 時，讀
   `docs/reports/2026-05-08_commit_history_report.md`，特別是 Phase J 和後續 addendum。
   需要逐 stage artifact / trust boundary 時，再讀
   `docs/reports/2026-05-09_phase_j_evidence_map.md`。
3. 不要用舊 prompt、舊 task pack 或舊 README 段落覆蓋 Phase J pipeline。
4. 若要使用舊 module / 舊 output，先判斷它屬於 current pathfinder evidence、
   reusable module / tool、legacy diagnostic，還是 quarantined source。只有第一類可以直接用於目前主線；
   第二類必須重新接 current contract；第三、四類不能變成 current claim。
5. 如果完成一系列同屬同一個 idea 的任務，而且它改變了目前主線、可用狀態、信任邊界或下一步優先順序，
   必須同步更新 `README.md` 和 / 或 `CURRENT_MAINLINE.md`。
6. 如果只做局部 test / script guardrail，請在文件中說清楚它是 claim-boundary / diagnostic，
   還是真正工程 validation。
7. 遇到工程問題時，不要只用軟體測試通過作結論；要用該領域工程師角度檢查物理假設是否合理。

## 11. 暫停中的主翼 mesh-native CFD / SU2 支線

這不是目前正式主線，也不是可用來背書人力飛機性能的 CFD 結果。2026-05-13 current-GO
no-BL completion case 已補上 finite route-level force history，但 BL/y+、grid V&V 與 drag
calibration 仍未完成；下列 2026-05-01 凍結支線仍是高保真氣動參考：

```text
OpenVSP main-wing sections
  -> mesh-native indexed wing
  -> Gmsh HXT / boundary-layer mesh
  -> SU2 marker-owned smoke
```

目前已證明：

- VSP-native section extraction 比舊 AVL-driven source 更接近設計者在 VSP 看到的主翼；
- 1.1M 級 wall-resolved BL mesh 可以生成並通過目前 mesh quality gate；
- SU2 可讀 mesh，`wing_wall` / `farfield` marker audit pass，4-thread smoke 可執行；
- current-GO no-BL completion case 可跑完 159 iterations 並寫出 finite CL/CD route evidence。

目前尚未證明：

- BL-resolved / grid-converged 可信 CL/CD/Cm；
- grid independence；
- 人力飛機低雷諾數 / boundary-layer / transition 物理合理；
- 5M+ cell 等級網格可穩定生成；
- half-wing symmetry route。

若未來 agent 要接這條線，先讀：

```text
hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md
```

不要從舊 STEP/BREP repair 報告或單次 SU2 smoke 直接開始改。
