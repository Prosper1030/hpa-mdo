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
| [2026-05-08_commit_history_report.md](reports/2026-05-08_commit_history_report.md) | commit-derived Phase J pipeline report | 需要理解目前主線來源的人 |
| [legacy_blackcat004_downstream_reference.md](legacy_blackcat004_downstream_reference.md) | Black Cat 004 / OpenMDAO 舊 downstream 參考 | 需要查歷史工具、舊 quickstart、舊 DAG 的人 |
| [mesh_native_cfd_line_freeze.v1.md](../hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md) | 暫停中的主翼 mesh-native CFD / SU2 支線交接 | 需要接續 Gmsh/SU2/BL 網格與低雷諾數 CFD 的人 |

## Current Mainline

下面這些屬於目前應該優先對齊的「正式真值 / 正式 contract」：

| 文件 | 性質 | 說明 |
|---|---|---|
| [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md) | 最高優先的現況真值 | 定義現在 repo 真正主線、入口、legacy 邊界、能力上限 |
| [2026-05-08_commit_history_report.md](reports/2026-05-08_commit_history_report.md) | commit-derived 現況報告 | Phase J pipeline 與 Phase K guardrail addendum 的來源 |
| [2026-05-09_phase_j_evidence_map_plan.md](reports/2026-05-09_phase_j_evidence_map_plan.md) | 下一個專門 goal 計畫 | 建立 Phase J evidence map，先整理 artifacts / candidate / trust boundary |
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
