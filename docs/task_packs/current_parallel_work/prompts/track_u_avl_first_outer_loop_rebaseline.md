# Track U — AVL-First Outer-Loop Rebaseline

> 目標：把目前過重的 outer-loop 搜尋重新收斂成 `AVL / lightweight search first -> shortlist 再 candidate_rerun_vspaero confirm`。
> 這一包不是要把 `candidate_rerun_vspaero` 刪掉，而是把它從「每個 coarse candidate 都跑」降回「只有 shortlist / finalist 才跑」。

## 為什麼現在要做這包

最近 Track T 的 bounded search 已經證明：

- `candidate_rerun_vspaero` 路徑現在是能跑的
- 也已經能找到第一個 `clearance-pass region`
- 但這條路徑對每個候選都要做 OpenVSP 幾何重建 + VSPAero rerun，對 coarse search 來說過重

而 repo 其實早就有較快的舊路徑：

- `scripts/dihedral_sweep_campaign.py`
- AVL trim / stability / beta-sweep / aero gate
- 再把候選送進 inverse design

目前要做的是把這條舊路徑重新升格成正式預設的 outer-loop search path，而且要符合現在的主線敘事：

`target shape / multiplier search -> inverse design -> jig clearance / mass / manufacturing / discrete layup -> shortlist -> rerun-aero confirm`

## 你要做什麼

請把 outer-loop 工作模式重定義成兩段：

1. `search mode`
   - 預設使用 AVL / lightweight screening
   - 用來做倍率、上反角、clearance-pass region、stability/trim gate 搜尋
2. `confirm mode`
   - 只對 shortlist / finalist 使用 `candidate_rerun_vspaero`
   - 用來做較重的 geometry ownership / aero replay confirm

## 寫入範圍

你只能修改這些檔案：

- `docs/NOW_NEXT_BLUEPRINT.md`
- `project_state.yaml`
- `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
- `docs/task_packs/current_parallel_work/README.md`
- `docs/task_packs/current_parallel_work/AGENT_LAUNCH_PLAN.md`
- `docs/task_packs/current_parallel_work/HANDOFF_QUICKSTART.md`
- `docs/task_packs/current_parallel_work/TASKS.md`
- `docs/task_packs/current_parallel_work/history.md`
- `docs/task_packs/current_parallel_work/manifest.yaml`

如果你認為還需要補一份極短的 handoff 說明文件，可以新增在：

- `docs/task_packs/current_parallel_work/reports/`

但不要動 code。

## 不要碰

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/GRAND_BLUEPRINT.md`
- `configs/blackcat_004.yaml`
- 任一 `scripts/*.py`
- 任一 `tests/*.py`

## 你要寫清楚的內容

請把文件明確改成下面這個判斷：

- 目前慢的主因不是 rib
- 目前慢的主因是把 `candidate_rerun_vspaero` 拉成 coarse outer-loop 搜尋主路徑
- 正確方向是：
  - `AVL / lightweight outer-loop` 當預設搜尋
  - `candidate_rerun_vspaero` 當 shortlist / finalist confirmation

要明確寫出：

1. 為什麼改回 AVL-first 是合理的
   - AVL 既有路徑已經能做 trim / L/D / stability / beta sweep
   - 舊報告已顯示它可以支撐有效候選搜尋
   - 現在 immediate blocker 不是「需要每個候選都 full rerun」，而是要先高效找到合理候選

2. 什麼不能跟著退回去
   - 不能把 `candidate_rerun_vspaero` 完全刪掉
   - 不能把 replay ownership / confirm contract 當沒發生過
   - 不能把 current selected candidate 直接當 final winner

3. 新的近期順序
   - 先 AVL-first 搜尋 / recovery / pass-region / recovered-candidate screening
   - 再對 shortlist 做 `candidate_rerun_vspaero`
   - 然後才談 rib ranking sanity / finalist spot-check

## 成功標準

- 文件不再暗示「每個 outer-loop candidate 都應先走 rerun-aero」
- 下一個 agent 看文件時，會自然先用 AVL / lightweight search，而不是直接走最重路徑
- 文件保留 `candidate_rerun_vspaero` 的價值，但把它清楚降級成 downstream confirm path

## 最小必要驗證

這一包是 docs/planning 任務，所以最小驗證是：

- `project_state.yaml` 可 parse
- `docs/task_packs/current_parallel_work/manifest.yaml` 可 parse
- 所有你在 manifest 裡列到的 prompt / 文件路徑都存在
- `git diff --check` clean
