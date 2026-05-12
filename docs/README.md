# HPA-MDO 文件索引

這份文件是 `docs/` 的導航層，不取代根目錄的 [README.md](../README.md)。

- 人類使用者先看 [README.md](../README.md)。
- 想先知道目前正式主線是什麼，先看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)。
- 想找正式 contract / 正式真值，先看下面的 `Current Mainline`。
- 想知道近期優先順序，先看 [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md)。
- 想看長期方向，才看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。

## Start Here

| 文件 | 角色 | 適合誰 |
|---|---|---|
| [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md) | 目前正式主線的單一真相文件 | 所有人，尤其是新進協作者與 AI agent |
| [README.md](../README.md) | Repo landing page，先講正式入口、閱讀路徑、第一個指令 | 第一次進 repo 的人 |
| [AI_WORK_ORDER_PROTOCOL.md](AI_WORK_ORDER_PROTOCOL.md) | Baseline A AI work-order protocol | 需要接任務、驗證、commit、產生 reviewer prompt 的 AI thread |
| [work_orders/QUEUE.md](work_orders/QUEUE.md) | Baseline A priority queue | 需要知道下一個可派工任務的人 |
| [baseline_A_team_release.md](../output/baseline_A_team_release/baseline_A_team_release.md) | Baseline A team release package | 施工、結構、控制、傳動、製造組共同起點；不是 final aircraft sign-off |
| [2026-05-08_commit_history_report.md](reports/2026-05-08_commit_history_report.md) | commit-derived Phase J pipeline report | 需要理解目前主線來源的人 |
| [2026-05-09_phase_j_evidence_map.md](reports/2026-05-09_phase_j_evidence_map.md) | Phase J deep evidence map / source quarantine | 需要逐 stage 看 artifact / candidate / trust boundary / gap，並避免舊 medium-search 資料污染的人 |
| [2026-05-09_empennage_trim_stability_contract_audit.md](reports/2026-05-09_empennage_trim_stability_contract_audit.md) | all-moving tail / trim / stability contract insertion | 需要把水平尾、垂尾、配平、靜穩定、控制 authority、tail drag/mass 接進 pathfinder 的人 |
| [2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md) | tail-aware rib / rear-spar and material-family sensitivity | 需要看 balsa baseline、EPS/XPS/structural foam rib family 對 mass / GJ / twist verdict 影響的人 |
| [2026-05-09_tail_aware_aeroelastic_closure.md](reports/2026-05-09_tail_aware_aeroelastic_closure.md) | tail-aware aeroelastic closure baseline | 需要看 balsa/50% baseline twist-source blocker 的人 |
| [2026-05-09_current_pathfinder_materialized_rib_contract_audit.md](reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md) | materialized rib station/bay contract audit | 需要確認 0.30 m rib bay 是否真的 materialized，以及 hybrid rework 前哪些 skin/bond/FEM data 仍 blocked 的人 |
| [2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md](reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md) | closure-owned hybrid rib / torsion verdict | 需要知道 selected hybrid basis 是否真的讓 bounded twist 過 3 deg，以及 local FEM/coupon 下一站的人 |
| [2026-05-09_positive_torque_zone_local_validation_package.md](reports/2026-05-09_positive_torque_zone_local_validation_package.md) | positive y≈2.328 m local FEM / coupon input package | 需要接 positive torque-critical rib-spar bond/collar FEM skeleton、coupon matrix、missing-data register 的人 |
| [2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md](reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md) | rib / torsion detailed local validation shortlist | 需要知道 current fast-model selected basis、保守/製造性 alternate，以及 detailed FEM/coupon 驗證範圍的人 |
| [2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md](reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md) | P1 y≈2.328 m geometry and allowable freeze sheet | 需要知道 spar tube OD/wall、collar/bondline/adhesive/skin 工程估算值、7 failure-mode preliminary margins，以及 APDL skeleton 已填值狀態的人 |
| [2026-05-11_current_pathfinder_rib_local_detail_margin_run.md](reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md) | P1 y≈2.328 m Step 2 refined analytical margin run | 需要知道 C04 bond peel eccentric moment model（margin −0.893，critical blocker）、C07 skin sag process pre-strain sweep、C02/C03 SCF、C05 Hertz curvature、C06 Lamé hoop 的人 |
| `scripts/collar_joint_modes.py` + `scripts/current_pathfinder_rib_collar_joint_design_search.py` | C04 collar joint 架構修正方向 + multi-mode design search | 需要知道 C04 peel bond fail 根本原因、saddle ring yoke 架構方向、5 種 joint mode 比較、59+11 tests 的人 |
| `scripts/current_pathfinder_spar_splice_design.py` | 3 m 翼板 spar splice design | 需要知道 5 joints/half-wing 設計、3.85 kg 全翼展質量、inboard spigot 1.02 mm、3 m 限制鎖定的人；runner half-span 以 structural freeze 16.5 m 為準 |
| [2026-05-12_current_pathfinder_p1_load_path_mass_closure.md](reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md) | P1 C04 load-path closure + mass-integrated pathfinder update | 需要知道 final verdict `p1_local_load_path_ready_for_coupon_fem`、saddle/yoke/clamp fix、splice/collar mass 回灌到 CG/tail/closure，以及 coupon/local FEM 邊界的人 |
| [legacy_blackcat004_downstream_reference.md](legacy_blackcat004_downstream_reference.md) | Black Cat 004 / OpenMDAO 舊 downstream 參考 | 需要查歷史工具、舊 quickstart、舊 DAG 的人 |
| [mesh_native_cfd_line_freeze.v1.md](../hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md) | 暫停中的主翼 mesh-native CFD / SU2 支線交接 | 需要接續 Gmsh/SU2/BL 網格與低雷諾數 CFD 的人 |

