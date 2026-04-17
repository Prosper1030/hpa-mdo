# Dual-Beam Consumer Integration Guide

更新時間：2026-04-12 CST

這份文件是寫給外部 consumer 的整合指南。
目前目標 consumer 是像 `/Volumes/Samsung SSD/autoresearch-通用` 這種 repo 外的自動化系統。

這次的前提是：

- 不搬 repo
- 不做 monorepo
- 不直接碰 `autoresearch-通用`
- 先把 `hpa-mdo` 整理成穩定 producer

另外一個重要前提：

- `equivalent_beam` 只視為 legacy parity / regression 路徑
- 外部 consumer 不應再把 `equivalent_beam` cross-validation artifact 當成目前正式設計判準
- 正式判準請以 `dual_beam_production` 與 producer decision interface 為準

## 1. 正式推薦入口

### 正式推薦入口：CLI

第一版正式推薦入口是：

```bash
uv run python -m hpa_mdo.producer --output-dir /abs/path/to/run_dir
```

原因：

- repo 邊界最清楚
- 不需要外部 consumer import 內部 research script
- 最適合跨 repo、自動化、batch study、app orchestration
- stdout 會輸出 machine-readable producer manifest

### Python API：次推薦入口

如果 consumer 與 `hpa-mdo` 在同一個 Python 環境，且希望直接拿 Python object，可以用：

```python
from hpa_mdo.producer import JointDecisionProducerConfig, produce_joint_decision_interface

run = produce_joint_decision_interface(
    JointDecisionProducerConfig(output_dir="/abs/path/to/run_dir")
)
decision = run.decision_interface
```

這比較適合：

- notebook
- internal tooling
- 同 repo / 同 environment 測試

但跨 repo 的第一版正式整合，仍建議優先走 CLI。

## 2. CLI contract

### 呼叫方式

```bash
uv run python -m hpa_mdo.producer \
  --config /Volumes/Samsung\ SSD/hpa-mdo/configs/blackcat_004.yaml \
  --design-report /Volumes/Samsung\ SSD/hpa-mdo/output/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt \
  --v2m-summary-json /Volumes/Samsung\ SSD/hpa-mdo/output/direct_dual_beam_v2m_plusplus_compare/direct_dual_beam_v2m_summary.json \
  --output-dir /abs/path/to/run_dir
```

### CLI 固定行為

- 固定跑 `joint geometry + material workflow`
- 固定用正式 producer strategy
- 固定輸出 decision interface v1 相關 artifacts
- stdout 固定輸出 producer manifest JSON

### CLI stdout manifest

目前 manifest 會包含：

- `producer_name`
- `producer_interface_version`
- `search_strategy`
- `decision_schema_name`
- `decision_schema_version`
- `decision_status`
- `producer_cli_overrides`
- `input_provenance.config`
- `input_provenance.design_report`
- `input_provenance.v2m_summary_json`
- `input_provenance.output_dir`
- `artifacts.output_dir`
- `artifacts.report_path`
- `artifacts.summary_json_path`
- `artifacts.decision_json_path`
- `artifacts.decision_text_path`
- `design_statuses`

consumer 可以 parse 這份 manifest，但正式 payload 仍然是 decision JSON 本身。

其中 `input_provenance.*.sha256` 的目的是讓下游不只知道「用了哪個 path」，
也能知道「當時那個 path 的內容指紋是什麼」，避免同一路徑後續被覆寫時無法追蹤。

## 3. 會輸出哪些檔案

CLI / Python API 產出固定 artifacts：

- `direct_dual_beam_v2m_joint_material_report.txt`
- `direct_dual_beam_v2m_joint_material_summary.json`
- `direct_dual_beam_v2m_joint_material_decision_interface.json`
- `direct_dual_beam_v2m_joint_material_decision_interface.txt`

## 4. 下游應該吃哪個 JSON

### 正式推薦：只吃這個

- `direct_dual_beam_v2m_joint_material_decision_interface.json`

### 不建議當正式 contract

- `direct_dual_beam_v2m_joint_material_summary.json`

原因：

- summary JSON 含研究診斷與內部欄位，未來更可能演進
- decision interface JSON 才是刻意固化給 consumer 的 schema

## 5. 哪些內部檔案 / 腳本不應直接依賴

外部 consumer 不應直接依賴：

- [scripts/direct_dual_beam_v2m_joint_material.py](</Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py>)
- [scripts/direct_dual_beam_v2m_material_proxy.py](</Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_material_proxy.py>)
- phase31~phase36 note
- report text 的自然語言段落
- 任何 research 用的 stdout 字串

原因是這些都屬於內部 workflow engine 或研究說明，不是正式對外 contract。

## 6. 推薦給 autoresearch-通用 的第一版接法

### 第一版最穩的方式

1. `autoresearch-通用` 以 subprocess call `python -m hpa_mdo.producer`
2. 指定自己的 `output_dir`
3. parse CLI stdout manifest
4. 讀 `decision_json_path`
5. 僅以 decision interface JSON 作為正式下游輸入

### 為什麼不是先 import Python API

不是因為 Python API 不行，而是因為第一版跨 repo 整合時：

- CLI 邊界更穩
- 環境隔離更清楚
- 升版與回滾更簡單
- 更容易接 app / batch / reporting

## 7. 未來擴展是否夠用

這個 producer 邊界現在已經夠支撐第一版：

- autoresearch
- app orchestration
- batch study
- reporting pipeline

如果未來需求變成：

- 長期服務化
- 遠端 job queue
- 多 workflow 共用 producer registry

那再往 API server / orchestration layer 擴就好，現在還不需要搬 repo 或做 monorepo。
