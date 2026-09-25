"""solver.solve 的单元测试。"""

from __future__ import annotations

import pytest

from app.solver import Candidate, NoValidSequenceError, solve


def make_candidates(groups: list[list[tuple[int, float]]]) -> list[list[Candidate]]:
    return [
        [Candidate(frame_no=no, confidence=conf, index=idx) for idx, (no, conf) in enumerate(g)]
        for g in groups
    ]


def sequence_of(result):
    return [a.frame_no for a in result.assignments]


def test_basic_candidate_and_gap_inference():
    # 3 帧：首帧固定 1，末帧固定 5；帧0候选1，帧2候选5，帧1无候选。
    # 总缺帧数恒为 (5-1+1)-3=2，缺帧惩罚恒为 60；推断代价恒为 100。
    # 因此帧1 取 2/3/4 的总代价相同，按字典序取最小值 2。
    result = solve(
        frame_ids=["f0", "f1", "f2"],
        candidates_per_frame=make_candidates([[(1, 90)], [], [(5, 95)]]),
        first_frame_no=1,
        last_frame_no=5,
        max_missing=3,
    )
    assert sequence_of(result) == [1, 2, 5]
    assert [a.source for a in result.assignments] == ["candidate", "inferred", "candidate"]
    assert result.total_cost == pytest.approx(10 + 100 + 5 + 60)
    assert result.missing_frame_numbers == [3, 4]
    assert result.gap_penalty_total == 60


def test_misread_candidate_discarded_by_inference():
    # 帧1 的候选 9 与固定序列 1,2,3 冲突（9 越界），应舍弃并推断 2。
    result = solve(
        frame_ids=["f0", "f1", "f2"],
        candidates_per_frame=make_candidates([[(1, 99)], [(9, 80)], [(3, 99)]]),
        first_frame_no=1,
        last_frame_no=3,
        max_missing=1,
    )
    assert sequence_of(result) == [1, 2, 3]
    assert result.assignments[1].source == "inferred"
    discarded = {(d.frame_index, d.frame_no, d.reason) for d in result.discarded_candidates}
    assert (1, 9, "out_of_range") in discarded
    assert result.total_cost == pytest.approx(1 + 100 + 1)


def test_lex_min_on_equal_total_cost():
    # 帧1 候选 2 和 3：代价相同（置信分相同），缺帧惩罚都为 0。
    # 序列 [1,2,4] 与 [1,3,4] 同分，取字典序小的 [1,2,4]。
    result = solve(
        frame_ids=["f0", "f1", "f2"],
        candidates_per_frame=make_candidates([[(1, 90)], [(2, 50), (3, 50)], [(4, 90)]]),
        first_frame_no=1,
        last_frame_no=4,
        max_missing=2,
    )
    assert sequence_of(result) == [1, 2, 4]
    not_selected = [d for d in result.discarded_candidates if d.reason == "not_selected"]
    assert len(not_selected) == 1
    assert not_selected[0].frame_no == 3


def test_lex_min_branch_merges_later():
    # 4 帧 1..5，帧1/帧2 可在 2,3,4 中组合，max_missing=1 => 相邻差<=2。
    # 帧1 取 2：帧2 只能 3 或 4；帧1 取 3：帧2 只能 4。
    # 所有候选置信分相同 => 三种完整序列总代价相同，取字典序最小 [1,2,3,5]。
    result = solve(
        frame_ids=["a", "b", "c", "d"],
        candidates_per_frame=make_candidates(
            [
                [(1, 90)],
                [(2, 90), (3, 90), (4, 90)],
                [(2, 90), (3, 90), (4, 90)],
                [(5, 90)],
            ]
        ),
        first_frame_no=1,
        last_frame_no=5,
        max_missing=1,
    )
    assert sequence_of(result) == [1, 2, 3, 5]
    assert result.missing_frame_numbers == [4]
    assert result.gap_penalty_total == 30


def test_higher_confidence_preferred_even_if_lex_greater():
    # 帧1：候选 3 置信分 90（代价10），候选 2 置信分 10（代价90）。
    # 取 3 的总代价更低，即使序列字典序更大也应取 3。
    result = solve(
        frame_ids=["a", "b", "c"],
        candidates_per_frame=make_candidates([[(1, 90)], [(2, 10), (3, 90)], [(4, 90)]]),
        first_frame_no=1,
        last_frame_no=4,
        max_missing=2,
    )
    assert sequence_of(result) == [1, 3, 4]
    assert result.total_cost == pytest.approx(10 + 10 + 10 + 30)
    assert result.missing_frame_numbers == [2]


