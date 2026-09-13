"""Unit tests for Smart Money Score computation."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.analytics.smart_money_score import ScoreBreakdown, compute_score


def _make_metrics(
    total_trades: int = 30,
    win_rate: float = 60.0,
    average_roi: float = 80.0,
    profit_factor: float = 2.0,
    max_drawdown: float = 10.0,
    total_pnl_usd: float = 5000.0,
    median_roi: float = 60.0,
    average_profit_usd: float = 500.0,
    average_loss_usd: float = 200.0,
) -> MagicMock:
    m = MagicMock()
    m.total_trades = total_trades
    m.win_rate = win_rate
    m.average_roi = average_roi
    m.median_roi = median_roi
    m.profit_factor = profit_factor
    m.max_drawdown = max_drawdown
    m.total_pnl_usd = total_pnl_usd
    m.best_trade_roi = 300.0
    m.worst_trade_roi = -40.0
    m.average_profit_usd = average_profit_usd
    m.average_loss_usd = average_loss_usd
    return m


def test_score_returns_breakdown():
    metrics = _make_metrics()
    result = compute_score(metrics)
    assert isinstance(result, ScoreBreakdown)
    assert 0 <= result.final_score <= 100


def test_low_sample_size_penalizes_score():
    metrics_few = _make_metrics(total_trades=3, win_rate=80.0, average_roi=200.0)
    metrics_many = _make_metrics(total_trades=100, win_rate=80.0, average_roi=200.0)
    few = compute_score(metrics_few)
    many = compute_score(metrics_many)
    assert few.final_score < many.final_score
    assert "LOW_SAMPLE_SIZE" in few.flags


def test_perfect_stats_give_high_score():
    metrics = _make_metrics(
        total_trades=100,
        win_rate=80.0,
        average_roi=150.0,
        profit_factor=5.0,
        max_drawdown=3.0,
    )
    result = compute_score(metrics)
    assert result.final_score >= 70


def test_poor_stats_give_low_score():
    metrics = _make_metrics(
        total_trades=50,
        win_rate=30.0,
        average_roi=-20.0,
        profit_factor=0.5,
        max_drawdown=60.0,
        median_roi=-15.0,
        average_profit_usd=100.0,
        average_loss_usd=300.0,
    )
    result = compute_score(metrics)
    assert result.final_score < 40


def test_zero_trades_returns_zero():
    metrics = _make_metrics(
        total_trades=0, win_rate=0, average_roi=0, profit_factor=0,
        max_drawdown=0, median_roi=0, average_profit_usd=0, average_loss_usd=0,
    )
    result = compute_score(metrics)
    assert result.final_score < 20  # Near-zero — no real trading history
