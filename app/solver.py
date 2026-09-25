"""帧号指派的动态规划核心。

问题描述
--------
扫描得到 n 帧（按扫描顺序排列），每帧有 0 个或多个 OCR 候选帧号及置信分。
已知整卷胶片的首帧号 ``first``、末帧号 ``last``，以及相邻两帧之间最多允许
跳过 ``max_missing_between`` 个胶片帧号。

- 候选命中代价：100 - 置信分（0～100）
- 该帧没有命中任何候选（纯推断）：100
- 相邻两帧之间每缺 1 帧：+30

要求给每帧指派一个严格递增的帧号，使总代价最小；总代价相同时，帧号序列
按字典序取最小。第一帧指派为 ``first``、最后一帧指派为 ``last``。

实现思路
--------
令 span = last - first，第 i 帧（0-based）指派到 first + d_i。
合法序列满足 d_0 = 0、d_{n-1} = span 且
1 <= d_i - d_{i-1} <= max_missing_between + 1。

定义后缀 DP：

    dp[i][d] = 第 i 帧取 first + d 时，第 i..n-1 帧的最小总代价（不含 i 之前
               的缺帧代价）

转移：

    dp[i][d] = match_cost(i, d)
             + min over d' in [d+1, d+max_step] of
                   (30 * (d' - d - 1) + dp[i+1][d'])

回溯时在保持最小代价的前提下每一步选最小的 d，由于后缀代价与历史无关，
这恰好得到字典序最小的最优序列。

置信分可能带小数，统一用 Decimal 精确比较，避免浮点同分误判。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


# ---- 代价常量 ----
INFER_COST = Decimal("100")        # 未命中任何候选时的推断代价
MISSING_FRAME_PENALTY = 30         # 每缺 1 帧的额外代价
CONFIDENCE_BASE = Decimal("100")   # 候选代价 = 100 - 置信分

# 业务边界
MIN_FRAMES = 2
MAX_FRAMES = 100
MIN_MISSING_GAP = 0
MAX_MISSING_GAP = 10


class ReviewError(Exception):
    """业务校验失败的基类，携带机器可读的 code。"""

    code = "review_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidRangeError(ReviewError):
    code = "invalid_range"


class NoFeasibleSequenceError(ReviewError):
    code = "no_feasible_sequence"


def _to_decimal(value: Any, field: str) -> Decimal:
    """把 JSON 中的数字转成 Decimal；拒绝 NaN/Infinity 等非法数值。"""
    try:
        result = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - 统一转成业务错误
        raise InvalidRangeError(f"{field} 必须是 0～100 之间的有限数值") from exc
    if not result.is_finite():
        raise InvalidRangeError(f"{field} 必须是 0～100 之间的有限数值")
    return result


def _json_number(value: Any) -> Any:
    """把 Decimal 转回 JSON 友好的 int/float。"""
    if isinstance(value, Decimal):
        integer = value.to_integral_value()
        if integer == value:
            return int(integer)
        return float(value)
    return value


def solve_review(payload: dict[str, Any]) -> dict[str, Any]:
    """执行帧号复核。

    入参字段：
        first / last: int，固定首末帧号（last > first）
        max_missing_between: int，0～10
        frames: [{id, candidates: [{frame_number: int, confidence: 0~100}]}]

    返回逐帧指派、每帧舍弃的候选、缺失帧号与各项代价汇总。
    参数不合法时抛 InvalidRangeError，无合法序列时抛 NoFeasibleSequenceError。
    """
    frames = payload.get("frames")
    if not isinstance(frames, list) or not (MIN_FRAMES <= len(frames) <= MAX_FRAMES):
        raise InvalidRangeError(
            f"frames 数量必须在 {MIN_FRAMES}～{MAX_FRAMES} 之间"
        )

    first = payload.get("first")
    last = payload.get("last")
    gap = payload.get("max_missing_between")

    if not isinstance(first, int) or isinstance(first, bool):
        raise InvalidRangeError("first 必须是整数帧号")
    if not isinstance(last, int) or isinstance(last, bool):
        raise InvalidRangeError("last 必须是整数帧号")
    if last <= first:
        raise InvalidRangeError("last 必须严格大于 first（帧号按扫描方向递增）")
    if (
        not isinstance(gap, int)
        or isinstance(gap, bool)
        or not (MIN_MISSING_GAP <= gap <= MAX_MISSING_GAP)
    ):
        raise InvalidRangeError(
            f"max_missing_between 必须是 {MIN_MISSING_GAP}～{MAX_MISSING_GAP} 的整数"
        )

    n = len(frames)
    span = last - first
    max_step = gap + 1  # 相邻指派帧号之差上限（差 1 表示不缺帧）

    # ---- 解析每帧候选 ----
    # best[i]: {帧号 -> (置信分 Decimal, 该帧号最终采用的候选下标)}
    # 同一帧内同帧号只保留置信分最高的一条（同分保留下标小的），其余舍弃。
    parsed: list[tuple[Any, list[dict[str, Any]]]] = []
    best_by_frame: list[dict[int, tuple[Decimal, int]]] = []
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict) or "id" not in frame:
            raise InvalidRangeError(f"第 {i + 1} 帧缺少 id 字段")
        frame_id = frame["id"]
        raw_candidates = frame.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise InvalidRangeError(f"帧 {frame_id!r} 的 candidates 必须是数组")

        cleaned: list[dict[str, Any]] = []
        best: dict[int, tuple[Decimal, int]] = {}
        for j, cand in enumerate(raw_candidates):
            if not isinstance(cand, dict):
                raise InvalidRangeError(
                    f"帧 {frame_id!r} 的第 {j + 1} 个候选格式不正确"
                )
            number = cand.get("frame_number")
            if not isinstance(number, int) or isinstance(number, bool):
                raise InvalidRangeError(
                    f"帧 {frame_id!r} 的第 {j + 1} 个候选 frame_number 必须是整数"
                )
            confidence = _to_decimal(
                cand.get("confidence"),
                f"帧 {frame_id!r} 的第 {j + 1} 个候选 confidence",
            )
            if not (Decimal("0") <= confidence <= CONFIDENCE_BASE):
                raise InvalidRangeError(
                    f"帧 {frame_id!r} 的第 {j + 1} 个候选 confidence 必须在 0～100 之间"
                )
            cleaned.append(
                {
                    "index": j,
                    "frame_number": number,
                    "confidence": confidence,
                }
            )
            # 同帧号取最高置信分；同分保留先出现（下标更小）的。
            incumbent = best.get(number)
            if incumbent is None or confidence > incumbent[0]:
                best[number] = (confidence, j)
        parsed.append((frame_id, cleaned))
        best_by_frame.append(best)

    # ---- 可行性前置检查 ----
    # 相邻两帧帧号差至少 1、至多 max_step。
    if span < n - 1:
        raise NoFeasibleSequenceError(
            f"帧号区间 [{first}, {last}] 只有 {span + 1} 个帧号，"
            f"无法为 {n} 帧指派严格递增的帧号"
        )
    if span > (n - 1) * max_step:
        raise NoFeasibleSequenceError(
            f"帧号跨度为 {span}，但 {n} 帧在相邻最多缺 {gap} 帧的限制下"
            f"最多只能跨越 {(n - 1) * max_step}，无法覆盖到末帧 {last}"
        )

    def match_cost(i: int, d: int) -> Decimal:
        hit = best_by_frame[i].get(first + d)
        if hit is not None:
            return CONFIDENCE_BASE - hit[0]
        return INFER_COST

    # ---- 后缀 DP：layers[i] = dp[i]，dict[offset -> 后缀最小代价] ----
    layers: list[dict[int, Decimal]] = [dict() for _ in range(n)]

    # 最后一帧必须指派 last（offset = span）
    layers[n - 1][span] = match_cost(n - 1, span)

    for i in range(n - 2, -1, -1):
        layer: dict[int, Decimal] = {}
        for d in range(0, span + 1):
            best_value: Decimal | None = None
            upper = min(span, d + max_step)
            for nd in range(d + 1, upper + 1):
                suffix = layers[i + 1].get(nd)
                if suffix is None:
                    continue
                value = Decimal(MISSING_FRAME_PENALTY * (nd - d - 1)) + suffix
                if best_value is None or value < best_value:
                    best_value = value
            if best_value is not None:
                layer[d] = match_cost(i, d) + best_value
        layers[i] = layer

    # 第一帧必须指派 first（offset = 0）
    if 0 not in layers[0]:
        # 理论上已被前置可行性检查覆盖，保留防御性报错。
        raise NoFeasibleSequenceError("无法形成从首帧到末帧的合法帧号序列")

    total_cost = layers[0][0]

    # ---- 回溯：在最优代价前提下每一步取最小 offset ----
    # nd 从小到大遍历且只在严格更小时替换，同分自然保留最小值；
    # 后缀最优与历史无关，因此贪心得到全局字典序最小的最优序列。
    offsets: list[int] = [0]
    for i in range(n - 1):
        d = offsets[-1]
        chosen: int | None = None
        chosen_value: Decimal | None = None
        upper = min(span, d + max_step)
        for nd in range(d + 1, upper + 1):
            suffix = layers[i + 1].get(nd)
            if suffix is None:
                continue
            value = Decimal(MISSING_FRAME_PENALTY * (nd - d - 1)) + suffix
            if chosen_value is None or value < chosen_value:
                chosen_value = value
                chosen = nd
        if chosen is None:  # 防御性检查
            raise NoFeasibleSequenceError(
                f"回溯到第 {i + 1} 帧时找不到合法后继帧号"
            )
        offsets.append(chosen)

    assigned_numbers = [first + d for d in offsets]
    assigned_set = set(assigned_numbers)

    # ---- 组装逐帧结果与代价明细 ----
    result_frames: list[dict[str, Any]] = []
    sum_match_cost = Decimal(0)
    sum_missing_penalty = Decimal(0)
    total_discarded = 0

    for i, (frame_id, candidates) in enumerate(parsed):
        d = offsets[i]
        number = first + d
        hit = best_by_frame[i].get(number)
        matched_index = hit[1] if hit is not None else None

        if hit is not None:
            frame_cost = CONFIDENCE_BASE - hit[0]
            source = "candidate"
        else:
            frame_cost = INFER_COST
            source = "inferred"
        sum_match_cost += frame_cost

        if i + 1 < n:
            missing_after = offsets[i + 1] - d - 1
        else:
            missing_after = 0
        gap_penalty = MISSING_FRAME_PENALTY * missing_after
        sum_missing_penalty += gap_penalty

        discarded: list[dict[str, Any]] = []
        for cand in candidates:
            idx = cand["index"]
            cand_number = cand["frame_number"]
            if idx == matched_index:
                continue  # 被采用的候选
            # 说明舍弃原因
            winner = best_by_frame[i].get(cand_number)
            if winner is not None and winner[1] != idx:
                reason = "duplicate_frame_number"  # 同帧号仅保留置信分最高者
            elif cand_number < first or cand_number > last:
                reason = "out_of_range"            # 超出固定首末帧号范围
            else:
                reason = "not_selected"            # 误识别 / 未被最优方案采用
            discarded.append(
                {
                    "candidate_index": idx,
                    "frame_number": cand_number,
                    "confidence": _json_number(cand["confidence"]),
                    "reason": reason,
                }
            )

        discarded.sort(key=lambda item: item["candidate_index"])
        total_discarded += len(discarded)

        result_frames.append(
            {
                "position": i + 1,
                "id": frame_id,
                "assigned_frame_number": number,
                "source": source,
                "matched_candidate_index": matched_index,
                "assigned_cost": _json_number(frame_cost),
                "missing_after": missing_after,
                "missing_penalty": gap_penalty,
                "discarded_candidates": discarded,
            }
        )

    # [first, last] 内未指派给任何扫描帧的帧号即为缺失帧（有序）
    missing_frame_numbers = [
        num for num in range(first, last + 1) if num not in assigned_set
    ]

    computed_total = sum_match_cost + sum_missing_penalty
    assert computed_total == total_cost, "代价明细与 DP 总代价不一致"
    assert len(missing_frame_numbers) == span - (n - 1), "缺失帧计数不一致"

    return {
        "first": first,
        "last": last,
        "max_missing_between": gap,
        "frame_count": n,
        "assigned_frame_numbers": assigned_numbers,
        "total_cost": _json_number(total_cost),
        "candidate_cost_total": _json_number(sum_match_cost),
        "missing_penalty_total": _json_number(sum_missing_penalty),
        "missing_frame_numbers": missing_frame_numbers,
        "missing_frame_count": len(missing_frame_numbers),
        "discarded_candidate_count": total_discarded,
        "frames": result_frames,
    }
