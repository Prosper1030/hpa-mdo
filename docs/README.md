# HPA-MDO 文件索引

這份文件是 `docs/` 的導航層，不取代根目錄的 [README.md](../README.md)。

- 人類使用者先看 [README.md](../README.md)。
- 想找正式 contract / 正式真值，先看下面的 `Current Mainline`。
- 想知道近期優先順序，先看 [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md)。
- 想看長期方向，才看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。

## Start Here

| 文件 | 角色 | 適合誰 |
|---|---|---|
| [README.md](../README.md) | Repo landing page，先講正式入口、閱讀路徑、第一個指令 | 第一次進 repo 的人 |
| [dual_beam_workflow_architecture_overview.md](dual_beam_workflow_architecture_overview.md) | 正式 dual-beam workflow 與資料流概觀 | 協作開發者 |
| [dual_beam_consumer_integration_guide.md](dual_beam_consumer_integration_guide.md) | consumer 如何接正式 decision output | 外部整合 / AI agent |
| [dual_beam_autoresearch_quickstart.md](dual_beam_autoresearch_quickstart.md) | built-in autoresearch 的最小可用入口 | AI / automation |

## Current Mainline

下面這些屬於目前應該優先對齊的「正式真值 / 正式 contract」：

| 文件 | 性質 | 說明 |
|---|---|---|
| [dual_beam_workflow_architecture_overview.md](dual_beam_workflow_architecture_overview.md) | 正式 workflow 真值 | 說明 dual-beam production / inverse-design / decision layer 怎麼串起來 |
| [dual_beam_decision_interface_v1_spec.md](dual_beam_decision_interface_v1_spec.md) | 正式 consumer contract | 定義 decision interface JSON |
| [dual_beam_consumer_integration_guide.md](dual_beam_consumer_integration_guide.md) | 正式 integration guide | 告訴 consumer 怎麼接 producer output |
| [dual_beam_autoresearch_quickstart.md](dual_beam_autoresearch_quickstart.md) | 正式 machine-readable 入口說明 | 對應 `hpa_mdo.autoresearch` |
| [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md) | 近期執行藍圖 | 告訴你 repo 現況下先做什麼 |

目前不應該拿來當主線 sign-off 的內容：

- `equivalent_beam` parity / regression 路徑
- 單次研究型 script 的臨時輸出
- 舊 phase report 的結論摘要，如果它和正式 workflow / contract 衝突，以正式主線文件為準

## Now / Next

| 文件 | 用途 |
|---|---|
| [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md) | 近期 3 到 5 個優先任務、暫緩項、開始條件與不該先做的事 |
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
| [hi_fidelity_validation_stack.md](hi_fidelity_validation_stack.md) | 高保真驗證層路線與依賴資料 |

## Reports / Research / Archive

這一區有價值，但定位不是 onboarding：

| 類別 | 路徑 | 說明 |
|---|---|---|
| phase / sweep reports | `docs/*phase*.md`, `docs/*report*.md` | 保存每輪工程探索、benchmark 與結果 |
| research notes | [research/](research/) | 深入研究與文獻整理 |
| codex prompts | [codex_prompts/](codex_prompts/) | 給 AI 代理執行特定任務的自包含 prompt |
| manuals / papers | [Manual/](Manual/), [Paper/](Paper/) | 外部工具與論文參考資料 |
| examples snapshots | [examples/README.md](examples/README.md) | 範例輸出快照 |

如果你不確定某份文件是不是現在要跟的真值，先回到 [README.md](../README.md) 或 `Current Mainline` 再決定。
