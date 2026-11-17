"""Vendored SalesCRM dataclasses."""

from __future__ import annotations
from .base import EntityBase, generate_id, now_iso
from .metrics import Metrics, MetricValue, DeltaInfo
from .stage import Stage, StageState, StageOverride, EvidenceEntry, STAGES
from .event import Event
from .ranking import Ranking, RankedPerson, RankingChange, InsufficientData
