"""请求 / 响应模型与输入校验。"""

from __future__ import annotations

import math
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class PlanRequest(BaseModel):
    """提交一条乐谱进行安全翻页分页。"""

    name: Optional[str] = Field(
        default=None, max_length=200, description="乐谱名称，仅用于展示"
    )
    system_heights: List[float] = Field(
        ...,
        min_length=1,
        description="按顺序排列的各谱面系统高度（与页面高度同单位）",
    )
    boundary_rests: List[float] = Field(
        ...,
        description="相邻系统之间的边界休止秒数，长度须为系统数 - 1",
    )
    page_height: float = Field(..., gt=0, description="页面可用高度（统一）")
    min_safe_rest: float = Field(
        ..., ge=0, description="允许翻页所需的最低安全休止秒数"
    )

    @field_validator("system_heights")
    @classmethod
    def _heights_positive_finite(cls, v: List[float]) -> List[float]:
        for idx, h in enumerate(v):
            if not math.isfinite(h):
                raise ValueError(f"第 {idx + 1} 个系统高度必须为有限数值")
            if h <= 0:
                raise ValueError(f"第 {idx + 1} 个系统高度必须大于 0")
        return v

    @field_validator("boundary_rests")
    @classmethod
    def _rests_non_negative_finite(cls, v: List[float]) -> List[float]:
        for idx, r in enumerate(v):
            if not math.isfinite(r):
                raise ValueError(f"第 {idx + 1} 个边界休止必须为有限数值")
            if r < 0:
                raise ValueError(f"第 {idx + 1} 个边界休止不能为负数")
        return v

    @field_validator("page_height", "min_safe_rest")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("必须为有限数值")
        return v


class PageOut(BaseModel):
    page_no: int
    start_system: int
    end_system: int
    used_height: float
    whitespace: float


class InfeasibleDetail(BaseModel):
    reason: str
    message: str
    interval_start: int
    interval_end: int
    interval_height: float
    safe_boundaries_after_start: List[int]
    overflow_system: Optional[int] = None


class PlanResponse(BaseModel):
    id: int
    name: Optional[str] = None
    feasible: bool
    page_count: Optional[int] = None
    min_turn_rest: Optional[float] = None
    whitespace_square_sum: Optional[float] = None
    pages: List[PageOut] = []
    infeasible: Optional[InfeasibleDetail] = None
    created_at: str


class PlanSummary(BaseModel):
    id: int
    name: Optional[str] = None
    feasible: bool
    page_count: Optional[int] = None
    min_turn_rest: Optional[float] = None
    created_at: str


class PlanListResponse(BaseModel):
    items: List[PlanSummary]
    total: int
