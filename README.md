# 胶片数字化帧号复核 API

按扫描顺序接收 2～100 帧的 OCR 帧号识别结果，基于动态规划为每帧指派一个
**严格递增**的帧号：自动舍弃误识别候选、推断未识别帧、标出缺失帧号，并给出
最优方案的代价明细。

- 语言/框架：Python 3.12 + FastAPI + Pydantic v2
- 算法：后缀动态规划（含字典序同分裁决）
- 置信分使用 `Decimal` 精确比较，避免浮点同分误判

## 一条命令启动

需要已安装 Docker（含 Compose 插件），在项目根目录执行：

```bash
docker compose up --build -d
```

- API 地址：`http://localhost:8000`
- 服务端口：`8000`（容器内外一致；可在 `docker-compose.yml` 的 `ports` 中修改宿主机端口）
- 交互式文档（Swagger UI）：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

停止服务：

```bash
docker compose down
```

## 接口

### `POST /api/v1/frame-reviews`

#### 请求参数

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `first` | int | 固定首帧号 |
| `last` | int | 固定末帧号，必须严格大于 `first` |
| `max_missing_between` | int | 相邻两帧之间最多允许缺帧数，0～10 |
| `frames` | 数组 | 按扫描顺序排列的 2～100 帧 |
| `frames[].id` | string \| int | 扫描帧唯一标识 |
| `frames[].candidates` | 数组 | OCR 候选，可为空 |
| `candidates[].frame_number` | int | OCR 识别帧号 |
| `candidates[].confidence` | number | OCR 置信分，0～100 |

#### 指派规则与代价

- 第 1 帧必须指派为 `first`，最后 1 帧必须指派为 `last`；
- 相邻指派帧号之差 ∈ `[1, max_missing_between + 1]`；
- 命中候选代价 = `100 - 置信分`；未命中任何候选（纯推断）代价 = `100`；
- 相邻两帧之间每缺 1 帧额外加 `30`；
- 取总代价最小的方案；总代价相同时，取**帧号序列字典序最小**的方案；
- 同一帧内同帧号出现多次时，仅保留置信分最高的一条（同分保留下标小者），
  其余作为重复候选舍弃；超出 `[first, last]` 的候选也会被舍弃。
- 在上述约束下无法形成合法序列时返回 HTTP `422`，错误体含
  `error`（`invalid_range` / `no_feasible_sequence`）与中文 `message`。

#### 请求示例

```bash
curl -s -X POST http://localhost:8000/api/v1/frame-reviews \
  -H 'Content-Type: application/json' \
  -d '{
    "first": 10,
    "last": 13,
    "max_missing_between": 2,
    "frames": [
      {"id": "scan-001", "candidates": [{"frame_number": 10, "confidence": 95}]},
      {"id": "scan-002", "candidates": [{"frame_number": 12, "confidence": 90}]},
      {"id": "scan-003", "candidates": [
        {"frame_number": 13, "confidence": 80},
        {"frame_number": 99, "confidence": 70}
      ]}
    ]
  }'
```

#### 响应示例

```json
{
  "first": 10,
  "last": 13,
  "max_missing_between": 2,
  "frame_count": 3,
  "assigned_frame_numbers": [10, 12, 13],
  "total_cost": 65,
  "candidate_cost_total": 35,
  "missing_penalty_total": 30,
  "missing_frame_numbers": [11],
  "missing_frame_count": 1,
  "discarded_candidate_count": 1,
  "frames": [
    {
      "position": 1,
      "id": "scan-001",
      "assigned_frame_number": 10,
      "source": "candidate",
      "matched_candidate_index": 0,
      "assigned_cost": 5,
      "missing_after": 1,
      "missing_penalty": 30,
      "discarded_candidates": []
    },
    {
      "position": 2,
      "id": "scan-002",
      "assigned_frame_number": 12,
      "source": "candidate",
      "matched_candidate_index": 0,
      "assigned_cost": 10,
      "missing_after": 0,
      "missing_penalty": 0,
      "discarded_candidates": []
    },
    {
      "position": 3,
      "id": "scan-003",
      "assigned_frame_number": 13,
      "source": "candidate",
      "matched_candidate_index": 0,
      "assigned_cost": 20,
      "missing_after": 0,
      "missing_penalty": 0,
      "discarded_candidates": [
        {"candidate_index": 1, "frame_number": 99, "confidence": 70, "reason": "out_of_range"}
      ]
    }
  ]
}
```

舍弃候选的 `reason`：

- `not_selected`：在最优方案中未被采用（典型误识别）；
- `out_of_range`：帧号超出固定的 `[first, last]` 范围；
- `duplicate_frame_number`：同帧内与更高置信分的候选帧号重复。

#### 无合法序列示例

帧号区间无法容纳全部扫描帧（如 3 帧却只给了 2 个帧号）：

```json
{
  "error": "no_feasible_sequence",
  "message": "帧号区间 [1, 2] 只有 2 个帧号，无法为 3 帧指派严格递增的帧号"
}
```

## 算法说明

令 `span = last - first`，第 i 帧的指派帧号写作 `first + d_i`。
合法条件：`d_0 = 0`、`d_{n-1} = span`、
`1 ≤ d_{i+1} - d_i ≤ max_missing_between + 1`。

后缀 DP（`app/solver.py`）：

```
dp[i][d] = match(i, d)
           + min over d' ∈ [d+1, d+max_step]  (30·(d'-d-1) + dp[i+1][d'])

match(i, d) = 100 - 置信分   若该帧存在帧号 first+d 的候选
            = 100            否则（推断）
```

- 时间复杂度 O(n · span · max_step)，最坏约 100 × 1090 × 11 ≈ 1.2×10⁶；
- 回溯时在保持最优代价的前提下每一步选最小偏移量，后缀最优与历史无关，
  因此贪心回溯得到的就是字典序最小的最优帧号序列。

## 本地开发（不使用 Docker）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── main.py       # FastAPI 入口与错误处理
│   ├── schemas.py    # Pydantic 请求/响应模型
│   └── solver.py     # DP 核心（纯标准库，可独立调用）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```
