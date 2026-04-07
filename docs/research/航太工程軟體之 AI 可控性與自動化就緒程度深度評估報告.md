# **航太工程軟體之 AI 可控性與自動化就緒程度深度評估報告**

在 2026 年的航太設計與多學科優化（MDO）領域，開發環境正經歷從「人機交互」向「人工智慧代理（AI Agent）驅動」的根本性轉變。隨著 AI 技術在質量檢查、製造執行以及軟體開發生命週期中的滲透率顯著提升，軟體的「AI 可控性」已成為衡量工具鏈先進程度的核心指標 。本報告針對一系列主流航太分析軟體，深入評估其自動化可行性（Automation Readiness），探討原生 API、命令列介面（CLI）與 GUI 綁架現象，並針對無人值守（Unattended）自動化轉接器的開發提供架構性建議。 \[1\]

**自動化就緒程度（Automation Readiness）之理論架構**

評估軟體的自動化能力，必須建立在標準化的技術就緒水平（TRL）與系統集成視角之上 。在企業環境中，流程自動化適合度框架（PASF）將業務流程劃分為不同的自動化區域，其中僅有約 27% 的流程被視為「立即自動化」的候選對象 。航太工程軟體的特殊性在於其物理計算的複雜性與遺留代碼的沈重負荷。 \[1\]

一個高自動化就緒的軟體應具備以下特徵：首先是確定性（Determinism），即在相同的輸入下產生可預測的狀態變遷；其次是無狀態操作能力，允許 AI 代理在無須人工干預的情況下初始化與銷毀運算實例；最後是透明的錯誤反饋機制，而非依賴視覺化彈窗 。 \[1\]

| **自動化就緒等級 (ARL)** | **特徵描述** | **典型交互模式** | **數據交換方式** | 
|---|---|---|---|
| ARL 5 (原生 AI 友好) | 具備完整 Python/C++ API，支持內存級數據訪問 | 函數調用 (Shared Memory) | JSON/NDArray | 
| ARL 4 (高度可自動化) | 強大的 CLI，支持完整的配置驅動模式 | subprocess (stdin/stdout) | 結構化文本 (XML/YAML) | 
| ARL 3 (腳本化可行) | 具備宏命令或內建腳本語言 (如 AngelScript) | 腳本加載與遠程觸發 | 文件 IO | 
| ARL 2 (GUI 依賴型) | 核心邏輯嵌入 GUI，CLI 功能極其有限 | RPA / 鍵盤滑鼠模擬 | 專有二進位文件 (.xfl) | 
| ARL 1 (封閉系統) | 嚴格綁定圖形界面，無外部接口 | 人工點擊 | 視覺化截圖 | 



**航太分析工具之類別化自動化評估**

**原生 Python API 與高階 headless 系統**

在當前的軟體清單中，OpenVSP 與 SU2 代表了自動化技術的最前沿。這些工具的共同點在於其設計之初便考慮了大型優化框架的集成需求，而非僅僅作為單機桌面應用。

OpenVSP (Open Vehicle Sketch Pad) 內置了強大的 C++ API，並通過 SWIG (Simplified Wrapper and Interface Generator) 提供了對 Python 的原生支持 。這使得 OpenVSP 能夠在無圖形介面（Headless）的情況下運行，直接集成到外部軟體程序中進行參數化研究與優化 。API 函數涵蓋了從幾何定義、CFD 網格生成到 VSPAERO 求解器的所有功能 。對於 AI 代理而言，這種內存級別的交互避開了文件系統的延遲，且能夠即時捕捉到 API 錯誤對象，而非依賴日誌解析 。 \[1\]\[2\]

SU2 則是另一個極致自動化的範例。作為一個專門為高效率計算（HPC）設計的偏微分方程（PDE）求解套件，SU2 的執行完全由配置文件（.cfg）驅動 。它不僅提供 CLI 模組，還分發了一系列 Python 腳本（如 parallel\_[computation.py](computation.py) 和 shape\_[optimization.py](optimization.py)），這些腳本協調多個 C++ 組件完成複雜的分析任務 。PySU2 接口更進一步，允許用戶定義 Python 函數來干預物理求解過程，這為 AI 代理提供了極深的控制權 。 \[1\]\[2\]

**強大且友善的命令列介面 (CLI) 工具**

