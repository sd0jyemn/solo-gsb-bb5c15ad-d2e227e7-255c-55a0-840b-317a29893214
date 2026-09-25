"""胶片数字化帧号复核：为扫描帧指派严格递增帧号的动态规划求解器。

规则
----
* 首帧（扫描顺序第 1 帧）固定指派 ``first_frame_no``，
  末帧（扫描顺序最后一帧）固定指派 ``last_frame_no``。
* 相邻两帧的帧号严格递增，且两帧之间最多缺失 ``max_missing`` 帧，
  即相邻指派帧号之差 ``<= max_missing + 1``。
* 每帧可从若干 OCR 候选帧号中选择一个，也可全部舍弃后推断一个帧号。
* 候选代价 = ``100 - 置信分``；推断代价 = ``100``；
  每缺失一帧额外加 ``30``。取总代价最小的方案。
* 总代价相同时，取帧号序列字典序最小的方案。
"""

from __future__ import annotations

from dataclasses import dataclass

CANDIDATE_BASE_COST = 100.0
INFER_COST = 100.0
MISSING_FRAME_COST = 30.0


class NoValidSequenceError(ValueError):
    """无法形成满足全部约束的严格递增帧号序列。"""


@dataclass(frozen=True)
class Candidate:
    """单个 OCR 候选帧号。"""

    frame_no: int
    confidence: float
    index: int  # 在该帧 candidates 数组中的原始下标，用于回指与舍弃报告


@dataclass(frozen=True)
class FrameAssignment:
    """单帧的最终指派结果。"""

    frame_index: int
    frame_id: str
    frame_no: int
    source: str  # "candidate" 表示采用 OCR 候选，"inferred" 表示推断
    confidence: float | None
    cost: float
    candidate_index: int | None


@dataclass(frozen=True)
class DiscardedCandidate:
    """被舍弃的 OCR 候选。"""

    frame_index: int
    frame_id: str
    candidate_index: int
    frame_no: int
    confidence: float
    reason: str  # duplicate_frame_no | out_of_range | not_selected


@dataclass(frozen=True)
class ReviewResult:
    """完整复核结果。"""

    assignments: list[FrameAssignment]
    discarded_candidates: list[DiscardedCandidate]
    missing_frame_numbers: list[int]
    total_cost: float
    candidate_cost_total: float
    inferred_cost_total: float
    gap_penalty_total: float


@dataclass
class _State:
    """DP 中“第 i 帧取某帧号”的状态。

    ``prev`` 是上一层状态按字典序排好后的序号（rank），用于回溯。
    """

    value: int
    total: float
    prev: int
    candidate: Candidate | None


