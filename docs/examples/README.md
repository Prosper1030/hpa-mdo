# 範例輸出快照

本目錄收錄 `examples/blackcat_004_optimize.py` 自動同步的 baseline 輸出，讓開發者不需先跑最佳化也能快速理解結果格式與內容。

如果你是第一次進 repo，請先看 [README.md](../../README.md)；想找整體文件入口與近期主線，請看 [docs/README.md](../README.md) 與 [NOW_NEXT_BLUEPRINT.md](../NOW_NEXT_BLUEPRINT.md)。這個目錄只負責提供「成功跑完後大概會看到什麼」的靜態快照。

目前提供：

- `optimization_summary.txt`：單次結構最佳化的文字摘要（質量分解、結構表現、段參數、計時資訊）。
- `beam_analysis.png`：撓度、扭轉、應力與質量摘要圖。

> 說明：這些檔案是快照範例；不同設定檔、版本或載重條件下，數值與圖形可能不同。

## 怎麼使用這些快照

- 想快速確認輸出格式是否合理，可以先對照這裡的 `optimization_summary.txt`。
- 想看圖表大概會長什麼樣，可以直接打開 `beam_analysis.png`。
- 想知道正式主線輸出與 decision contract，請不要只停在快照，改看：
  - [dual_beam_workflow_architecture_overview.md](../dual_beam_workflow_architecture_overview.md)
  - [dual_beam_consumer_integration_guide.md](../dual_beam_consumer_integration_guide.md)
  - [dual_beam_decision_interface_v1_spec.md](../dual_beam_decision_interface_v1_spec.md)

## 重要限制

- 這裡的快照是文件資產，不是目前設計 sign-off 的正式真值。
- 正式 structural truth / inverse-design artifacts 仍以 production workflow 實際輸出為準。
- 若快照與目前主線文件衝突，請以 [README.md](../../README.md) 和 [NOW_NEXT_BLUEPRINT.md](../NOW_NEXT_BLUEPRINT.md) 的定位說明為準。
