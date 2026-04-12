# Autoresearch Experiment Governance v1

更新時間：2026-04-12 CST

這份文件定義 `hpa_mdo.autoresearch` 目前第一版最小 experiment governance。

目標不是做大型資料庫，而是先讓每一次 run 都能回答：

- 這次是用什麼輸入跑的
- 這次和上一次到底差在哪
- 兩次結果不同時，是同一 lineage 的重跑，還是真的換了輸入定義

## 1. 必記欄位

每筆 run record 至少應記：

- `run_id`
- `run_timestamp_utc`
- `status`
- `score_name`
- `score_rule`
- `score`
- `output_dir`
- `producer_name`
- `producer_interface_version`
- `decision_schema_name`
- `decision_schema_version`
- `producer_command`
- `producer_cli_overrides`
- `input_provenance`
- `run_fingerprint`
- `run_fingerprint_version`
- `git_commit_hash`
- `git_branch`
- `git_worktree_dirty`

其中 `input_provenance` 最低要求：

- `config.path` / `config.sha256`
- `design_report.path` / `design_report.sha256`
- `v2m_summary_json.path` / `v2m_summary_json.sha256`
- `config.snapshot_path` / `config.snapshot_success`
- `design_report.snapshot_path` / `design_report.snapshot_success`
- `v2m_summary_json.snapshot_path` / `v2m_summary_json.snapshot_success`
- `output_dir`
- `producer_cli_overrides`

## 2. 可選欄位

目前仍屬可選，但保留擴充空間：

- 額外 input source
- runtime environment tag
- job scheduler / batch id
- host / container image / Python version
- 更細的 artifact fingerprint

## 3. lineage 定義

### 視為不同 experiment lineage

以下任一項改變，就應視為不同 lineage：

- `config` 的 path 或內容摘要改變
- `design_report` 的 path 或內容摘要改變
- `v2m_summary_json` 的 path 或內容摘要改變
- `producer_cli_overrides` 改變
- `producer_name` 改變
- `producer_interface_version` 改變
- `decision_schema_name` 或 `decision_schema_version` 改變

### 視為同一 lineage 下的不同結果

以下改變，預設只算同一 lineage 的不同 run result，不另外切 lineage：

- `output_dir` 改變
- `run_id` / `run_timestamp_utc` 改變
- `git_commit_hash` 改變
- `git_branch` 改變
- `git_worktree_dirty` 改變
- score / mass / margin 改變
- 成功 / 失敗狀態改變

這表示 `run_fingerprint` 目前刻意只代表「輸入定義 lineage」，
不代表完整 execution environment。

## 4. run_fingerprint 規則

`run_fingerprint` 目前定義為：

- 先取一份標準化 payload
- payload 只包含 lineage 相關欄位
- 用 canonical JSON 排序序列化
- 再取 `sha256(...)[:12]`

標準化 payload 內容為：

- `producer_name`
- `producer_interface_version`
- `decision_schema_name`
- `decision_schema_version`
- `input_sources.config`
- `input_sources.design_report`
- `input_sources.v2m_summary_json`
- `producer_cli_overrides`

## 5. 操作原則

- summary / compare 應優先展示 `run_fingerprint`
- 最近 run 應顯示與前一次 run 的 provenance 差異
- 若多筆 run 共享同一 fingerprint，應顯示為同一 lineage group
- 若 fingerprint 一樣但結果不同，優先先看 `git_commit_hash` / `git_worktree_dirty`

## 6. 這版刻意不做的事

這版 governance 故意還不做：

- database-backed experiment registry
- UI dashboard
- multi-project global lineage graph
- 自動判定「哪個 commit 算 code lineage」
- 完整 reproducibility lockfile

先把最小 traceability 做穩，再往上疊實驗管理。
