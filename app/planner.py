"""乐谱安全翻页分页的动态规划求解器。

规则
----
* 乐谱被切分为若干"系统"（谱表行），按给定顺序排布；
* 一页由若干连续系统组成，其高度之和不得超过页面可用高度；
* 只能在"边界休止"达到最低安全休止秒数的系统之间翻页
  （第一页起点、最后一页终点无需休止）。

目标（字典序，依次满足）
------------------------
1. 最大化最短翻页休止；
2. 最小化各页留白平方和 ``sum((H - 已用高度)^2)``；
3. 减少页数。

求解思路
--------
目标 1 是"瓶颈"目标：设所有翻页边界休止都不低于阈值 t，则只要存在
合规分页，就能得到最短休止 >= t 的方案。可行性随 t 单调，因此在
"达到最低安全休止的边界休止值"（离散、降序）上二分，找到仍可行的
最高阈值 t*；再在允许使用休止 >= t* 的边界这一限制下，用动态规划
最小化（留白平方和, 页数）——该指标对"页"可加，按起点保留唯一最优
后缀即可保证字典序最优。

无法分页时，返回首个无法容纳或无法安全断开的区间，供调用方定位问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# 浮点比较容差：高度累加误差、休止秒比较均使用
_EPS = 1e-9


@dataclass(frozen=True)
class Page:
    """一页的排布结果（系统下标为从 1 开始的闭区间）。"""

    start_system: int
    end_system: int
    used_height: float
    whitespace: float


@dataclass
class PlanResult:
    """分页结果。feasible 为 False 时各诊断字段给出首个不可行区间。"""

    feasible: bool
    pages: List[Page] = field(default_factory=list)
    min_turn_rest: Optional[float] = None
    whitespace_square_sum: Optional[float] = None
    page_count: Optional[int] = None
    reason: Optional[str] = None
    # 首个无法容纳 / 无法安全断开的区间（系统序号，从 1 开始，闭区间）
    interval_start: Optional[int] = None
    interval_end: Optional[int] = None
    interval_height: Optional[float] = None
    safe_boundaries_after_start: List[int] = field(default_factory=list)
    overflow_system: Optional[int] = None


def plan_pages(
    system_heights: List[float],
    boundary_rests: List[float],
    page_height: float,
    min_safe_rest: float,
) -> PlanResult:
    """按字典序目标计算完整分页。

    参数
    ----
    system_heights: 各谱面系统高度（顺序排列）。
    boundary_rests: 相邻系统之间的休止秒数，长度必须为 ``n-1``，
                    ``boundary_rests[i]`` 为系统 i 与 i+1 之间的休止。
    page_height: 页面可用高度（统一高度）。
    min_safe_rest: 最低安全休止秒数，仅达到该值的边界允许翻页。
    """
    n = len(system_heights)

    # 前缀和，O(1) 求区间高度
    prefix = [0.0] * (n + 1)
    for i, h in enumerate(system_heights):
        prefix[i + 1] = prefix[i] + h

    def range_height(lo: int, hi: int) -> float:
        """系统 [lo, hi) 的总高度。"""
        return prefix[hi] - prefix[lo]

    # 单个系统就超高：任何分页都无解，直接定位
    for i, h in enumerate(system_heights):
        if h > page_height + _EPS:
            return _infeasible(
                reason="system_too_tall",
                lo=0, hi=i,
                system_heights=system_heights,
                meets_safe=[r + _EPS >= min_safe_rest for r in boundary_rests],
                prefix=prefix,
                overflow_system=i,
            )

    # 达到最低安全休止的边界，按休止值降序去重（二分阈值的候选集）
    thresholds = sorted(
        {round(r, 9) for r in boundary_rests if r + _EPS >= min_safe_rest},
        reverse=True,
    )

    def feasible_at(threshold: float) -> bool:
        """贪心：从每页起点尽量多装，在装得下的范围内取最后一个
        休止 >= threshold 的边界切分。能否切分只取决于"有无可达切法"，
        取最晚边界是区间覆盖问题的标准贪心（交换论证）。"""
        lo = 0
        while lo < n:
            k = lo
            while k < n and range_height(lo, k + 1) <= page_height + _EPS:
                k += 1
            if k == n:
                return True  # 最后一页无需断开
            cut = -1
            for b in range(k - 1, lo - 1, -1):
                if boundary_rests[b] + _EPS >= threshold:
                    cut = b
                    break
            if cut == -1:
                return False
            lo = cut + 1
        return True  # pragma: no cover

    # 在"休止 >= threshold 的边界才可翻页"的限制下，最小化
    # （留白平方和, 页数），返回构造参数或 None
    def optimize(threshold: float) -> Optional[tuple]:
        @dataclass
        class State:
            ws_sq: float
            pages: int
            next_start: int

        states: List[Optional[State]] = [None] * (n + 1)
        states[n] = State(0.0, 0, n)

        for i in range(n - 1, -1, -1):
            best: Optional[State] = None
            for j in range(i + 1, n + 1):
                used = range_height(i, j)
                if used > page_height + _EPS:
                    break  # 再加系统只会更高
                if j < n and boundary_rests[j - 1] + _EPS < threshold:
                    continue
                tail = states[j]
                if tail is None:
                    continue
                ws = page_height - used
                cand_ws = ws * ws + tail.ws_sq
                cand_pages = 1 + tail.pages
                if best is None or (cand_ws, cand_pages) < (best.ws_sq, best.pages):
                    best = State(cand_ws, cand_pages, j)
            states[i] = best

        if states[0] is None:
            return None

        pages: List[Page] = []
        chosen_rests: List[float] = []
        i = 0
        while i < n:
            st = states[i]
            assert st is not None
            j = st.next_start
            used = range_height(i, j)
            pages.append(Page(
                start_system=i + 1,
                end_system=j,
                used_height=round(used, 9),
                whitespace=round(page_height - used, 9),
            ))
            if j < n:
                chosen_rests.append(boundary_rests[j - 1])
            i = j

        return (
            pages,
            round(states[0].ws_sq, 9),
            states[0].pages,
            round(min(chosen_rests), 9) if chosen_rests else None,
        )

    # 整体一页放得下时无需任何翻页边界；优化 DP 天然会选中它（留白最小），
    # 但阈值候选可能为空，故先处理无候选的情况。
    if not thresholds:
        if range_height(0, n) <= page_height + _EPS:
            opt = optimize(min_safe_rest)  # 无边界可用，只会产出整曲一页
        else:
            return _first_infeasible_interval(
                system_heights,
                [r + _EPS >= min_safe_rest for r in boundary_rests],
                page_height, prefix,
            )
    else:
        # 二分：feasible 在降序阈值上前缀为真
        lo_idx, hi_idx = 0, len(thresholds) - 1
        best_idx = -1
        while lo_idx <= hi_idx:
            mid = (lo_idx + hi_idx) // 2
            if feasible_at(thresholds[mid]):
                best_idx = mid
                hi_idx = mid - 1
            else:
                lo_idx = mid + 1

        if best_idx == -1:
            # 连最低安全休止阈值都无法完成分页
            return _first_infeasible_interval(
                system_heights,
                [r + _EPS >= min_safe_rest for r in boundary_rests],
                page_height, prefix,
            )
        opt = optimize(thresholds[best_idx])
        if opt is None:  # 理论上不会发生：feasible_at 已证实可行
            return _first_infeasible_interval(
                system_heights,
                [r + _EPS >= min_safe_rest for r in boundary_rests],
                page_height, prefix,
            )

    pages, ws_sq, page_count, min_rest = opt
    return PlanResult(
        feasible=True,
        pages=pages,
        min_turn_rest=min_rest,
        whitespace_square_sum=ws_sq,
        page_count=page_count,
    )


def _first_infeasible_interval(
    system_heights: List[float],
    meets_safe: List[bool],
    page_height: float,
    prefix: List[float],
) -> PlanResult:
    """贪心扫描，找出第一个既装不下、又没有达标边界可断开的区间。

    从每页起点 lo 出发不断纳入系统；遇到第一个超高系统 k：
      * 若系统 k 自身就高于页面 -> 无法容纳；
      * 否则在 lo..k-1 之间找最后一个达标边界切分。
        找到则从切分点继续，找不到则区间 [lo+1, k] 无法安全断开。
    """
    n = len(system_heights)

    def range_height(lo: int, hi: int) -> float:
        return prefix[hi] - prefix[lo]

    lo = 0
    while lo < n:
        k = lo
        while k < n and range_height(lo, k + 1) <= page_height + _EPS:
            k += 1

        if k == n:
            # 能装下却走到这里，只可能是前面某页起点不可达——不会发生，
            # 兜底按整曲无法安全断开处理。
            break

        if system_heights[k] > page_height + _EPS:
            return _infeasible(
                reason="system_too_tall",
                lo=lo, hi=k,
                system_heights=system_heights,
                meets_safe=meets_safe,
                prefix=prefix,
                overflow_system=k,
            )

        cut = -1
        for b in range(k - 1, lo - 1, -1):
            if meets_safe[b]:
                cut = b
                break
        if cut == -1:
            return _infeasible(
                reason="no_safe_boundary",
                lo=lo, hi=k - 1,
                system_heights=system_heights,
                meets_safe=meets_safe,
                prefix=prefix,
                overflow_system=k,
            )
        lo = cut + 1

    # k == n 的兜底：当前页能装完整段却无法作为最后一页（只可能因调用
    # 方在无解时调用），按整曲无法安全断开处理。
    return _infeasible(
        reason="no_safe_boundary",
        lo=0, hi=n - 1,
        system_heights=system_heights,
        meets_safe=meets_safe,
        prefix=prefix,
    )


def _infeasible(
    *,
    reason: str,
    lo: int,
    hi: int,
    system_heights: List[float],
    meets_safe: List[bool],
    prefix: List[float],
    overflow_system: Optional[int] = None,
) -> PlanResult:
    n = len(system_heights)

    def range_height(a: int, b: int) -> float:
        return prefix[b + 1] - prefix[a]

    # 区间内（起点之后）达到最低安全休止、理论可翻页的边界
    safe_boundaries = [
        b + 1  # 边界 b（系统 b 与 b+1 之间）展示为"系统 b+1 之后"
        for b in range(lo, min(hi, n - 1))
        if meets_safe[b]
    ]

    if reason == "system_too_tall":
        return PlanResult(
        feasible=False,
        reason=reason,
        interval_start=lo + 1,
        interval_end=hi + 1,
        interval_height=round(range_height(lo, hi), 9),
        safe_boundaries_after_start=safe_boundaries,
        overflow_system=(overflow_system + 1) if overflow_system is not None else None,
    )

    return PlanResult(
        feasible=False,
        reason=reason,
        interval_start=lo + 1,
        interval_end=hi + 1,
        interval_height=round(range_height(lo, hi), 9),
        safe_boundaries_after_start=safe_boundaries,
        overflow_system=(overflow_system + 1) if overflow_system is not None else None,
    )