## Current Mainline

下面這些屬於目前應該優先對齊的「正式真值 / 正式 contract」：

| 文件 | 性質 | 說明 |
|---|---|---|
| [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md) | 最高優先的現況真值 | 定義現在 repo 真正主線、入口、legacy 邊界、能力上限 |
| [2026-05-08_commit_history_report.md](reports/2026-05-08_commit_history_report.md) | commit-derived 現況報告 | Phase J pipeline 與 Phase K guardrail addendum 的來源 |
| [2026-05-09_phase_j_evidence_map.md](reports/2026-05-09_phase_j_evidence_map.md) | Phase J 實際證據地圖 | 把每個 stage 對回目前 artifact / candidate / key number / trust boundary / next action，並標出 Stage 0-2 promoted-trace gap |
| [2026-05-09_phase_j_evidence_map_plan.md](reports/2026-05-09_phase_j_evidence_map_plan.md) | evidence map 前置計畫 | 這份 report 的 planning predecessor；保留設計意圖與優先順序來源 |
| [2026-05-09_empennage_trim_stability_contract_audit.md](reports/2026-05-09_empennage_trim_stability_contract_audit.md) | empennage contract / roadmap | 規定 all-moving H-tail / V-tail 不能最後才補，並定義 tail contract v0、full-aircraft AVL trim/stability audit、discrete tail-airfoil screening 的下一步 |
| [2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md) | rib / rear-spar material family sensitivity | balsa baseline 保留；foam-only EPS/XPS/structural foam 目前不清除 current closure twist blocker |
| [2026-05-09_tail_aware_aeroelastic_closure.md](reports/2026-05-09_tail_aware_aeroelastic_closure.md) | tail-aware aeroelastic closure baseline | fixed-point baseline 已收斂，但 balsa/50% direct spar-pair incidence stress-test 與 bounded physical projection 超出 twist bound |
| [2026-05-09_current_pathfinder_materialized_rib_contract_audit.md](reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md) | materialized rib station/bay audit | 121 full-wing stations / 120 bays 已 trace；skin sag、bond/collar、transition/control station 與 torque-zone FEM 仍 blocked / needs-data |
| [2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md](reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md) | rib / torsion rework verdict | `eps_balsa_cap_hybrid_10mm + bounded_65pct_screening` actual bounded twist clears 3 deg; direct stress-test remains conservative mapping warning; FEM/APDL package still blocked by local detail evidence |
| [2026-05-09_positive_torque_zone_local_validation_package.md](reports/2026-05-09_positive_torque_zone_local_validation_package.md) | positive torque-zone local package | R067/R068/R069 and B066-B069 FEM/coupon handoff with APDL guarded skeleton; no FEM margin claimed |
| [2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md](reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md) | detailed local validation shortlist | Locks the revised fast-model selected row as `selected_candidate_ready_for_detailed_local_validation`, plus heavier reserve and lower-complexity collar alternate; no final aircraft pass claimed |
| [2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md](reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md) | P1 geometry and allowable freeze sheet | Step 1 of the FEM/Coupon Plan: spar tube OD/wall derived from config, 8 missing-data items filled, preliminary margins computed for 7 failure modes; C07 skin sag (margin 0.03) and C04 peel (margin 2.57) are process-sensitive; APDL skeleton filled |
| [2026-05-11_current_pathfinder_rib_local_detail_margin_run.md](reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md) | P1 Step 2 refined analytical margin run | Step 2: C04 bond peel eccentric moment model gives margin −0.893 (critical blocker; requires physical coupon before Step 4 claim); C07 min viable pre-strain derived from sweep; SCF / Hertz / Lamé models applied to C02-C06 |
| `scripts/collar_joint_modes.py` + `scripts/current_pathfinder_rib_collar_joint_design_search.py` | C04 collar joint Step 3 — architecture fix direction | saddle ring yoke confirmed as C04 fix direction (eliminates peel eccentricity); 5-mode library + design search; 59 + 11 tests; analytical screening, not coupon/FEM sign-off |
| `scripts/current_pathfinder_spar_splice_design.py` | 3 m transport spar splice design | 5 joints per half-wing at y=3/6/9/12/15 m on structural freeze half-span 16.5 m; all pass; 3.85 kg full-wing; inboard wall 1.02 mm (auto-upsized); 3 m panel limit locked; 13 tests |
| [2026-05-12_current_pathfinder_p1_load_path_mass_closure.md](reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md) | P1 local load-path + mass-integrated closure update | final verdict `p1_local_load_path_ready_for_coupon_fem`; C04 fix mass 0.094 kg and splice mass 3.847 kg charged into mass/CG/tail/closure; QPROP/XROTOR kept independent |
| [baseline_A_team_release.md](../output/baseline_A_team_release/baseline_A_team_release.md) | Baseline A team release | release verdict `baseline_A_release_system_ready`; release artifacts, interface packs, change-control rules, and work packages; not final aircraft sign-off |
| [AI_WORK_ORDER_PROTOCOL.md](AI_WORK_ORDER_PROTOCOL.md) | AI work-order protocol | worker startup, verification minimum, report shape, escalation rules, and engineering honesty checklist |
| [work_orders/QUEUE.md](work_orders/QUEUE.md) | AI work-order queue | priority queue and next recommended Codex goal |
| [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md) | 近期執行藍圖 | 告訴你 repo 現況下先做什麼 |
| [task_packs/current_parallel_work/README.md](task_packs/current_parallel_work/README.md) | 多 agent 並行 task pack 入口 | 給需要快速 handoff / 派工的人與 AI agent |
| [task_packs/benchmark_basket/README.md](task_packs/benchmark_basket/README.md) | benchmark basket task pack 入口 | 給整理高保真 / ANSYS / APDL 案例的人與 AI agent |

