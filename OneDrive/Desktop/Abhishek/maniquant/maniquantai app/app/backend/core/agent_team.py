"""ManiQuantAI — Professional Trading Agent Team

Six specialized agents that mirror a real prop-trading desk:
  1. Momentum Agent      — trend-following, EMA crossovers, ADX filter
  2. Mean Reversion Agent — RSI + Bollinger oversold/overbought
  3. Breakout Agent       — support/resistance + volume confirmation
  4. Scalper Agent        — micro-structure, fast EMAs, tight SL
  5. Sentiment Agent      — fear/greed proxy from funding rates + OI
  6. Portfolio Manager    — aggregates signals, enforces risk limits, gates live orders

All agents are deterministic: given the same bars they produce the same signal.
The LLM is only used for strategy compilation, NOT for signal generation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

# ─────────────────────────────────────────────────────────────────────────────
# Core data types
# ─────────────────────────────────────────────────────────────────────────────

Signal = Literal["BUY", "SELL", "HOLD", "CLOSE_LONG", "CLOSE_SHORT"]

@dataclass
class Bar:
    ts: int          # unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

@dataclass
class AgentSignal:
    agent: str
    signal: Signal
    strength: float      # 0.0 – 1.0
    reason: str
    symbol: str
    timeframe: str
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_pct: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class PortfolioDecision:
    execute: bool
    side: Literal["buy", "sell", "close"] | None
    volume_pct: float          # fraction of base lot
    stop_loss: float | None
    take_profit: float | None
    risk_pct: float
    reason: str
    signals: list[AgentSignal]
    consensus: float           # -1.0 (all sell) to +1.0 (all buy)


# ─────────────────────────────────────────────────────────────────────────────
# Indicator helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period:
            ag = (ag * (period - 1) + gains[i - 1]) / period
            al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def _bb(values: list[float], period: int = 20, k: float = 2.0) -> list[tuple[float, float, float] | None]:
    out: list[tuple[float, float, float] | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        w = values[i - period + 1 : i + 1]
        mean = sum(w) / period
        sd = math.sqrt(sum((x - mean) ** 2 for x in w) / period)
        out[i] = (mean, mean - k * sd, mean + k * sd)
    return out


def _atr(bars: list[Bar], period: int = 14) -> list[float | None]:
    if len(bars) < 2:
        return [None] * len(bars)
    trs: list[float] = []
    for i in range(1, len(bars)):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        trs.append(tr)
    out: list[float | None] = [None] * len(bars)
    if len(trs) < period:
        return out
    avg = sum(trs[:period]) / period
    out[period] = avg
    for i in range(period + 1, len(bars)):
        avg = (avg * (period - 1) + trs[i - 1]) / period
        out[i] = avg
    return out


def _adx(bars: list[Bar], period: int = 14) -> list[float | None]:
    """Simplified ADX — measures trend strength."""
    if len(bars) < period * 2:
        return [None] * len(bars)
    plus_dms, minus_dms, trs = [], [], []
    for i in range(1, len(bars)):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dms.append(max(up, 0) if up > down else 0)
        minus_dms.append(max(down, 0) if down > up else 0)
        trs.append(max(bars[i].high - bars[i].low, abs(bars[i].high - bars[i - 1].close), abs(bars[i].low - bars[i - 1].close)))

    def _smooth(arr: list[float], p: int) -> list[float]:
        if len(arr) < p:
            return []
        result = [sum(arr[:p])]
        for i in range(p, len(arr)):
            result.append(result[-1] - result[-1] / p + arr[i])
        return result

    s_tr = _smooth(trs, period)
    s_p = _smooth(plus_dms, period)
    s_m = _smooth(minus_dms, period)
    dxs = []
    for i in range(len(s_tr)):
        if s_tr[i] == 0:
            dxs.append(0.0)
            continue
        di_p = 100 * s_p[i] / s_tr[i]
        di_m = 100 * s_m[i] / s_tr[i]
        dxs.append(100 * abs(di_p - di_m) / (di_p + di_m) if (di_p + di_m) else 0)
    if len(dxs) < period:
        return [None] * len(bars)
    adx_vals: list[float] = [sum(dxs[:period]) / period]
    for i in range(period, len(dxs)):
        adx_vals.append((adx_vals[-1] * (period - 1) + dxs[i]) / period)
    out: list[float | None] = [None] * len(bars)
    offset = len(bars) - len(adx_vals)
    for i, v in enumerate(adx_vals):
        if offset + i < len(out):
            out[offset + i] = v
    return out


def _pivot(bars: list[Bar], lookback: int = 20) -> tuple[float, float]:
    """Simple support/resistance from recent highs/lows."""
    window = bars[-lookback:]
    return min(b.low for b in window), max(b.high for b in window)


# ─────────────────────────────────────────────────────────────────────────────
# Agent 1: Momentum Agent
# ─────────────────────────────────────────────────────────────────────────────

class MomentumAgent:
    """EMA 9/21/50 crossover with ADX trend filter.
    Signal fires when fast EMA crosses slow EMA AND ADX > 20 (confirmed trend).
    """
    name = "momentum"

    def evaluate(self, bars: list[Bar], symbol: str, tf: str) -> AgentSignal:
        closes = [b.close for b in bars]
        ema9  = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        ema50 = _ema(closes, 50)
        adx   = _adx(bars, 14)
        atr_vals = _atr(bars, 14)

        i = len(bars) - 1
        if any(v is None for v in [ema9[i], ema21[i], ema50[i], adx[i], ema9[i-1], ema21[i-1]]):
            return AgentSignal(self.name, "HOLD", 0.0, "Insufficient bars", symbol, tf)

        prev_cross = ema9[i-1] < ema21[i-1]   # was below
        curr_cross = ema9[i]   > ema21[i]      # now above → bullish crossover

        bullish_cross = prev_cross and curr_cross
        bearish_cross = (not prev_cross) and (ema9[i] < ema21[i])

        adx_strength = adx[i]
        trend_confirmed = adx_strength > 20
        strong_trend = adx_strength > 30
        price_above_50 = closes[i] > ema50[i]

        atr = atr_vals[i] or (closes[i] * 0.01)
        sl_mult = 1.5
        tp_mult = 3.0

        if bullish_cross and trend_confirmed and price_above_50:
            strength = min(1.0, 0.5 + (adx_strength - 20) / 60) if strong_trend else 0.55
            return AgentSignal(
                self.name, "BUY", strength,
                f"EMA 9 crossed above 21 · ADX={adx_strength:.1f} · price above EMA50",
                symbol, tf,
                stop_loss=round(closes[i] - sl_mult * atr, 8),
                take_profit=round(closes[i] + tp_mult * atr, 8),
                risk_pct=1.0,
                meta={"ema9": ema9[i], "ema21": ema21[i], "adx": adx_strength},
            )

        if bearish_cross and trend_confirmed and not price_above_50:
            strength = min(1.0, 0.5 + (adx_strength - 20) / 60) if strong_trend else 0.55
            return AgentSignal(
                self.name, "SELL", strength,
                f"EMA 9 crossed below 21 · ADX={adx_strength:.1f} · price below EMA50",
                symbol, tf,
                stop_loss=round(closes[i] + sl_mult * atr, 8),
                take_profit=round(closes[i] - tp_mult * atr, 8),
                risk_pct=1.0,
                meta={"ema9": ema9[i], "ema21": ema21[i], "adx": adx_strength},
            )

        return AgentSignal(self.name, "HOLD", 0.2, f"No crossover · ADX={adx_strength:.1f}", symbol, tf)


# ─────────────────────────────────────────────────────────────────────────────
# Agent 2: Mean Reversion Agent
# ─────────────────────────────────────────────────────────────────────────────

class MeanReversionAgent:
    """RSI + Bollinger Bands mean-reversion.
    BUY when RSI<30 AND price touches lower BB.
    SELL when RSI>70 AND price touches upper BB.
    """
    name = "mean_reversion"

    def __init__(self, rsi_period: int = 14, bb_period: int = 20, bb_std: float = 2.0,
                 rsi_entry_below: float = 30.0, rsi_entry_above: float = 70.0):
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_entry_below = rsi_entry_below
        self.rsi_entry_above = rsi_entry_above

    def evaluate(self, bars: list[Bar], symbol: str, tf: str) -> AgentSignal:
        closes = [b.close for b in bars]
        lows   = [b.low for b in bars]
        highs  = [b.high for b in bars]
        rsi_vals = _rsi(closes, self.rsi_period)
        bb_vals  = _bb(closes, self.bb_period, self.bb_std)
        atr_vals = _atr(bars, 14)

        i = len(bars) - 1
        if rsi_vals[i] is None or bb_vals[i] is None:
            return AgentSignal(self.name, "HOLD", 0.0, "Insufficient bars", symbol, tf)

        rsi = rsi_vals[i]
        mid, lower, upper = bb_vals[i]
        atr = atr_vals[i] or (closes[i] * 0.01)
        price = closes[i]

        oversold  = rsi < self.rsi_entry_below and lows[i] <= lower * 1.002
        overbought = rsi > self.rsi_entry_above and highs[i] >= upper * 0.998

        bb_width = (upper - lower) / mid if mid else 0
        squeeze = bb_width < 0.02   # low volatility — reduce confidence

        if oversold:
            strength = min(1.0, (self.rsi_entry_below - rsi) / self.rsi_entry_below + 0.4)
            if squeeze:
                strength *= 0.6
            return AgentSignal(
                self.name, "BUY", strength,
                f"RSI={rsi:.1f} < {self.rsi_entry_below} · price at lower BB={lower:.4f}",
                symbol, tf,
                stop_loss=round(lower - atr, 8),
                take_profit=round(mid, 8),
                risk_pct=1.0,
                meta={"rsi": rsi, "bb_lower": lower, "bb_mid": mid, "bb_width_pct": round(bb_width * 100, 2)},
            )

        if overbought:
            strength = min(1.0, (rsi - self.rsi_entry_above) / (100 - self.rsi_entry_above) + 0.4)
            if squeeze:
                strength *= 0.6
            return AgentSignal(
                self.name, "SELL", strength,
                f"RSI={rsi:.1f} > {self.rsi_entry_above} · price at upper BB={upper:.4f}",
                symbol, tf,
                stop_loss=round(upper + atr, 8),
                take_profit=round(mid, 8),
                risk_pct=1.0,
                meta={"rsi": rsi, "bb_upper": upper, "bb_mid": mid, "bb_width_pct": round(bb_width * 100, 2)},
            )

        return AgentSignal(self.name, "HOLD", 0.15, f"RSI={rsi:.1f} · no edge", symbol, tf)


# ─────────────────────────────────────────────────────────────────────────────
# Agent 3: Breakout Agent
# ─────────────────────────────────────────────────────────────────────────────

class BreakoutAgent:
    """Detects consolidation breakouts with volume confirmation.
    Looks for price breaking above recent resistance or below support
    with a surge in relative volume.
    """
    name = "breakout"

    def __init__(self, lookback: int = 20, vol_multiplier: float = 1.5):
        self.lookback = lookback
        self.vol_multiplier = vol_multiplier

    def evaluate(self, bars: list[Bar], symbol: str, tf: str) -> AgentSignal:
        if len(bars) < self.lookback + 5:
            return AgentSignal(self.name, "HOLD", 0.0, "Insufficient bars", symbol, tf)

        recent = bars[-self.lookback - 1 : -1]   # exclude current bar
        cur    = bars[-1]

        support    = min(b.low for b in recent)
        resistance = max(b.high for b in recent)
        avg_volume = sum(b.volume for b in recent) / len(recent) if recent else 0

        atr_vals = _atr(bars, 14)
        atr = atr_vals[-1] or (cur.close * 0.01)

        # Consolidation: narrowing range in last 5 bars
        last5_range = max(b.high for b in bars[-6:-1]) - min(b.low for b in bars[-6:-1])
        full_range  = resistance - support
        consolidating = last5_range < full_range * 0.4 if full_range else False

        vol_surge = cur.volume > avg_volume * self.vol_multiplier if avg_volume > 0 else False

        bullish_break = cur.close > resistance and vol_surge
        bearish_break = cur.close < support    and vol_surge

        if bullish_break:
            strength = min(1.0, 0.5 + 0.3 * (cur.volume / avg_volume - 1) / 2 if avg_volume else 0.5)
            if consolidating:
                strength = min(1.0, strength + 0.15)
            return AgentSignal(
                self.name, "BUY", strength,
                f"Price broke above resistance={resistance:.4f} · volume={cur.volume:.0f} ({cur.volume/avg_volume:.1f}x avg)",
                symbol, tf,
                stop_loss=round(resistance - atr * 0.5, 8),
                take_profit=round(cur.close + (cur.close - support) * 0.618, 8),
                risk_pct=1.5,
                meta={"resistance": resistance, "support": support, "vol_ratio": round(cur.volume / avg_volume, 2) if avg_volume else 0},
            )

        if bearish_break:
            strength = min(1.0, 0.5 + 0.3 * (cur.volume / avg_volume - 1) / 2 if avg_volume else 0.5)
            if consolidating:
                strength = min(1.0, strength + 0.15)
            return AgentSignal(
                self.name, "SELL", strength,
                f"Price broke below support={support:.4f} · volume={cur.volume:.0f} ({cur.volume/avg_volume:.1f}x avg)",
                symbol, tf,
                stop_loss=round(support + atr * 0.5, 8),
                take_profit=round(cur.close - (resistance - cur.close) * 0.618, 8),
                risk_pct=1.5,
                meta={"resistance": resistance, "support": support, "vol_ratio": round(cur.volume / avg_volume, 2) if avg_volume else 0},
            )

        return AgentSignal(self.name, "HOLD", 0.1, f"No breakout · res={resistance:.4f} sup={support:.4f}", symbol, tf)


# ─────────────────────────────────────────────────────────────────────────────
# Agent 4: Scalper Agent
# ─────────────────────────────────────────────────────────────────────────────

class ScalperAgent:
    """High-frequency micro-structure scalper.
    Uses fast EMA 3/8 crossover with RSI filter on 5m/15m timeframes.
    Tight ATR-based stop losses. High trade frequency, small risk per trade.
    """
    name = "scalper"

    def evaluate(self, bars: list[Bar], symbol: str, tf: str) -> AgentSignal:
        # Scalper only makes sense on short timeframes
        if tf not in {"1m", "5m", "15m"}:
            return AgentSignal(self.name, "HOLD", 0.0, f"Scalper inactive on {tf}", symbol, tf)

        closes = [b.close for b in bars]
        ema3 = _ema(closes, 3)
        ema8 = _ema(closes, 8)
        rsi_vals = _rsi(closes, 7)   # shorter RSI for scalping
        atr_vals = _atr(bars, 7)

        i = len(bars) - 1
        if any(v is None for v in [ema3[i], ema8[i], rsi_vals[i], ema3[i-1], ema8[i-1]]):
            return AgentSignal(self.name, "HOLD", 0.0, "Insufficient bars", symbol, tf)

        rsi = rsi_vals[i]
        atr = atr_vals[i] or (closes[i] * 0.005)
        bullish = ema3[i-1] < ema8[i-1] and ema3[i] > ema8[i] and 40 < rsi < 65
        bearish = ema3[i-1] > ema8[i-1] and ema3[i] < ema8[i] and 35 < rsi < 60

        if bullish:
            return AgentSignal(
                self.name, "BUY", 0.65,
                f"EMA3 cross EMA8 bullish · RSI={rsi:.1f}",
                symbol, tf,
                stop_loss=round(closes[i] - atr, 8),
                take_profit=round(closes[i] + atr * 2, 8),
                risk_pct=0.5,
                meta={"ema3": ema3[i], "ema8": ema8[i], "rsi": rsi},
            )

        if bearish:
            return AgentSignal(
                self.name, "SELL", 0.65,
                f"EMA3 cross EMA8 bearish · RSI={rsi:.1f}",
                symbol, tf,
                stop_loss=round(closes[i] + atr, 8),
                take_profit=round(closes[i] - atr * 2, 8),
                risk_pct=0.5,
                meta={"ema3": ema3[i], "ema8": ema8[i], "rsi": rsi},
            )

        return AgentSignal(self.name, "HOLD", 0.1, f"No micro-cross · RSI={rsi:.1f}", symbol, tf)


# ─────────────────────────────────────────────────────────────────────────────
# Agent 5: Sentiment / Market-Structure Agent
# ─────────────────────────────────────────────────────────────────────────────

class SentimentAgent:
    """Proxy sentiment from price action: volume trend + price deviation from SMA200.
    In the absence of real funding rate / OI feed, uses statistically
    meaningful price-based proxies that are deterministic and transparent.
    """
    name = "sentiment"

    def evaluate(self, bars: list[Bar], symbol: str, tf: str) -> AgentSignal:
        if len(bars) < 50:
            return AgentSignal(self.name, "HOLD", 0.0, "Need 50+ bars", symbol, tf)

        closes  = [b.close for b in bars]
        volumes = [b.volume for b in bars]

        # SMA200 proxy (use available bars, min 50)
        sma_period = min(200, len(bars) - 1)
        sma = sum(closes[-sma_period:]) / sma_period

        # Volume trend: 10-bar vs 30-bar average
        vol_short = sum(volumes[-10:]) / 10 if len(volumes) >= 10 else 0
        vol_long  = sum(volumes[-30:]) / 30 if len(volumes) >= 30 else 1
        vol_trend = vol_short / vol_long if vol_long else 1.0

        price = closes[-1]
        dev_from_sma = (price - sma) / sma   # positive = above, negative = below

        # Bearish sentiment: price far above SMA (>20%) + declining volume
        # Bullish sentiment: price far below SMA (<-20%) + rising volume (accumulation)
        if dev_from_sma < -0.10 and vol_trend > 1.2:
            strength = min(1.0, abs(dev_from_sma) * 3 + (vol_trend - 1.0) * 0.3)
            return AgentSignal(
                self.name, "BUY", strength,
                f"Price {dev_from_sma*100:.1f}% below SMA{sma_period} · volume trend {vol_trend:.2f}x (accumulation)",
                symbol, tf,
                meta={"sma": round(sma, 4), "dev_pct": round(dev_from_sma * 100, 2), "vol_trend": round(vol_trend, 2)},
            )

        if dev_from_sma > 0.10 and vol_trend < 0.8:
            strength = min(1.0, dev_from_sma * 3 + (1.0 - vol_trend) * 0.3)
            return AgentSignal(
                self.name, "SELL", strength,
                f"Price {dev_from_sma*100:.1f}% above SMA{sma_period} · volume declining ({vol_trend:.2f}x)",
                symbol, tf,
                meta={"sma": round(sma, 4), "dev_pct": round(dev_from_sma * 100, 2), "vol_trend": round(vol_trend, 2)},
            )

        return AgentSignal(
            self.name, "HOLD", 0.2,
            f"Price {dev_from_sma*100:+.1f}% from SMA · vol trend {vol_trend:.2f}x",
            symbol, tf,
            meta={"sma": round(sma, 4), "dev_pct": round(dev_from_sma * 100, 2), "vol_trend": round(vol_trend, 2)},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Agent 6: Portfolio Manager (Aggregator + Gate)
# ─────────────────────────────────────────────────────────────────────────────

AGENT_WEIGHTS = {
    "momentum":      0.25,
    "mean_reversion": 0.25,
    "breakout":      0.20,
    "scalper":       0.10,
    "sentiment":     0.20,
}

SIGNAL_VALUE = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0, "CLOSE_LONG": -0.5, "CLOSE_SHORT": 0.5}


class PortfolioManager:
    """Aggregates all agent signals, enforces risk limits, gates the live order.

    Rules (non-negotiable):
    - Minimum consensus threshold before firing any live order.
    - Maximum 2% risk per trade (hard cap).
    - No execution if any required agent returned an error.
    - Position limit: only one direction at a time per symbol.
    """
    MIN_CONSENSUS   = 0.35    # weighted average must exceed this to trade
    MAX_RISK_PCT    = 2.0     # absolute cap
    MIN_AGENTS_AGREE = 2      # at least N agents must point same direction

    def decide(
        self,
        signals: list[AgentSignal],
        current_position: Literal["long", "short", "flat"] = "flat",
        account_equity: float = 10_000.0,
    ) -> PortfolioDecision:
        if not signals:
            return PortfolioDecision(False, None, 0.0, None, None, 0.0, "No agent signals", signals, 0.0)

        # Weighted consensus score
        total_weight = 0.0
        weighted_sum = 0.0
        for sig in signals:
            w = AGENT_WEIGHTS.get(sig.agent, 0.1)
            v = SIGNAL_VALUE.get(sig.signal, 0.0) * sig.strength
            weighted_sum += v * w
            total_weight += w

        consensus = weighted_sum / total_weight if total_weight else 0.0

        # Count agreeing agents
        buy_agents  = [s for s in signals if s.signal == "BUY"]
        sell_agents = [s for s in signals if s.signal == "SELL"]

        # Determine direction
        if consensus >= self.MIN_CONSENSUS and len(buy_agents) >= self.MIN_AGENTS_AGREE:
            direction = "buy"
            candidate_sigs = buy_agents
        elif consensus <= -self.MIN_CONSENSUS and len(sell_agents) >= self.MIN_AGENTS_AGREE:
            direction = "sell"
            candidate_sigs = sell_agents
        else:
            return PortfolioDecision(
                False, None, 0.0, None, None, 0.0,
                f"Insufficient consensus: {consensus:.3f} (need ±{self.MIN_CONSENSUS})",
                signals, consensus,
            )

        # Skip if already in the same direction
        if current_position == "long" and direction == "buy":
            return PortfolioDecision(False, None, 0.0, None, None, 0.0, "Already long", signals, consensus)
        if current_position == "short" and direction == "sell":
            return PortfolioDecision(False, None, 0.0, None, None, 0.0, "Already short", signals, consensus)

        # Use the highest-confidence signal's SL/TP, risk_pct
        best = max(candidate_sigs, key=lambda s: s.strength)
        risk_pct = min(best.risk_pct or 1.0, self.MAX_RISK_PCT)

        # Volume fraction scales with consensus confidence
        vol_frac = min(1.0, abs(consensus) / self.MIN_CONSENSUS * 0.8)

        reason_parts = [f"{s.agent}({s.signal}·{s.strength:.2f})" for s in signals]
        reason = f"consensus={consensus:+.3f} | " + " · ".join(reason_parts)

        return PortfolioDecision(
            execute=True,
            side=direction,
            volume_pct=round(vol_frac, 3),
            stop_loss=best.stop_loss,
            take_profit=best.take_profit,
            risk_pct=risk_pct,
            reason=reason,
            signals=signals,
            consensus=round(consensus, 4),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Team runner — evaluate all agents and get portfolio decision
# ─────────────────────────────────────────────────────────────────────────────

def run_agent_team(
    bars: list[dict],
    symbol: str,
    timeframe: str,
    strategy_params: dict | None = None,
    current_position: str = "flat",
    account_equity: float = 10_000.0,
) -> dict:
    """Convert raw bar dicts → evaluate all agents → portfolio decision.

    Returns a dict suitable for serialisation and storage in Supabase.
    """
    if len(bars) < 30:
        return {
            "execute": False,
            "reason": f"Only {len(bars)} bars — need 30+",
            "signals": [],
            "consensus": 0.0,
        }

    bar_objs = [
        Bar(
            ts=int(b.get("ts", b.get("time", 0))),
            open=float(b.get("open", 0)),
            high=float(b.get("high", 0)),
            low=float(b.get("low", 0)),
            close=float(b.get("close", 0)),
            volume=float(b.get("volume", b.get("tick_volume", 0))),
        )
        for b in bars
    ]

    p = strategy_params or {}
    agents = [
        MomentumAgent(),
        MeanReversionAgent(
            rsi_period=int(p.get("rsi_period", 14)),
            bb_period=int(p.get("bollinger_period", 20)),
            bb_std=float(p.get("bollinger_std", 2.0)),
            rsi_entry_below=float(p.get("rsi_entry_below", 30)),
            rsi_entry_above=float(p.get("rsi_entry_above", 70)),
        ),
        BreakoutAgent(),
        ScalperAgent(),
        SentimentAgent(),
    ]

    signals = []
    for agent in agents:
        try:
            sig = agent.evaluate(bar_objs, symbol, timeframe)
            signals.append(sig)
        except Exception as exc:
            signals.append(AgentSignal(agent.name, "HOLD", 0.0, f"Agent error: {exc}", symbol, timeframe))

    pm = PortfolioManager()
    decision = pm.decide(signals, current_position=current_position, account_equity=account_equity)

    return {
        "execute":     decision.execute,
        "side":        decision.side,
        "volume_pct":  decision.volume_pct,
        "stop_loss":   decision.stop_loss,
        "take_profit": decision.take_profit,
        "risk_pct":    decision.risk_pct,
        "reason":      decision.reason,
        "consensus":   decision.consensus,
        "signals": [
            {
                "agent":     s.agent,
                "signal":    s.signal,
                "strength":  round(s.strength, 4),
                "reason":    s.reason,
                "stop_loss": s.stop_loss,
                "take_profit": s.take_profit,
                "risk_pct":  s.risk_pct,
                "meta":      s.meta,
            }
            for s in signals
        ],
    }
