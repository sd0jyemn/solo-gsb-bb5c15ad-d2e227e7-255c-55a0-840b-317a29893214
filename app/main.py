"""胶片数字化帧号复核 API。

启动（容器内）：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .models import (
    AssignmentOut,
    CostSummary,
    DiscardedCandidateOut,
    ReviewRequest,
    ReviewResponse,
)
from .solver import Candidate, NoValidSequenceError, solve

app = FastAPI(
    title="胶片数字化帧号复核 API",
    description=(
        "对扫描顺序的 2～100 帧进行 OCR 帧号复核：用动态规划为每帧指派"
        "严格递增的帧号，可舍弃误识别候选并推断未识别帧。"
    ),
    version="1.0.0",
)


@app.exception_handler(NoValidSequenceError)
async def no_valid_sequence_handler(_: Request, exc: NoValidSequenceError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "service": "film-frame-review",
        "docs": "/docs",
        "health": "/health",
        "review": "POST /review",
    }


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/review",
    response_model=ReviewResponse,
    tags=["review"],
    summary="复核帧号指派",
)
async def review(req: ReviewRequest) -> ReviewResponse:
    frame_ids = [f.frame_id for f in req.frames]
    candidates_per_frame = [
        [
            Candidate(frame_no=c.frame_no, confidence=c.confidence, index=idx)
            for idx, c in enumerate(f.candidates)
        ]
        for f in req.frames
    ]

    result = solve(
        frame_ids=frame_ids,
        candidates_per_frame=candidates_per_frame,
        first_frame_no=req.first_frame_no,
        last_frame_no=req.last_frame_no,
        max_missing=req.max_missing,
    )

    return ReviewResponse(
        assignments=[
            AssignmentOut(
                frame_index=a.frame_index,
                frame_id=a.frame_id,
                frame_no=a.frame_no,
                source=a.source,
                confidence=a.confidence,
                cost=a.cost,
                candidate_index=a.candidate_index,
            )
            for a in result.assignments
        ],
        discarded_candidates=[
            DiscardedCandidateOut(
                frame_index=d.frame_index,
                frame_id=d.frame_id,
                candidate_index=d.candidate_index,
                frame_no=d.frame_no,
                confidence=d.confidence,
                reason=d.reason,
            )
            for d in result.discarded_candidates
        ],
        missing_frame_numbers=result.missing_frame_numbers,
        total_cost=result.total_cost,
        cost_summary=CostSummary(
            candidate_cost_total=result.candidate_cost_total,
            inferred_cost_total=result.inferred_cost_total,
            gap_penalty_total=result.gap_penalty_total,
            inferred_frame_count=sum(1 for a in result.assignments if a.source == "inferred"),
            missing_frame_count=len(result.missing_frame_numbers),
        ),
    )
