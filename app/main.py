"""乐谱安全翻页规划 API。

启动时自动建库（见 lifespan）；分页采用 app.planner 中的动态规划。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Query

from . import database as db
from .planner import plan_pages
from .schemas import (
    InfeasibleDetail,
    PageOut,
    PlanListResponse,
    PlanRequest,
    PlanResponse,
    PlanSummary,
)


def _infeasible_message(result) -> str:
    if result.reason == "system_too_tall":
        return (
            f"系统 {result.overflow_system} 高度超出页面可用高度，"
            f"任何页面都无法容纳（区间 {result.interval_start}-"
            f"{result.interval_end}，区间高度 {result.interval_height}）"
        )
    overflow = result.overflow_system or result.interval_end
    return (
        f"首个无法安全断开的区间为系统 {result.interval_start}-"
        f"{result.interval_end}（高度 {result.interval_height}）："
        f"继续纳入系统 {overflow} 将超高，且该区间内没有达到最低安全"
        f"休止的翻页边界"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 依赖及建库随启动完成
    db.init_db()
    yield


app = FastAPI(
    title="乐谱安全翻页规划 API",
    version="1.0.0",
    description=(
        "提交按顺序排列的谱面系统高度、边界休止秒数、页面可用高度与最低安全休止，"
        "由动态规划生成完整分页：页面不得超高，且只能在达标的边界休止处翻页；"
        "依次最大化最短翻页休止、最小化各页留白平方和、减少页数。"
    ),
    lifespan=lifespan,
)


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _serialize_plan(row: sqlite3.Row, page_rows: List[sqlite3.Row]) -> PlanResponse:
    infeasible = None
    if not row["feasible"] and row["infeasible_detail"]:
        detail = json.loads(row["infeasible_detail"])
        infeasible = InfeasibleDetail(**detail)

    pages = [
        PageOut(
            page_no=p["page_no"],
            start_system=p["start_system"],
            end_system=p["end_system"],
            used_height=p["used_height"],
            whitespace=p["whitespace"],
        )
        for p in page_rows
    ]

    return PlanResponse(
        id=row["id"],
        name=row["name"],
        feasible=bool(row["feasible"]),
        page_count=row["page_count"],
        min_turn_rest=row["min_turn_rest"],
        whitespace_square_sum=row["whitespace_square_sum"],
        pages=pages,
        infeasible=infeasible,
        created_at=row["created_at"],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/plans", response_model=PlanResponse, status_code=201)
def create_plan(req: PlanRequest, conn: sqlite3.Connection = Depends(get_conn)):
    n = len(req.system_heights)
    if len(req.boundary_rests) != n - 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"boundary_rests 长度必须为系统数 - 1（当前系统 {n} 个，"
                f"休止 {len(req.boundary_rests)} 个，应为 {n - 1} 个）"
            ),
        )

    result = plan_pages(
        system_heights=req.system_heights,
        boundary_rests=req.boundary_rests,
        page_height=req.page_height,
        min_safe_rest=req.min_safe_rest,
    )

    infeasible_detail = None
    if not result.feasible:
        infeasible_detail = {
            "reason": result.reason,
            "message": _infeasible_message(result),
            "interval_start": result.interval_start,
            "interval_end": result.interval_end,
            "interval_height": result.interval_height,
            "safe_boundaries_after_start": result.safe_boundaries_after_start,
            "overflow_system": result.overflow_system,
        }

    with conn:  # 单事务：完整方案或纯诊断一次落库，绝不保存半成品分页
        plan_id = db.insert_plan(
            conn,
            name=req.name,
            system_heights=req.system_heights,
            boundary_rests=req.boundary_rests,
            page_height=req.page_height,
            min_safe_rest=req.min_safe_rest,
            feasible=result.feasible,
            page_count=result.page_count,
            min_turn_rest=result.min_turn_rest,
            whitespace_square_sum=result.whitespace_square_sum,
            infeasible_detail=infeasible_detail,
            pages=result.pages,
        )

    row = db.get_plan(conn, plan_id)
    page_rows = db.get_pages(conn, plan_id) if result.feasible else []
    return _serialize_plan(row, page_rows)


@app.get("/plans", response_model=PlanListResponse)
def list_plans(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
):
    rows = db.list_plans(conn, limit, offset)
    items = [
        PlanSummary(
            id=r["id"],
            name=r["name"],
            feasible=bool(r["feasible"]),
            page_count=r["page_count"],
            min_turn_rest=r["min_turn_rest"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return PlanListResponse(items=items, total=db.count_plans(conn))


@app.get("/plans/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    row = db.get_plan(conn, plan_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"方案 {plan_id} 不存在")
    page_rows = db.get_pages(conn, plan_id)
    return _serialize_plan(row, page_rows)
