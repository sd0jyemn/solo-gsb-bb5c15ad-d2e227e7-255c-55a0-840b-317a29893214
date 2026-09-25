"""请求/响应 Pydantic 模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CandidateIn(BaseModel):
    """单帧的一个 OCR 候选帧号。"""

    frame_no: int = Field(..., description="OCR 识别出的帧号")
    confidence: float = Field(
        ..., ge=0, le=100, description="置信分，范围 0～100"
    )


class FrameIn(BaseModel):
    """一帧扫描图像及其 OCR 候选。"""

    frame_id: str = Field(..., min_length=1, description="帧 ID")
    candidates: list[CandidateIn] = Field(
        default_factory=list, max_length=100, description="OCR 帧号候选，可为空"
    )


class ReviewRequest(BaseModel):
    """帧号复核请求。"""

    frames: list[FrameIn] = Field(
        ..., min_length=2, max_length=100, description="按扫描顺序排列的 2～100 帧"
    )
    first_frame_no: int = Field(..., description="固定的首帧帧号")
    last_frame_no: int = Field(..., description="固定的末帧帧号")
    max_missing: int = Field(
        ..., ge=0, le=10, description="相邻两帧之间最多允许缺失的帧数，0～10"
    )


class AssignmentOut(BaseModel):
    """单帧指派结果。"""

    frame_index: int = Field(..., description="帧在扫描顺序中的下标，从 0 开始")
    frame_id: str
    frame_no: int = Field(..., description="指派给该帧的帧号")
    source: Literal["candidate", "inferred"] = Field(
        ..., description="candidate=采用 OCR 候选；inferred=舍弃全部候选后推断"
    )
    confidence: float | None = Field(
        None, description="采用候选时的置信分；推断时为 null"
    )
    cost: float = Field(..., description="本帧指派代价（100-置信分 或 100）")
    candidate_index: int | None = Field(
        None, description="被采用候选在该帧 candidates 数组中的下标；推断时为 null"
    )


class DiscardedCandidateOut(BaseModel):
    """被舍弃的 OCR 候选。"""

    frame_index: int
    frame_id: str
    candidate_index: int = Field(
        ..., description="该候选在所属帧 candidates 数组中的下标"
    )
    frame_no: int
    confidence: float
    reason: Literal["duplicate_frame_no", "out_of_range", "not_selected"] = Field(
        ...,
        description=(
            "舍弃原因：duplicate_frame_no=同帧同帧号仅保留最高置信分候选；"
            "out_of_range=不可能出现在合法序列中；not_selected=最优方案未采用"
        ),
    )


class CostSummary(BaseModel):
    """代价明细。"""

    candidate_cost_total: float
    inferred_cost_total: float
    gap_penalty_total: float = Field(..., description="缺帧惩罚合计，每缺 1 帧 30")
    inferred_frame_count: int
    missing_frame_count: int


class ReviewResponse(BaseModel):
    """帧号复核响应。"""

    assignments: list[AssignmentOut] = Field(
        ..., description="逐帧指派结果，顺序与请求 frames 一致，帧号严格递增"
    )
    discarded_candidates: list[DiscardedCandidateOut] = Field(
        ..., description="被舍弃的 OCR 候选"
    )
    missing_frame_numbers: list[int] = Field(
        ..., description="首末帧之间未被任何扫描帧占有的帧号（缺失帧）"
    )
    total_cost: float
    cost_summary: CostSummary


class ErrorResponse(BaseModel):
    detail: str
