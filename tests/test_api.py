"""暴力枚举对拍 + API 集成测试。"""

from __future__ import annotations

import itertools

from fastapi.testclient import TestClient

from app.main import app
from app.solver import CANDIDATE_BASE_COST, MISSING_FRAME_COST, Candidate, solve


def brute_force(candidates_per_frame, first, last, max_missing):
    """枚举每帧帧号（候选 ∪ 范围内全部整数），返回 (序列, 总代价) 或 None。"""
    n = len(candidates_per_frame)
    options = []
    for i in range(n):
        lo = max(first + i, last - (n - 1 - i) * (max_missing + 1))
        hi = min(first + i * (max_missing + 1), last - (n - 1 - i))
        values = {c.frame_no for c in candidates_per_frame[i] if lo <= c.frame_no <= hi}
        values.update(range(lo, hi + 1))
        options.append(sorted(values))

    best = None
    for seq in itertools.product(*options):
        if seq[0] != first or seq[-1] != last:
            continue
        if any(b <= a for a, b in zip(seq, seq[1:])):
            continue
        if any(b - a > max_missing + 1 for a, b in zip(seq, seq[1:])):
            continue
        total = 0.0
        for value, cands in zip(seq, candidates_per_frame):
            costs = [CANDIDATE_BASE_COST - c.confidence for c in cands if c.frame_no == value]
            total += min(costs) if costs else 100.0
        total += (last - first + 1 - n) * MISSING_FRAME_COST
        key = (total, seq)
        if best is None or key < best:
            best = key
    return best  # (total, seq)


def make_candidates(groups):
    return [
        [Candidate(frame_no=no, confidence=float(conf), index=idx) for idx, (no, conf) in enumerate(g)]
        for g in groups
    ]


def test_brute_force_fuzz():
    import random

    rng = random.Random(42)
    for _ in range(400):
        n = rng.randint(2, 5)
        first = rng.randint(0, 5)
        max_missing = rng.randint(0, 3)
        span = (n - 1) + rng.randint(0, (n - 1) * max_missing)
        last = first + span
        groups = []
        for i in range(n):
            cands = []
            for _ in range(rng.randint(0, 3)):
                no = rng.randint(first, last)
                conf = rng.randint(0, 100)
                cands.append((no, conf))
            groups.append(cands)

        result = solve(
            frame_ids=[f"f{i}" for i in range(n)],
            candidates_per_frame=make_candidates(groups),
            first_frame_no=first,
            last_frame_no=last,
            max_missing=max_missing,
        )
        expected = brute_force(make_candidates(groups), first, last, max_missing)
        assert expected is not None
        exp_total, exp_seq = expected
        assert [a.frame_no for a in result.assignments] == list(exp_seq)
        assert abs(result.total_cost - exp_total) < 1e-9


def test_api_review_success():
    client = TestClient(app)
    resp = client.post(
        "/review",
        json={
            "frames": [
                {"frame_id": "scan-0001", "candidates": [{"frame_no": 1, "confidence": 98}]},
                {
                    "frame_id": "scan-0002",
                    "candidates": [
                        {"frame_no": 2, "confidence": 12},
                        {"frame_no": 3, "confidence": 91},
                    ],
                },
                {"frame_id": "scan-0003", "candidates": [{"frame_no": 4, "confidence": 97}]},
            ],
            "first_frame_no": 1,
            "last_frame_no": 4,
            "max_missing": 1,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert [a["frame_no"] for a in data["assignments"]] == [1, 3, 4]
    assert data["assignments"][1]["source"] == "candidate"
    assert data["total_cost"] == 2 + 9 + 3 + 30
    assert data["missing_frame_numbers"] == [2]
    assert data["cost_summary"]["missing_frame_count"] == 1
    discarded = {(d["frame_index"], d["frame_no"]) for d in data["discarded_candidates"]}
    assert (1, 2) in discarded


def test_api_no_valid_sequence_returns_400():
    client = TestClient(app)
    resp = client.post(
        "/review",
        json={
            "frames": [
                {"frame_id": "a", "candidates": []},
                {"frame_id": "b", "candidates": []},
            ],
            "first_frame_no": 1,
            "last_frame_no": 50,
            "max_missing": 2,
        },
    )
    assert resp.status_code == 400
    assert "缺帧超限" in resp.json()["detail"]


def test_api_validation_errors():
    client = TestClient(app)
    # 置信分越界
    resp = client.post(
        "/review",
        json={
            "frames": [
                {"frame_id": "a", "candidates": [{"frame_no": 1, "confidence": 120}]},
                {"frame_id": "b", "candidates": []},
            ],
            "first_frame_no": 1,
            "last_frame_no": 2,
            "max_missing": 0,
        },
    )
    assert resp.status_code == 422

    # max_missing 越界
    resp = client.post(
        "/review",
        json={
            "frames": [
                {"frame_id": "a", "candidates": []},
                {"frame_id": "b", "candidates": []},
            ],
            "first_frame_no": 1,
            "last_frame_no": 2,
            "max_missing": 11,
        },
    )
    assert resp.status_code == 422


def test_api_health_and_docs():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
