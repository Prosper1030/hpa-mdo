# Codex 任務：P5#22 範例輸出快照

## 背景

`docs/codex_tasks.md` 的 P5#22 一直掛著「範例輸出快照」未做。
README 與 onboarding 文件需要參考輸出，但目前 `output/blackcat_004/` 的檔案
是 gitignore 的，新貢獻者看不到「成功跑完」長什麼樣子。

## 任務

### 1. 建立 `docs/examples/` 目錄並放入快照

從目前 `output/blackcat_004/` 複製以下檔案到 `docs/examples/blackcat_004/`：

- `optimization_summary.txt` （會被 git track）
- `beam_analysis.png`
- `spar_geometry.png`
- `convergence.png`（如果有）

**注意**：這些檔案會 commit 到 repo，所以要確認：
1. 內容對應到目前的 baseline `val_weight: 14.3579 kg`
2. 圖片不要太大（每張 < 500 KB；如需縮減用 `pillow` resize）
3. txt 報告含 `Buckling index : -0.8555 (SAFE)` 那行（前次補強的結果）

### 2. 在 `docs/examples/blackcat_004/README.md` 寫一段描述（繁體中文）

```markdown
# Black Cat 004 範例輸出

本目錄保存 `examples/blackcat_004_optimize.py` 在 commit `<sha>` 跑完後的
標準輸出快照，作為新貢獻者的對照基準。

## 主要結果

- 全翼展總質量：14.36 kg
- 主翼梁壁厚範圍：0.6 – 0.8 mm
- 唯一綁定約束：tip_deflection（96.4% budget）
- 失效係數：-0.78（78% margin）
- 屈曲係數：-0.86（被動滿足）

## 重現方式

\`\`\`bash
hpa-optimize --config configs/blackcat_004.yaml --output-dir output/blackcat_004
\`\`\`

預期執行時間：~9 分鐘（M1 Mac mini）。
```

### 3. 更新主 `README.md`

在「快速開始」段落後加一行：
```markdown
> 範例輸出快照位於 [`docs/examples/blackcat_004/`](docs/examples/blackcat_004/)
```

### 4. `docs/codex_tasks.md` P5#22 標記 ✅

## 驗收

1. `git ls-files docs/examples/` 列出至少 4 個檔案（txt + 3 png）
2. txt 內容含 `Buckling index` 行
3. 主 README 有連結

## 不要做的事

- ❌ 不要把整個 `output/` 解除 gitignore
- ❌ 不要動程式碼，只是 copy + commit 文件
- ❌ 不要把舊 / 過期的快照放進去（先重跑一次 optimize 確認 14.3579）

## Git

單一 commit：`docs: 新增 docs/examples/blackcat_004 範例輸出快照（P5#22）`
