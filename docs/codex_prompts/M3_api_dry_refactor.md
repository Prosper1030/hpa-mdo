# M3 — API DRY 重構（消除 server.py 與 mcp_server.py 重複）

## 背景

`src/hpa_mdo/api/server.py`（343 行）與 `src/hpa_mdo/api/mcp_server.py`（314 行）目前
**互相複製貼上**了三個輔助函式：

| 函式 | server.py 行數 | mcp_server.py 行數 | 內容是否完全相同 |
|------|---------------|---------------------|----------------|
| `_json_safe` | 42 | 30 | ✅ 字節級相同 |
| `_run_pipeline` | 83 | 46 | ✅ 邏輯相同 |
| `_result_to_dict` | 53 | 88 | ✅ 邏輯相同 |

每次有 `OptimizationResult` 加新欄位（例如先前 `buckling_index` 上線時），就要記得**兩邊都改**。
這是 latent drift bug 的溫床。

> 前提：本任務必須等 M2 hygiene pack 完成並 push 之後再開工。

## 目標

把這 3 個輔助函式抽到 `src/hpa_mdo/api/_shared.py`，讓 server.py 與 mcp_server.py 都 import。

**禁止**：
- 不要動任何 endpoint 簽章 / route 路徑 / MCP tool 名稱
- 不要把 endpoint handler 函式抽過去（只抽 helper）
- 不要在這個 PR 加 async wrapping、authentication、rate limiting（那些是另一個 mission）
- 不要把 `_error_response`（mcp_server 獨有）或 `_error_json` / `_success_json`（server 獨有）抽出去
  ——它們不是真正的重複，各自服務不同 wire format
- 不要動 FastAPI 的 `app = FastAPI(...)` 物件位置（必須留在 server.py）
- 不要 import `fastapi` 進 `_shared.py`（否則 mcp 無 fastapi 環境會炸）

## 要做的事

### Step 1：建立 `src/hpa_mdo/api/_shared.py`

```python
"""Shared helpers for the FastAPI and MCP servers.

This module is intentionally framework-agnostic — it must NOT import
fastapi or mcp, so both servers can use it without dragging optional
dependencies into the other.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np


def json_safe(obj):
    """Convert numpy scalar/array types to JSON-serializable Python types."""
    # 從 server.py 第 42 行（或 mcp_server.py 第 30 行）原封不動搬過來
    ...


def run_pipeline(config_yaml_path: str, aoa_deg: Optional[float] = None):
    """Execute the full HPA-MDO pipeline (config → aero → structure → result).
    
    Returns the OptimizationResult plus any intermediate state both
    servers need (mapped loads, aircraft, etc.). The exact return shape
    must match the *current* server.py / mcp_server.py contracts so the
    callers don't break.
    """
    # 從 server.py 第 83 行原封不動搬過來
    ...


def result_to_dict(result) -> dict:
    """Convert an OptimizationResult to a JSON-safe dict."""
    # 從 server.py 第 53 行（注意：mcp_server.py 第 88 行也有，內容應相同）原封不動搬過來
    ...
```

**重要實作細節**：

1. **比對兩邊的版本**：在開工前先 `diff` 兩邊的這 3 個函式，確認它們確實一致。
   如果有微小差異（例如 mcp 版多 round 一位數），以 **server.py 版本為準**，
   並在 commit message 裡記錄差異。

2. **import 路徑**：底部用 `_shared.py` 而不是 `shared.py`，因為這是 internal helper，
   不對外 export，底線開頭表示 private。

3. **不要**在 `_shared.py` 內 import `OptimizationResult`，只用 duck typing 取屬性。
   這樣可以避免循環 import 風險（雖然目前沒有，但保險）。

### Step 2：改寫 `src/hpa_mdo/api/server.py`

- 刪除 local 的 `_json_safe`、`_run_pipeline`、`_result_to_dict`
- 在 module top 加：
  ```python
  from hpa_mdo.api._shared import json_safe as _json_safe
  from hpa_mdo.api._shared import run_pipeline as _run_pipeline
  from hpa_mdo.api._shared import result_to_dict as _result_to_dict
  ```
- 用 alias 是為了讓 endpoint handler 完全不需要改動內部呼叫

### Step 3：改寫 `src/hpa_mdo/api/mcp_server.py`

- 同上：刪除 local 三個函式
- 加同樣的 import alias
- 注意 mcp_server.py 的 `_error_response` 與 `_make_server` **不要動**

### Step 4：跑測試 + 簡單煙霧測試

```
.venv/bin/python -m pytest -x -m "not slow" tests/test_api_server.py
```

如果有 mcp_server 的測試也跑（搜尋 `tests/test_mcp*.py`）。

如果沒有 mcp_server 的單元測試，**手動煙霧測試**：

```bash
.venv/bin/python -c "
from hpa_mdo.api._shared import json_safe, run_pipeline, result_to_dict
import numpy as np
print('json_safe ok:', json_safe(np.float64(3.14)))
print('imports ok')
"
```

確保 `_shared.py` 沒有語法錯誤、沒有循環 import。

### Step 5：驗證沒有 silently 改變行為

`grep -rn "_json_safe\|_result_to_dict\|_run_pipeline" src/hpa_mdo/api/`
應該只剩 import 行 + 使用點，不應該再有任何 `def _json_safe` / `def _run_pipeline` /
`def _result_to_dict`（除了 `_shared.py` 內的 public 名稱 `json_safe` / `run_pipeline` /
`result_to_dict`）。

## 驗收標準

1. `pytest -x -m "not slow"` 全綠（特別是 `test_api_server.py` 5 個測試都過）
2. `_shared.py` 不 import `fastapi`、不 import `mcp`、不 import `OptimizationResult`
3. server.py 與 mcp_server.py 的對外行為（endpoint / tool 簽章、回應 JSON 結構）
   **完全不變**
4. 三個 helper 函式只剩**一份實作**（在 `_shared.py`）
5. 跑 `wc -l src/hpa_mdo/api/*.py` 兩個檔案應該各少約 30–50 行
6. 新增的 `_shared.py` 約 80–120 行
7. 程式碼註解 / docstring 全英文（鐵律 #8）

## Commit 訊息範本

```
refactor: 抽出 API 共用 helper 至 _shared.py（消除 server / mcp_server 重複）

- 新建 src/hpa_mdo/api/_shared.py，集中 json_safe / run_pipeline /
  result_to_dict 三個 framework-agnostic helper
- server.py 與 mcp_server.py 改用 import alias，刪除各自 local 副本
- _shared.py 不 import fastapi 或 mcp，確保兩邊環境互不污染
- 行為等價：endpoint / MCP tool 簽章與回應 JSON 結構完全不變
```

## 完成後

```
.venv/bin/python -m pytest -x -m "not slow"
git add -A src/hpa_mdo/api/ docs/codex_prompts/M3_api_dry_refactor.md
git commit -m "..."
git pull --rebase --autostash origin main
git push origin main
```