def test_duplicate_frame_no_keeps_highest_confidence():
    # 同帧两个相同帧号 2：保留置信分高者，另一个记 duplicate_frame_no。
    cands = [
        [Candidate(1, 90, 0)],
        [Candidate(2, 80, 0), Candidate(2, 99, 1)],
        [Candidate(3, 90, 0)],
    ]
    result = solve(
        frame_ids=["a", "b", "c"],
        candidates_per_frame=cands,
        first_frame_no=1,
        last_frame_no=3,
        max_missing=1,
    )
    assert sequence_of(result) == [1, 2, 3]
    assert result.assignments[1].candidate_index == 1
    dup = [d for d in result.discarded_candidates if d.reason == "duplicate_frame_no"]
    assert len(dup) == 1
    assert dup[0].candidate_index == 0


def test_max_missing_zero_forces_consecutive():
    result = solve(
        frame_ids=["a", "b", "c"],
        candidates_per_frame=make_candidates([[(1, 90)], [], [(3, 90)]]),
        first_frame_no=1,
        last_frame_no=3,
        max_missing=0,
    )
    assert sequence_of(result) == [1, 2, 3]
    assert result.missing_frame_numbers == []
    assert result.gap_penalty_total == 0


def test_impossible_span_too_many_frames():
    with pytest.raises(NoValidSequenceError, match="排不下"):
        solve(
            frame_ids=["a", "b", "c"],
            candidates_per_frame=make_candidates([[], [], []]),
            first_frame_no=10,
            last_frame_no=11,
            max_missing=0,
        )


def test_impossible_span_too_large_gap():
    with pytest.raises(NoValidSequenceError, match="缺帧超限"):
        solve(
            frame_ids=["a", "b"],
            candidates_per_frame=make_candidates([[], []]),
            first_frame_no=1,
            last_frame_no=20,
            max_missing=2,
        )


def test_candidate_must_respect_first_last_fixed():
    # 首帧候选不是 5、末帧候选不是 8 时，仍按固定首末帧号指派。
    result = solve(
        frame_ids=["a", "b"],
        candidates_per_frame=make_candidates([[(2, 100)], [(9, 100)]]),
        first_frame_no=5,
        last_frame_no=8,
        max_missing=3,
    )
    assert sequence_of(result) == [5, 8]
    reasons = {d.reason for d in result.discarded_candidates}
    assert reasons == {"out_of_range"}


def test_single_value_no_gap():
    result = solve(
        frame_ids=["a", "b"],
        candidates_per_frame=make_candidates([[(10, 70)], [(11, 60)]]),
        first_frame_no=10,
        last_frame_no=11,
        max_missing=0,
    )
    assert sequence_of(result) == [10, 11]
    assert result.total_cost == pytest.approx(30 + 40)
    assert result.missing_frame_numbers == []


def test_no_candidates_all_inferred():
    result = solve(
        frame_ids=[f"f{i}" for i in range(4)],
        candidates_per_frame=[[] for _ in range(4)],
        first_frame_no=100,
        last_frame_no=109,
        max_missing=10,
    )
    # 4 帧、跨度 9，每步缺帧自由；全部推断代价固定 400，缺帧惩罚固定 30*6=180。
    assert len(result.assignments) == 4
    assert result.total_cost == 400 + 180
    assert result.missing_frame_numbers == [103, 104, 105, 106, 107, 108]
    # 同分取字典序最小 => 尽量靠前分布。
    assert sequence_of(result) == [100, 101, 102, 109]


def test_cost_components_consistent():
    result = solve(
        frame_ids=["a", "b", "c"],
        candidates_per_frame=make_candidates([[(1, 90)], [(2, 20)], [(4, 0)]]),
        first_frame_no=1,
        last_frame_no=4,
        max_missing=2,
    )
    assert sequence_of(result) == [1, 2, 4]
    # 候选代价：10 + 80 + 100；缺 1 帧（3）惩罚 30。
    assert result.candidate_cost_total == pytest.approx(190)
    assert result.inferred_cost_total == 0
    assert result.gap_penalty_total == 30
    assert result.total_cost == pytest.approx(220)