此類別軟體雖然缺乏內存級 API，但其結構化且確定性的文字交互模式，使其成為 AI 代理通過 subprocess 模組進行控制的理想對象 。代表性工具包括 Mark Drela 教授開發的 AVL、XFOIL 與 ASWING。 \[1\]\[2\]

AVL (Athena Vortex Lattice) 通過讀取文字格式的幾何文件與運行指令進行工作 。如 PX4 開發的 AVL 自動化工具所示，通過 Python 生成 .avl 幾何定義與 .yml 參數文件，再由 [process.sh](process.sh) 調用 AVL 二進位文件，可以實現全自動的氣動係數提取 。其輸出的 custom_vehicle_stability_derivatives.txt 包含了精確的穩定性導數（如

 等），AI 代理可以輕易地解析這些固定格式的數據 。 \[1\]\[2\]

XFOIL 的自動化邏輯與 AVL 類似，但在處理交互式 Prompt 時需要更精細的控制。開發者通常使用 pexpect 或 Python 的非阻塞流讀取器（NonBlockingStreamReader）來與 XFOIL 進行實時對話，以避免終端緩衝區阻塞 。雖然 XFOIL 是以 Fortran 編寫，而現代封裝如 xfoil_wrapper 嘗試將其整合進 Python 流程，但核心依然是基於進程間通信的 CLI 交互 。 \[1\]\[2\]

| **軟體名稱** | **API/CLI 類型** | **核心優勢** | **適合 AI 代理的場景** | 
|---|---|---|---|
| OpenVSP | C++/Python API | 內存級操作，Headless 支持 | 大規模參數掃描與複雜幾何生成 | 
| SU2 | CLI + Python Wrapper | 配置文件驅動，MPI 並行支持 | 高保真度 CFD 與形狀優化 | 
| AVL | 純文字 CLI | 輸入輸出定義清晰 | 早期概念設計與穩定性評估 | 
| XFOIL | 交互式 CLI | 氣動數據計算速度極快 | 翼型分析與極曲線生成 | 
| ASWING | CLI + 數據腳本 | 結構與氣動耦合分析 | 柔性機翼與氣動彈性計算 | 



**「GUI 綁架」與封閉系統的典型特徵**

相較於上述工具，XFLR5 是「GUI 綁架」最顯著的代表。雖然 XFLR5 基於 XFOIL 開發，但其在進化過程中將大量計算邏輯與 Qt 框架的圖形事件循環深度耦合 。 \[1\]\[2\]

根據 XFLR5 開發者 André Deperrois 的明確說明，XFLR5 的腳本功能僅限於翼型分析，飛機層級的分析腳本僅在後續的付費版 flow5 中實現 。XFLR5 的啟動雖然支持少數命令行參數（如 OpenGL 格式選擇），但無法在無 GUI 模式下執行飛機的 3D 面元法計算或穩定性分析 。此外，XFLR5 使用二進位的 .xfl 項目文件格式（雖然部分組件如翼型和平面定義支持 XML 導入導出），這對 AI 代理來說極難進行非侵入式的修改 。 \[1\]\[2\]

這種「GUI 綁架」造成的後果是，AI 代理必須使用如 pyautogui 之類的圖形自動化包來模擬人手的點擊與鍵盤輸入 。這類自動化方案極端脆弱，任何 UI 的微小跳動、彈窗或解析度變化都會導致自動化流程崩潰 。 \[1\]\[2\]

在 CAD 領域，SolidWorks 同樣面臨類似挑戰。雖然它有 COM API，但其架構依然沈重且高度依賴本地 GUI 環境。相比之下，雲端原生的 Onshape 通過 REST API 提供數據級訪問，AI 代理可以直接通過 HTTP 請求讀取與修改設計文檔，無需任何圖形渲染 。 \[1\]\[2\]

**XFLR5 與 AVL 無人值守轉接器（Adapter）的技術瓶頸**

要將 XFLR5 或 AVL 轉化為可由 AI 代理調用的無人值守組件，開發者將面臨底層架構上的重大挑戰。

**XFLR5 的瓶頸：圖形環境與狀態不透明**

**AVL 的瓶頸：進程管理與並行開銷**

**轉接器 (Adapter) 之架構建議**

