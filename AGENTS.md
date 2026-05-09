# AGENTS.md

本文件給 Codex / Claude / 其他 AI agent 使用。若本文件與使用者當下明確指令衝突，以使用者當下指令為準；若沒有衝突，請遵守本文件。

## Commit 規則

- 每完成一個獨立任務後，請自動執行 `git add -p`，只加入本任務相關檔案，然後 commit。
- 不要把多個獨立任務合進同一個 commit。
- Commit message 使用 conventional prefix，依實際任務調整：
  - `feat: ...`
  - `fix: ...`
  - `test: ...`
  - `refactor: ...`
  - `docs: ...`
- 範例：`test: 補強 test_fsi_coupling.py 功能測試`

## 工程審核規則

- 遇到工程問題時，拿到輸出後不要只當軟體工程師。
- 必須用該領域工程師角度審核結果是否合理，並主動提出物理假設、單位、載荷路徑、邊界條件、信任邊界與過度宣稱風險。
- 測試通過只代表程式行為符合目前 test contract，不代表航空結構、氣動或製造已 final sign-off。

## 文件同步規則

- `CURRENT_MAINLINE.md` 是目前主線的單一真相文件；`README.md` 是新使用者與新 agent 的入口。
- 如果完成一系列同屬同一個 idea 的任務，而且這系列任務改變了以下任一項，必須同步更新 `README.md` 和 / 或 `CURRENT_MAINLINE.md`：
  - 目前正式 pipeline；
  - 可用入口或推薦指令；
  - candidate 狀態；
  - engineering trust boundary；
  - 下一步優先順序；
  - 哪些結果可以 / 不可以對外宣稱。
- 如果任務只是局部 script、test 或 guardrail，但會影響未來 agent 對工程狀態的理解，也要在主文件中用一句話標明它的定位。
- 不要讓 README / CURRENT_MAINLINE 長期落後於 commit history；如果因為任務範圍不適合更新主文件，請在 final response 或 commit message 說明原因。

## 目前主線基準

後續 agent 判斷任務優先順序時，先以 Phase J pipeline 為基準：

```text
Mission contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape
-> Tier2 full-alpha airfoil selection
-> aero-structure closure
-> FEM/APDL / shell buckling / load-factor checks
```

舊的 `VSP -> inverse design -> jig shape -> CFRP` 敘事仍是重要子能力，但不再是完整主線描述。
