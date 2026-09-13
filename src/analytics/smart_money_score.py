"""Smart Money Score — composite quality score for wallets."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.database.models import Wallet, WalletMetrics

logger = logging.getLogger(__name__)

MIN_TRADES_LOW_CONFIDENCE = 10
MIN_TRADES_HIGH_CONFIDENCE = 50


@dataclass
class ScoreBreakdown:
    win_rate_score: float
    avg_roi_score: float
    consistency_score: float
    risk_management_score: float
    trade_frequency_score: float
    drawdown_score: float
    sample_size_score: float
    final_score: float
    confidence: float  # 0-1
    flags: list[str]

    def to_dict(self) -> dict:
        return {
            "win_rate": round(self.win_rate_score, 1),
            "average_roi": round(self.avg_roi_score, 1),
            "consistency": round(self.consistency_score, 1),
            "risk_management": round(self.risk_management_score, 1),
            "trade_frequency": round(self.trade_frequency_score, 1),
            "drawdown": round(self.drawdown_score, 1),
            "sample_size": round(self.sample_size_score, 1),
            "final": round(self.final_score, 1),
            "confidence": round(self.confidence, 2),
            "flags": self.flags,
        }


def compute_score(metrics: WalletMetrics, wallet: Optional[Wallet] = None) -> ScoreBreakdown:
    """Compute Smart Money Score from wallet metrics."""
    flags: list[str] = []

    # ---- Win Rate Score (0-100) ----
    wr = metrics.win_rate or 0.0
    win_rate_score = min(100, wr * 1.1)  # 90% WR → 99, 80% → 88, 50% → 55

    # ---- Average ROI Score (0-100) ----
    avg_roi = metrics.average_roi or 0.0
    if avg_roi >= 200:
        avg_roi_score = 100.0
    elif avg_roi >= 100:
        avg_roi_score = 85.0 + (avg_roi - 100) / 100 * 15
    elif avg_roi >= 50:
        avg_roi_score = 70.0 + (avg_roi - 50) / 50 * 15
    elif avg_roi >= 20:
        avg_roi_score = 50.0 + (avg_roi - 20) / 30 * 20
    elif avg_roi > 0:
        avg_roi_score = avg_roi / 20 * 50
    else:
        avg_roi_score = 0.0

    # ---- Consistency Score (0-100) — based on profit factor and median vs avg ----
    pf = metrics.profit_factor or 0.0
    if pf >= 5:
        consistency_score = 100.0
    elif pf >= 3:
        consistency_score = 85.0 + (pf - 3) / 2 * 15
    elif pf >= 2:
        consistency_score = 70.0 + (pf - 2) * 15
    elif pf >= 1:
        consistency_score = 40.0 + (pf - 1) * 30
    else:
        consistency_score = 0.0

    # Penalty if median ROI is much lower than average (single lucky trade)
    median_roi = metrics.median_roi or 0.0
    if avg_roi > 50 and median_roi < avg_roi * 0.3:
        flags.append("CONCENTRATED_PNL")
        consistency_score *= 0.7

    # ---- Risk Management Score (0-100) ----
    avg_loss = abs(metrics.average_loss_usd or 0.0)
    avg_profit = metrics.average_profit_usd or 0.0
    if avg_loss == 0:
        risk_mgmt_score = 90.0  # No losses recorded — possibly too few data points
    else:
        rr_ratio = avg_profit / avg_loss
        if rr_ratio >= 5:
            risk_mgmt_score = 100.0
        elif rr_ratio >= 3:
            risk_mgmt_score = 85.0 + (rr_ratio - 3) / 2 * 15
        elif rr_ratio >= 2:
            risk_mgmt_score = 70.0 + (rr_ratio - 2) * 15
        elif rr_ratio >= 1:
            risk_mgmt_score = 50.0 + (rr_ratio - 1) * 20
        else:
            risk_mgmt_score = rr_ratio * 50

    # ---- Trade Frequency Score (0-100) ----
    total_trades = metrics.total_trades or 0
    if total_trades >= 200:
        freq_score = 100.0
    elif total_trades >= 100:
        freq_score = 85.0 + (total_trades - 100) / 100 * 15
    elif total_trades >= 50:
        freq_score = 70.0 + (total_trades - 50) / 50 * 15
    elif total_trades >= 20:
        freq_score = 50.0 + (total_trades - 20) / 30 * 20
    elif total_trades >= 10:
        freq_score = 30.0 + (total_trades - 10) / 10 * 20
    else:
        freq_score = total_trades * 3.0

    # ---- Drawdown Score (0-100) ----
    dd = metrics.max_drawdown or 0.0
    if dd <= 5:
        drawdown_score = 100.0
    elif dd <= 15:
        drawdown_score = 90.0 - (dd - 5) * 2
    elif dd <= 30:
        drawdown_score = 70.0 - (dd - 15) * 2
    elif dd <= 50:
        drawdown_score = 40.0 - (dd - 30) * 1.5
    else:
        drawdown_score = max(0, 10 - (dd - 50) * 0.5)

    # ---- Sample Size Score (confidence multiplier) ----
    if total_trades >= MIN_TRADES_HIGH_CONFIDENCE:
        sample_score = 100.0
        confidence = 1.0
    elif total_trades >= MIN_TRADES_LOW_CONFIDENCE:
        frac = (total_trades - MIN_TRADES_LOW_CONFIDENCE) / (MIN_TRADES_HIGH_CONFIDENCE - MIN_TRADES_LOW_CONFIDENCE)
        sample_score = 50.0 + frac * 50
        confidence = 0.5 + frac * 0.5
    else:
        sample_score = total_trades * 5.0
        confidence = total_trades / MIN_TRADES_LOW_CONFIDENCE * 0.5
        flags.append("LOW_SAMPLE_SIZE")

    # ---- Weighted final score ----
    weights = {
        "win_rate": 0.25,
        "avg_roi": 0.25,
        "consistency": 0.15,
        "risk_mgmt": 0.15,
        "trade_freq": 0.10,
        "drawdown": 0.10,
    }
    raw_score = (
        win_rate_score * weights["win_rate"]
        + avg_roi_score * weights["avg_roi"]
        + consistency_score * weights["consistency"]
        + risk_mgmt_score * weights["risk_mgmt"]
        + freq_score * weights["trade_freq"]
        + drawdown_score * weights["drawdown"]
    )

    # Apply sample size dampening
    final_score = raw_score * (0.5 + confidence * 0.5)

    # Wallet-level flags
    if wallet and wallet.risk_flags:
        for flag in wallet.risk_flags:
            if flag not in flags:
                flags.append(flag)
            final_score *= 0.85  # Penalize flagged wallets

    return ScoreBreakdown(
        win_rate_score=win_rate_score,
        avg_roi_score=avg_roi_score,
        consistency_score=consistency_score,
        risk_management_score=risk_mgmt_score,
        trade_frequency_score=freq_score,
        drawdown_score=drawdown_score,
        sample_size_score=sample_score,
        final_score=min(100, max(0, final_score)),
        confidence=confidence,
        flags=flags,
    )