def solve(
    frame_ids: list[str],
    candidates_per_frame: list[list[Candidate]],
    first_frame_no: int,
    last_frame_no: int,
    max_missing: int,
) -> ReviewResult:
    """执行动态规划求解。

    :raises NoValidSequenceError: 不存在满足首末帧号与缺帧约束的合法序列。
    """
    n = len(frame_ids)
    if n == 0:
        raise NoValidSequenceError("至少需要提供 1 帧。")
    if n == 1:
        if first_frame_no != last_frame_no:
            raise NoValidSequenceError(
                f"只有 1 帧时首末帧号必须相同：收到 {first_frame_no} 与 {last_frame_no}。"
            )
    elif first_frame_no >= last_frame_no:
        raise NoValidSequenceError(
            f"首帧号 {first_frame_no} 必须严格小于末帧号 {last_frame_no}。"
        )

    # ---- 整体跨度可行性 ---------------------------------------------------
    # 严格递增整数：末帧号至少为 first + n - 1；
    # 每步最多跳 max_missing + 1：末帧号至多为 first + (n-1)*(max_missing+1)。
    min_last = first_frame_no + (n - 1)
    max_last = first_frame_no + (n - 1) * (max_missing + 1)
    if last_frame_no < min_last:
        raise NoValidSequenceError(
            f"帧数过多：{n} 个严格递增帧号在 {first_frame_no}..{last_frame_no} "
            f"内排不下（末帧号至少为 {min_last}）。"
        )
    if last_frame_no > max_last:
        raise NoValidSequenceError(
            f"缺帧超限：{n} 帧从 {first_frame_no} 到 {last_frame_no}，"
            f"相邻最多缺 {max_missing} 帧时末帧号至多为 {max_last}。"
        )

    # 每帧 i 在任意合法完整序列中可能取到的帧号闭区间 [lo_i, hi_i]：
    #   从首帧正向最多走 i*(max_missing+1)，至少走 i 步；
    #   从末帧反向同理（至少留 n-1-i 步）。
    spans: list[tuple[int, int]] = []
    for i in range(n):
        remaining = n - 1 - i
        lo = max(
            first_frame_no + i,
            last_frame_no - remaining * (max_missing + 1),
        )
        hi = min(
            first_frame_no + i * (max_missing + 1),
            last_frame_no - remaining,
        )
        spans.append((lo, hi))

    # ---- 候选预处理：剔除越界候选，同帧同帧号只保留置信分最高者 -----------
    discarded: list[DiscardedCandidate] = []
    kept: list[dict[int, Candidate]] = []
    for i, cands in enumerate(candidates_per_frame):
        lo, hi = spans[i]
        best: dict[int, Candidate] = {}
        for cand in cands:
            if cand.frame_no < lo or cand.frame_no > hi:
                discarded.append(
                    DiscardedCandidate(
                        frame_index=i,
                        frame_id=frame_ids[i],
                        candidate_index=cand.index,
                        frame_no=cand.frame_no,
                        confidence=cand.confidence,
                        reason="out_of_range",
                    )
                )
                continue
            old = best.get(cand.frame_no)
            # 置信分相同则保留输入顺序靠前的候选（确定性取舍）。
            if old is None or cand.confidence > old.confidence:
                if old is not None:
                    discarded.append(
                        DiscardedCandidate(
                            frame_index=i,
                            frame_id=frame_ids[i],
                            candidate_index=old.index,
                            frame_no=old.frame_no,
                            confidence=old.confidence,
                            reason="duplicate_frame_no",
                        )
                    )
                best[cand.frame_no] = cand
            else:
                discarded.append(
                    DiscardedCandidate(
                        frame_index=i,
                        frame_id=frame_ids[i],
                        candidate_index=cand.index,
                        frame_no=cand.frame_no,
                        confidence=cand.confidence,
                        reason="duplicate_frame_no",
                    )
                )
        kept.append(best)

    # entries[i]: 帧 i 取各帧号时的“本帧指派代价”与候选来源。
    # 某帧号没有候选时按推断处理（代价 100）；候选代价 100-置信分 <= 100，
    # 因此同帧号若存在候选，候选始终不劣于推断。
    entries: list[dict[int, tuple[float, Candidate | None]]] = [
        {value: (CANDIDATE_BASE_COST - cand.confidence, cand) for value, cand in kept[i].items()}
        for i in range(n)
    ]

    # ---- 动态规划 ---------------------------------------------------------
    # 每层状态按“到该帧为止帧号序列的字典序”从小到大排列，序号即 rank。
    # 同帧号的多个前驱取总代价最小者；总代价相同取 rank 最小者：
    # 两前驱到达同一帧号后剩余后缀完全一致，rank 小等价于整条序列字典序小。
    def make_entry(i: int, value: int) -> tuple[float, Candidate | None]:
        return entries[i].get(value, (INFER_COST, None))

    first_cost, first_cand = make_entry(0, first_frame_no)
    layers: list[list[_State]] = [
        [_State(value=first_frame_no, total=first_cost, prev=-1, candidate=first_cand)]
    ]

    for i in range(1, n):
        lo, hi = spans[i]
        prev_states = layers[i - 1]
        best_by_value: dict[int, _State] = {}

        for rank, st in enumerate(prev_states):
            low = max(lo, st.value + 1)
            high = min(hi, st.value + max_missing + 1)
            for value in range(low, high + 1):
                assign_cost, cand = make_entry(i, value)
                missing = value - st.value - 1
                total = st.total + assign_cost + missing * MISSING_FRAME_COST
                old = best_by_value.get(value)
                if (
                    old is None
                    or total < old.total
                    or (total == old.total and rank < old.prev)
                ):
                    best_by_value[value] = _State(
                        value=value, total=total, prev=rank, candidate=cand
                    )

        if i == n - 1:
            # 末帧必须取固定末帧号。
            final = best_by_value.get(last_frame_no)
            if final is None:  # 理论上前面的跨度检查已覆盖，这里兜底。
                raise NoValidSequenceError(
                    f"末帧无法指派为 {last_frame_no}，不存在合法的严格递增序列。"
                )
            layers.append([final])
        else:
            if not best_by_value:
                raise NoValidSequenceError(
                    f"第 {i + 1} 帧（ID={frame_ids[i]}）无法指派任何满足约束的帧号，"
                    "不存在合法的严格递增序列。"
                )
            # rank 顺序：先按前驱 rank，再按本帧帧号，恰好对应前缀序列字典序。
            layers.append(
                [
                    best_by_value[value]
                    for value in sorted(
                        best_by_value,
                        key=lambda v: (best_by_value[v].prev, v),
                    )
                ]
            )

    # ---- 回溯 -------------------------------------------------------------
    chain: list[_State] = [layers[n - 1][0]]
    for i in range(n - 1, 0, -1):
        chain.append(layers[i - 1][chain[-1].prev])
    chain.reverse()

    assignments: list[FrameAssignment] = []
    used_candidates: set[tuple[int, int]] = set()
    candidate_cost_total = 0.0
    inferred_cost_total = 0.0
    gap_penalty_total = 0.0

    for i, st in enumerate(chain):
        if i > 0:
            gap_penalty_total += (st.value - chain[i - 1].value - 1) * MISSING_FRAME_COST
        if st.candidate is not None:
            cand = st.candidate
            cost = CANDIDATE_BASE_COST - cand.confidence
            candidate_cost_total += cost
            used_candidates.add((i, cand.index))
            assignments.append(
                FrameAssignment(
                    frame_index=i,
                    frame_id=frame_ids[i],
                    frame_no=st.value,
                    source="candidate",
                    confidence=cand.confidence,
                    cost=cost,
                    candidate_index=cand.index,
                )
            )
        else:
            inferred_cost_total += INFER_COST
            assignments.append(
                FrameAssignment(
                    frame_index=i,
                    frame_id=frame_ids[i],
                    frame_no=st.value,
                    source="inferred",
                    confidence=None,
                    cost=INFER_COST,
                    candidate_index=None,
                )
            )

    # 未被选中的保留候选计入舍弃列表。
    for i, best in enumerate(kept):
        for cand in best.values():
            if (i, cand.index) not in used_candidates:
                discarded.append(
                    DiscardedCandidate(
                        frame_index=i,
                        frame_id=frame_ids[i],
                        candidate_index=cand.index,
                        frame_no=cand.frame_no,
                        confidence=cand.confidence,
                        reason="not_selected",
                    )
                )
    discarded.sort(key=lambda d: (d.frame_index, d.candidate_index))

    assigned_values = {st.value for st in chain}
    missing_frame_numbers = [
        value
        for value in range(first_frame_no + 1, last_frame_no)
        if value not in assigned_values
    ]

    total_cost = chain[-1].total
    expected = candidate_cost_total + inferred_cost_total + gap_penalty_total
    if abs(total_cost - expected) > 1e-9:  # 纯防护：两种统计应恒等。
        raise RuntimeError(f"代价统计不一致：DP={total_cost}，汇总={expected}")

    return ReviewResult(
        assignments=assignments,
        discarded_candidates=discarded,
        missing_frame_numbers=missing_frame_numbers,
        total_cost=total_cost,
        candidate_cost_total=candidate_cost_total,
        inferred_cost_total=inferred_cost_total,
        gap_penalty_total=gap_penalty_total,
    )