暫停中的高保真氣動支線：

| 文件 | 性質 | 說明 |
|---|---|---|
| [mesh_native_cfd_line_freeze.v1.md](../hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md) | 支線交接 / freeze record | 整理 mesh-native VSP geometry、Gmsh HXT / BL mesh、SU2 設定、失敗原因、物理疑點與下一步試法；不是 validated CFD |

目前不應該拿來當主線 sign-off 的內容：

- `equivalent_beam` parity / regression 路徑
- 單次研究型 script 的臨時輸出
- 舊 phase report 的結論摘要，如果它和正式 workflow / contract 衝突，以正式主線文件為準

## Now / Next

| 文件 | 用途 |
|---|---|
| [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md) | 近期 3 到 5 個優先任務、暫緩項、開始條件與不該先做的事 |
| [work_orders/QUEUE.md](work_orders/QUEUE.md) | Baseline A work-order queue；目前下一個建議任務是 WO-001 design-space freeze audit |
| [EXECUTION_ROADMAP.md](EXECUTION_ROADMAP.md) | 細化版近期進度規劃；把多條工作軌道、啟動條件與完成判準拆開講清楚 |
| [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md) | 長期五階段藍圖；拿來看願景與跨 phase 依賴，不拿來排今天的工作 |
| [codex_tasks.md](codex_tasks.md) | 操作型 task log / 歷史 checklist；可當背景資料，但不是新使用者入口 |

## Deep Specs

這些文件適合在你已經知道主線之後，再往下讀：

| 文件 | 用途 |
|---|---|
| [dual_beam_decision_interface_v1_spec.md](dual_beam_decision_interface_v1_spec.md) | decision payload 詳規 |
| [dual_beam_mainline_theory_spec.md](dual_beam_mainline_theory_spec.md) | dual-beam mainline 理論背景 |
| [dual_beam_v2_mainline_spec.md](dual_beam_v2_mainline_spec.md) | mainline 架構與規格細節 |
| [controls_interface_v1.md](controls_interface_v1.md) | controls interface 定義 |
| [hi_fidelity_validation_stack.md](hi_fidelity_validation_stack.md) | 高保真驗證層的現況、限制、benchmark policy 與驗證階梯 |
| [research/high_fidelity_route_decision_2026-04-30.md](research/high_fidelity_route_decision_2026-04-30.md) | 高保真 VSP/ESP -> Gmsh -> SU2 route decision；定義 shell_v4 是 diagnostic branch，不是任意主翼 product route |

## Reports / Research / Archive

這一區有價值，但定位不是 onboarding：

| 類別 | 路徑 | 說明 |
|---|---|---|
| phase / sweep reports | `docs/*phase*.md`, `docs/*report*.md` | 保存每輪工程探索、benchmark 與結果 |
| research notes | [research/](research/) | 深入研究與文獻整理 |
| codex prompts | [codex_prompts/](codex_prompts/) | 給 AI 代理執行特定任務的自包含 prompt |
| manuals / papers | [Manual/](Manual/), [Paper/](Paper/) | 外部工具與論文參考資料 |
| examples snapshots | [examples/README.md](examples/README.md) | 範例輸出快照 |
| legacy Black Cat 004 | [legacy_blackcat004_downstream_reference.md](legacy_blackcat004_downstream_reference.md) | 舊 Black Cat / OpenMDAO / dual-beam downstream 入口與 DAG，歷史參考用 |

如果你不確定某份文件是不是現在要跟的真值，先回到 [README.md](../README.md) 或 `Current Mainline` 再決定。
