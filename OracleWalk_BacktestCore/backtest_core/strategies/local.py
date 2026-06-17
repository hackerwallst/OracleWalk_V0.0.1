from __future__ import annotations

from .cross_tendency import CrossTendencyStrategy
from .cross_tendency_v1 import CrossTendencyV1Strategy
from .fvg_imbalance import FairValueGapStrategy
from .mean_reversion_m1 import M1MeanReversionScalper
from .ml_rsi_zeiierman import MachineLearningRsiZeiiermanStrategy
from .parity_probes import (
    P1ClockFlip,
    P2DailyBreakout,
    P3DailyLimitFade,
    P4WeeklyTrailing,
    P5NBarAlternator,
)
from .registry import register_strategy_class


register_strategy_class(CrossTendencyStrategy, "cross_tendency", aliases=("crossTendency", "ema_cross_adx"))
register_strategy_class(CrossTendencyV1Strategy, "cross_tendency_v1", aliases=("crossTendency_v1",))
register_strategy_class(FairValueGapStrategy, "fvg", aliases=("fair_value_gap",))
register_strategy_class(M1MeanReversionScalper, "m1_mean_reversion", aliases=("mean_reversion_m1",))
register_strategy_class(MachineLearningRsiZeiiermanStrategy, "ml_rsi_zeiierman")
register_strategy_class(P1ClockFlip, "p1_clock_flip", aliases=("probe1", "clock_flip"))
register_strategy_class(P2DailyBreakout, "p2_daily_breakout", aliases=("probe2", "daily_breakout_stop"))
register_strategy_class(P3DailyLimitFade, "p3_daily_limit_fade", aliases=("probe3", "daily_limit_fade"))
register_strategy_class(P4WeeklyTrailing, "p4_weekly_trailing", aliases=("probe4", "weekly_trailing"))
register_strategy_class(P5NBarAlternator, "p5_nbar_alternator", aliases=("probe5", "nbar_alternator"))
