# 可能的廠商資訊

這個資料夾收錄的是台灣碳纖維管供應端的前期研究資料，現階段最適合支援：

- `docs/GRAND_BLUEPRINT.md` 中的 `real vendor catalog / hardware catalog`
- 後續把假想 vendor catalog 逐步替換成真實 RFQ 候選
- 採購前的 supplier short-list 與欄位設計

目前內容判讀：

- `台灣HPA用碳纖維管供應商與適配性分析報告.pdf`
  偏供應商能力與 HPA 適配性評估，適合拿來整理 RFQ 對象與驗證重點。
- `台灣碳纖維管製造商型號與規格深度調查報告.pdf`
  偏型號/規格盤點，對建立真實 tube catalog 較有直接幫助，但仍需人工抽取成 CSV。

目前可直接拿來用的價值：

- 可先建立供應商白名單，例如 GTI、Pan Taiwan、YFCM、Chris、GR Applied Materials。
- 可反推真實 catalog 最少要蒐集哪些欄位：
  `vendor`, `series`, `process`, `od_mm`, `id_mm`, `wall_mm`, `max_length_mm`,
  `surface_finish`, `machining_support`, `joint_support`, `fatigue_or_torque_test`,
  `datasheet_available`, `rfq_required`, `source_url_or_doc`
- 可提前定義哪些是 HPA 真的重要但多數廠商未公開、必須 RFQ 才能確認的欄位：
  直線度、同心度、纖維角度/疊層、TDS、疲勞、最長交貨長度、MOQ、單價。

目前還不能直接做的事：

- 不能直接取代 `data/carbon_tubes.csv`，因為 PDF 內容還不是乾淨的結構化 SKU 表。
- 不能直接支援 M11 CLT 或 M12 控制分析，因為這批資料主要是採購/製造面，不是疊層失效或飛控導數。

建議後續落地順序：

1. 先從 PDF 人工抽出 5 到 20 筆可核對的真實 SKU 或代表尺寸。
2. 新增 `data/real_vendor_tubes.csv`，保留 `source_doc` 與 `source_page` 欄位。
3. 讓 9d/離散化流程能在「假想 catalog」與「真實 catalog」間切換比較。
