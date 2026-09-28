#!/usr/bin/env python3
"""
주간 보고서 생성 파이프라인 (LangGraph).

수집 → 필터 → 분석 → 집계 → 출력을 노드/엣지 그래프로 구성한다.
- analyze 노드는 LLM/임베딩이 필요한 단계라, 활동이 0건이면 건너뛰고
  집계로 바로 진행하는 조건 분기를 그래프 엣지로 표현
- 각 노드는 ReportGenerator의 단계 함수를 호출 — 순차 경로와 로직 공유
- langgraph 미설치 환경에서는 이 모듈을 import하지 않고 순차 경로로 폴백
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from database import ActivityDatabase


class ReportState(TypedDict, total=False):
    week_start: str
    week_end: str
    formats: tuple
    activities: list
    extras: dict
    weekly_data: dict
    file_paths: dict
    errors: list


class WeeklyReportPipeline:
    """주간 보고서 생성 그래프. ReportGenerator의 단계 함수를 노드로 연결."""

    def __init__(self, generator, output_dir="reports"):
        self.gen = generator
        self.output_dir = output_dir
        self.app = self._build()

    def _build(self):
        graph = StateGraph(ReportState)
        graph.add_node("collect", self._collect)
        graph.add_node("filter", self._filter)
        graph.add_node("analyze", self._analyze)
        graph.add_node("aggregate", self._aggregate)
        graph.add_node("output", self._output)

        graph.add_edge(START, "collect")
        graph.add_edge("collect", "filter")
        # 활동이 없으면 LLM 분석은 건너뛰고 바로 집계로 (빈 보고서 생성)
        graph.add_conditional_edges(
            "filter",
            lambda state: "analyze" if state.get("activities") else "aggregate",
        )
        graph.add_edge("analyze", "aggregate")
        graph.add_edge("aggregate", "output")
        graph.add_edge("output", END)
        return graph.compile()

    # ---------- 노드 ----------

    def _collect(self, state: ReportState) -> dict[str, Any]:
        week_start, week_end = self.gen._resolve_week_range(
            state.get("week_start"), state.get("week_end")
        )
        return {"week_start": week_start, "week_end": week_end}

    def _filter(self, state: ReportState) -> dict[str, Any]:
        activities = self.gen.fetch_week_activities(
            state["week_start"], state["week_end"]
        )
        return {"activities": activities}

    def _analyze(self, state: ReportState) -> dict[str, Any]:
        extras = self.gen.analyze_week_activities(state["activities"])
        return {"extras": extras}

    def _aggregate(self, state: ReportState) -> dict[str, Any]:
        weekly_data = self.gen.compose_weekly_data(
            state["week_start"],
            state["week_end"],
            state.get("activities") or [],
            state.get("extras") or {},
        )
        return {"weekly_data": weekly_data}

    def _output(self, state: ReportState) -> dict[str, Any]:
        weekly_data = state["weekly_data"]
        file_paths = self.gen.save_report(
            weekly_data,
            formats=state.get("formats") or ("markdown", "word"),
            output_dir=self.output_dir,
        )
        with ActivityDatabase(self.gen.db_path) as db:
            db.save_weekly_summary(
                weekly_data["week_start"], weekly_data["week_end"], weekly_data
            )
        return {"file_paths": file_paths}

    # ---------- 실행 ----------

    def run(self, week_start=None, week_end=None, formats=("markdown", "word")):
        """그래프 실행 → {"weekly_data":..., "file_paths":...}"""
        initial: ReportState = {"errors": [], "formats": formats}
        if week_start:
            initial["week_start"] = week_start
        if week_end:
            initial["week_end"] = week_end
        result = self.app.invoke(initial)
        return {
            "weekly_data": result.get("weekly_data"),
            "file_paths": result.get("file_paths"),
        }