為了克服上述瓶頸，建議採用「六角架構（Hexagonal Architecture）」或「埠與轉接器（Ports and Adapters）」模式，將分析工具封裝為具備統一接口的微服務。

**建議一：分層轉接器架構**

AI 代理應與「領域服務層」交互，而非直接操作原始軟體。

• **API 抽象層 (Port)**：定義標准的飛機數據模型，如 run_stability_analysis(plane_model, flight_condition)。

• **具體轉接器層 (Adapter)**：

• **AVL Adapter**：負責將模型轉換為 .avl 文件，啟動 subprocess，處理非阻塞輸出，並使用正則表達式解析 custom_vehicle_body_axis_derivatives.txt 。 \[1\]\[2\]\[3\]\[4\]\[5\]\[6\]\[7\]

• **XFLR5 Adapter**：如果必須使用 XFLR5，建議跳過 GUI 自動化，轉而編寫底層文件操作邏輯。通過修改 XML 格式的平面定義文件並利用 flow5 的腳本接口（如果可用）進行替代，或使用 pyautogui 在隔離的 Xvfb 環境中運行，並將所有日誌重定向到數據庫 。 \[1\]\[2\]\[3\]\[4\]\[5\]\[6\]\[7\]

**建議二：利用 OpenMDAO 進行文件包裝 (File Wrapping)**

對於 AVL 這種文件驅動的軟體，最佳架構是將其包裝為 OpenMDAO 的一個 Component 。 \[1\]\[2\]\[3\]\[4\]\[5\]\[6\]\[7\]

**建議三：轉向「數據驅動」而非「操作驅動」**

在 2026 年，最成功的自動化方案是直接操作軟體的底層數據存儲。

**結論與前瞻：2026 年的 AI 可控性趨勢**

航太工程軟體的未來不在於功能的多寡，而在於其與 AI 生態系統的集成深度。分析顯示，OpenVSP 和 SU2 等「API 優先」的工具正迅速成為自動化 MDO 的標準，而 XFLR5 則因「GUI 綁架」逐漸邊緣化，被迫轉向作為教學工具而非自動化生產線的核心 。 \[1\]\[2\]\[3\]\[4\]\[5\]\[6\]

對於需要建構全自動 AI Agent 系統的團隊，建議：

1\.	**首選原生 API 軟體**：盡可能將工作流遷移至 OpenVSP 和 SU2。

2\.	**標準化 Adapter 設計**：對於 AVL/XFOIL，使用 OpenMDAO 進行標準化封裝，並實施非阻塞的進程監控。

3\.	**隔離與虛擬化**：對於必須使用的 GUI 工具，必須在容器化的虛擬顯示環境中運行，並建立基於心跳監控的失敗重啟機制。

隨著模型上下文協議（MCP）的普及，未來的航太軟體將演化為一組「工具集」，AI 代理可以像調用函數一樣調用氣動求解器、結構分析器與 CAD 生成器，最終實現真正的無人駕駛設計流程 。 \[1\]\[2\]\[3\]\[4\]\[5\]\[6\]

1\. <https://www.psware.com/aerospace-ai-at-scale-the-new-standard-for-speed-quality-and-readiness-in-2026/> (AI-Assisted Execution in Aerospace: Redefining Speed, Quality, and Readiness in 2026)

2\. <https://www.researchgate.net/publication/402026643_From_Suitability_to_Blueprint_A_Unified_Framework_for_Agentic_AI_Process_Automation_in_Enterprise_Environments_EIGENVECTOR_RESEARCH_From_Suitability_to_Blueprint> (A Unified Framework for Agentic AI Process Automation in Enterprise Environments EIGENVECTOR RESEARCH From Suitability to Blueprint - ResearchGate)

3\. <https://openvsp.org/pyapi_docs/latest/> (OpenVSP Python API Documentation — Project name not set ...)

4\. <https://openvsp.org/api_docs/latest/> (Documentation for the OpenVSP API)

5\. <https://openvsp.org/api_docs/latest/group___a_p_i_utilities.html> (General API Utility Functions - OpenVSP API Documentation)

6\. <https://openvsp.org/api_docs/latest/> (Documentation for the OpenVSP API)

7\. <https://groups.google.com/g/openvsp/c/nTDm2SqNDEc> (Python Api setup - Google Groups)