"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import ErrorResponse, ReviewRequest, ReviewResponse
from app.solver import InvalidRangeError, NoFeasibleSequenceError, solve_review

app = FastAPI(
    title="胶片数字化帧号复核 API",
    description=(
        "对扫描顺序的 2～100 帧 OCR 帧号进行复核：用动态规划指派严格递增的"
        "帧号，舍弃误识别候选并推断未识别帧，输出缺失帧号与代价明细。"
    ),
    version="1.0.0",
)


@app.exception_handler(InvalidRangeError)
async def invalid_range_handler(_request: Request, exc: InvalidRangeError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": exc.code, "message": exc.message},
    )


@app.exception_handler(NoFeasibleSequenceError)
async def no_feasible_handler(
    _request: Request, exc: NoFeasibleSequenceError
) -> JSONResponse:
    # 输入本身合法，但约束下不存在合法序列 -> 422 语义校验失败
    return JSONResponse(
        status_code=422,
        content={"error": exc.code, "message": exc.message},
    )


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/frame-reviews",
    response_model=ReviewResponse,
    tags=["review"],
    summary="复核扫描帧的帧号指派",
    responses={422: {"model": ErrorResponse, "description": "参数非法或无合法序列"}},
)
async def review_frames(request: ReviewRequest) -> ReviewResponse:
    result = solve_review(request.model_dump())
    return ReviewResponse.model_validate(result)
