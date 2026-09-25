# 胶片数字化帧号复核 API

按扫描顺序接收 2～100 帧胶片扫描图的 OCR 帧号候选，使用**动态规划**为每帧指派
**严格递增**的帧号：可舍弃误识别候选，也可推断未识别帧；输出逐帧指派、被舍弃
的候选以及缺失帧号。

## 一条命令启动

```bash
docker compose up --build
```

服务启动后监听 **8000** 端口：

| 地址 | 说明 |
| --- | --- |
| http://localhost:8000 | 服务信息 |
| http://localhost:8000/docs | Swagger UI（可在线发请求） |
| http://localhost:8000/health | 健康检查 |
| **http://localhost:8000/review** | **帧号复核接口（POST，JSON）** |

后台运行：`docker compose up --build -d`；停止：`docker compose down`。

## 请求

`POST /review`，`Content-Type: application/json`

```json
{
  "frames": [
    {"frame_id": "scan-0001", "candidates": [{"frame_no": 1, "confidence": 98}]},
    {"frame_id": "scan-0002", "candidates": [
      {"frame_no": 2, "confidence": 12},
      {"frame_no": 3, "confidence": 91}
    ]},
    {"frame_id": "scan-0003", "candidates": [{"frame_no": 4, "confidence": 97}]}
  ],
  "first_frame_no": 1,
  "last_frame_no": 4,
  "max_missing": 1
}
```

| 字段 | 约束 | 说明 |
| --- | --- | --- |
| `frames` | 长度 2～100，按扫描顺序排列 | 每帧含 `frame_id` 与 0～100 个候选 |
| `frames[].candidates[].frame_no` | 整数 | OCR 识别出的帧号 |
| `frames[].candidates[].confidence` | 0～100（可小数） | 置信分 |
| `first_frame_no` | 整数 | **固定**指派给第 1 帧的帧号 |
| `last_frame_no` | 整数 | **固定**指派给最后 1 帧的帧号 |
| `max_missing` | 0～10 | 相邻两帧之间最多允许缺失的帧数 |

## 响应

```json
{
  "assignments": [
    {"frame_index": 0, "frame_id": "scan-0001", "frame_no": 1,
     "source": "candidate", "confidence": 98.0, "cost": 2.0, "candidate_index": 0},
    {"frame_index": 1, "frame_id": "scan-0002", "frame_no": 3,
     "source": "candidate", "confidence": 91.0, "cost": 9.0, "candidate_index": 1},
    {"frame_index": 2, "frame_id": "scan-0003", "frame_no": 4,
     "source": "candidate", "confidence": 97.0, "cost": 3.0, "candidate_index": 0}
  ],
  "discarded_candidates": [
    {"frame_index": 1, "frame_id": "scan-0002", "candidate_index": 0,
     "frame_no": 2, "confidence": 12.0, "reason": "not_selected"}
  ],
  "missing_frame_numbers": [2],
  "total_cost": 44.0,
  "cost_summary": {
    "candidate_cost_total": 14.0,
    "inferred_cost_total": 0.0,
    "gap_penalty_total": 30.0,
    "inferred_frame_count": 0,
    "missing_frame_count": 1
  }
}
```

* `assignments`：逐帧指派结果（顺序与请求一致），`frame_no` 严格递增。
  * `source=candidate`：采用了 OCR 候选，`candidate_index` 为候选在该帧
    `candidates` 数组中的下标；
  * `source=inferred`：该帧全部候选被舍弃，帧号为推断值。
* `discarded_candidates[].reason`：
  * `out_of_range`：候选帧号不可能出现在任何满足首末帧号/缺帧约束的合法序列中；
  * `duplicate_frame_no`：同帧存在相同帧号候选，仅保留置信分最高的一个；
  * `not_selected`：候选合法，但未被最优方案采用。
* `missing_frame_numbers`：首末帧号之间未被任何扫描帧占有的帧号。

## 指派规则（动态规划）

1. 第 1 帧固定取 `first_frame_no`，最后 1 帧固定取 `last_frame_no`；
2. 相邻帧号严格递增，且相邻指派帧号之差 `≤ max_missing + 1`；
3. 每帧可从候选中取一个帧号（**候选代价 = 100 − 置信分**），也可舍弃全部候选
   后推断帧号（**推断代价 = 100**）；
4. 相邻两帧之间**每缺 1 帧加 30** 的缺帧惩罚；
5. 取**总代价最小**的完整方案；总代价相同时，取帧号序列**字典序最小**的方案；
6. 无法形成合法序列时返回 `400` 与明确的中文错误信息（如帧数过多、缺帧超限）；
   请求参数不合法（置信分越界、帧数不在 2～100 等）返回 `422`。

> 说明：在首末帧号与帧数固定时，任何合法序列的总缺帧数恒为
> `last_frame_no − first_frame_no + 1 − 帧数`，因此缺帧惩罚对所有合法方案为同一
> 常数，只计入总代价，不影响方案选择；同分仍严格按字典序裁决。

## curl 示例

```bash
curl -X POST http://localhost:8000/review \
  -H 'Content-Type: application/json' \
  -d '{
    "frames": [
      {"frame_id": "s1", "candidates": [{"frame_no": 1, "confidence": 98}]},
      {"frame_id": "s2", "candidates": []},
      {"frame_id": "s3", "candidates": [{"frame_no": 3, "confidence": 97}]}
    ],
    "first_frame_no": 1,
    "last_frame_no": 3,
    "max_missing": 0
  }'
```

## 不使用 Docker（本地运行）

需要 Python 3.11+：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 测试

```bash
pip install -r requirements.txt pytest httpx
python -m pytest
```

测试包含 400 组随机小实例的动态规划 vs 暴力枚举对拍（同时校验最小代价与字典序
裁决）、边界条件与 API 集成测试。100 帧 × 相邻最多缺 10 帧的最坏规模下单次求解
约 0.15 秒。

## 项目结构

```
├── app/
│   ├── main.py      # FastAPI 路由、请求/响应装配、错误处理
│   ├── solver.py    # 动态规划求解器（纯函数，无框架依赖）
│   └── models.py    # Pydantic 请求/响应模型
├── tests/           # 单元、对拍与 API 集成测试
├── Dockerfile       # 镜像内安装依赖并启动 uvicorn
├── compose.yaml     # 单条命令启动，映射 8000 端口
└── requirements.txt
```
