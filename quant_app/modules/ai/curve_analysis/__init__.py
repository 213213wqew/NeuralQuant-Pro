"""Curve-shape analysis tools for directional gate signals."""

from .curve_signal_gate import CurveGateConfig, CurveSignalGate, GateSignal, BranchSignal, PivotSummary
from .curve_service import CurveAnalysisService, curve_analysis_service
from .structure_judge import MultiTimeframeStructureJudge, StructureJudgeResult, multi_tf_structure_judge

__all__ = [
    "CurveGateConfig",
    "CurveSignalGate",
    "GateSignal",
    "BranchSignal",
    "PivotSummary",
    "CurveAnalysisService",
    "curve_analysis_service",
    "MultiTimeframeStructureJudge",
    "StructureJudgeResult",
    "multi_tf_structure_judge",
]
