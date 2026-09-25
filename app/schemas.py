"""请求/响应数据模型（Pydantic v2）。"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

# 帧 ID 允许字符串或整数
FrameId = Union[str, int]


class CandidateIn(BaseModel):
    frame_number: int = Field(..., description="OCR 识别出的帧号")
    confidence: Union[int, float] = Field(
        ..., ge=0, le=100, description="OCR 置信分，0～100"
    )


class FrameIn(BaseModel):
    id: FrameId = Field(..., description="扫描帧的唯一标识")
    candidates: list[CandidateIn] = Field(
        default_factory=list, description="该帧的 OCR 候选，可为空"
    )


class ReviewRequest(BaseModel):
    first: int = Field(..., description="固定首帧号")
    last: int = Field(..., description="固定末帧号（必须严格大于 first）")
    max_missing_between: int = Field(
        ..., ge=0, le=10, description="相邻两帧之间最多允许缺帧的数量，0～10"
    )
    frames: list[FrameIn] = Field(
        ..., min_length=2, max_length=100, description="按扫描顺序排列的 2～100 帧"
    )


class DiscardedCandidateOut(BaseModel):
    candidate_index: int = Field(..., description="该候选在输入 candidates 中的下标")
    frame_number: int
    confidence: Union[int, float]
    reason: Literal["duplicate_frame_number", "out_of_range", "not_selected"]


class FrameAssignmentOut(BaseModel):
    position: int = Field(..., description="扫描顺序位置，从 1 开始")
    id: FrameId
    assigned_frame_number: int = Field(..., description="指派给该帧的严格递增帧号")
    source: Literal["candidate", "inferred"] = Field(
        ..., description="candidate=命中 OCR 候选；inferred=未命中、按序列推断"
    )
    matched_candidate_index: Union[int, None] = Field(
        ..., description="命中的候选下标；推断时为 null"
    )
    assigned_cost: Union[int, float] = Field(
        ..., description="该帧的指派代价（命中=100-置信分，推断=100）"
    )
    missing_after: int = Field(..., description="该帧与下一帧之间缺了多少帧")
    missing_penalty: int = Field(..., description="上述缺帧产生的代价（30/帧）")
    discarded_candidates: list[DiscardedCandidateOut]


class ReviewResponse(BaseModel):
    first: int
    last: int
    max_missing_between: int
    frame_count: int
    assigned_frame_numbers: list[int] = Field(
        ..., description="与输入 frames 等长、严格递增的指派帧号序列"
    )
    total_cost: Union[int, float]
    candidate_cost_total: Union[int, float]
    missing_penalty_total: Union[int, float]
    missing_frame_numbers: list[int] = Field(
        ..., description="[first, last] 内未指派给任何扫描帧的缺失帧号"
    )
    missing_frame_count: int
    discarded_candidate_count: int
    frames: list[FrameAssignmentOut]


class ErrorResponse(BaseModel):
    error: Literal["invalid_range", "no_feasible_sequence"]
    message: str
