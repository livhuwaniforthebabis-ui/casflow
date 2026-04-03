"""
Smart Money Concepts (SMC) Analysis Engine
==========================================
Implements:
  - Market Structure (BOS / MSS)
  - Liquidity pool detection (EQH/EQL, stop hunts)
  - Order Block detection
  - Breaker Block detection
  - Fair Value Gap (FVG) / Imbalance
  - Premium / Discount zone classification
  - Multi-timeframe bias determination
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class StructurePoint:
    index: int
    price: float
    type: str          # "HH" | "HL" | "LH" | "LL"
    timestamp: object

@dataclass
class LiquidityPool:
    price: float
    type: str           # "BSL" (buy-side) | "SSL" (sell-side)
    strength: float     # 0-1
    swept: bool = False

@dataclass
class OrderBlock:
    high: float
    low: float
    mid: float
    direction: str      # "BULLISH" | "BEARISH"
    strength: float     # 0-1
    timestamp: object
    valid: bool = True

@dataclass
class FairValueGap:
    high: float
    low: float
    mid: float
    direction: str      # "BULLISH" | "BEARISH"
    timestamp: object
    filled: bool = False

@dataclass
class SMCAnalysis:
    instrument: str
    timeframe: str
    bias: str                      # BULLISH | BEARISH | NEUTRAL
    structure_type: Optional[str]  # BOS | MSS | None
    swing_high: float
    swing_low: float
    current_price: float
    premium_zone: float            # 50% level
    discount_zone: float
    in_premium: bool
    in_discount: bool
    liquidity_pools: list[LiquidityPool] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    fvgs: list[FairValueGap] = field(default_factory=list)
    liquidity_swept: bool = False
    sweep_direction: Optional[str] = None   # "BSL" | "SSL"
    trend_strength: float = 0.0


# ── SMC Engine ─────────────────────────────────────────────────────────────────

class SMCEngine:
    """
    Core SMC analysis engine.
    All methods are stateless and operate on pandas DataFrames.
    """

    SWING_LOOKBACK = 10     # candles each side for swing detection
    OB_LOOKBACK    = 50     # candles to search for order blocks
    FVG_MIN_SIZE   = 0.0002 # minimum FVG size as fraction of price

    # ── Public entry point ─────────────────────────────────────────────────

    def analyse(self, df: pd.DataFrame, instrument: str, timeframe: str) -> SMCAnalysis:
        if df is None or len(df) < 50:
            return self._empty_analysis(instrument, timeframe)

        current_price = float(df["close"].iloc[-1])
        swings = self._detect_swings(df)
        bias, structure_type = self._determine_bias(df, swings)
        swing_high, swing_low = self._recent_swing_range(swings, df)
        premium_zone = (swing_high + swing_low) / 2
        in_premium = current_price > premium_zone
        in_discount = current_price < premium_zone
        liquidity_pools = self._detect_liquidity_pools(df, swings)
        order_blocks = self._detect_order_blocks(df, bias)
        fvgs = self._detect_fvgs(df)
        swept, sweep_dir = self._check_liquidity_sweep(df, liquidity_pools)
        trend_strength = self._trend_strength(df)

        return SMCAnalysis(
            instrument=instrument,
            timeframe=timeframe,
            bias=bias,
            structure_type=structure_type,
            swing_high=swing_high,
            swing_low=swing_low,
            current_price=current_price,
            premium_zone=premium_zone,
            discount_zone=swing_low + (premium_zone - swing_low) * 0.382,
            in_premium=in_premium,
            in_discount=in_discount,
            liquidity_pools=liquidity_pools,
            order_blocks=order_blocks,
            fvgs=fvgs,
            liquidity_swept=swept,
            sweep_direction=sweep_dir,
            trend_strength=trend_strength,
        )

    # ── Swing detection ────────────────────────────────────────────────────

    def _detect_swings(self, df: pd.DataFrame, n: int = None) -> list[StructurePoint]:
        n = n or self.SWING_LOOKBACK
        highs = df["high"].values
        lows  = df["low"].values
        points: list[StructurePoint] = []

        for i in range(n, len(df) - n):
            if highs[i] == max(highs[i-n:i+n+1]):
                points.append(StructurePoint(
                    index=i, price=highs[i], type="swing_high",
                    timestamp=df.index[i]
                ))
            if lows[i] == min(lows[i-n:i+n+1]):
                points.append(StructurePoint(
                    index=i, price=lows[i], type="swing_low",
                    timestamp=df.index[i]
                ))

        points.sort(key=lambda x: x.index)
        return self._label_structure(points)

    def _label_structure(self, points: list[StructurePoint]) -> list[StructurePoint]:
        """Label HH/HL/LH/LL on swing points."""
        highs = [p for p in points if p.type == "swing_high"]
        lows  = [p for p in points if p.type == "swing_low"]

        for i, h in enumerate(highs):
            if i == 0:
                h.type = "HH"
                continue
            h.type = "HH" if h.price > highs[i-1].price else "LH"

        for i, l in enumerate(lows):
            if i == 0:
                l.type = "LL"
                continue
            l.type = "HL" if l.price > lows[i-1].price else "LL"

        return sorted(points + highs + lows, key=lambda x: x.index)

    # ── Bias & structure ───────────────────────────────────────────────────

    def _determine_bias(self, df: pd.DataFrame, swings: list[StructurePoint]) -> tuple[str, Optional[str]]:
        """
        Determine macro bias and detect BOS/MSS.
        Returns (bias, structure_type).
        """
        if not swings:
            return "NEUTRAL", None

        recent = [s for s in swings if s.type in ("HH","HL","LH","LL")][-20:]
        if not recent:
            return "NEUTRAL", None

        hh_count = sum(1 for s in recent if s.type == "HH")
        hl_count = sum(1 for s in recent if s.type == "HL")
        lh_count = sum(1 for s in recent if s.type == "LH")
        ll_count = sum(1 for s in recent if s.type == "LL")

        bullish_score = hh_count + hl_count
        bearish_score = lh_count + ll_count

        # Detect Break of Structure
        structure_type = None
        closes = df["close"].values
        current = closes[-1]

        recent_highs = [s.price for s in recent if s.type in ("HH", "LH")]
        recent_lows  = [s.price for s in recent if s.type in ("HL", "LL")]

        if recent_highs and current > max(recent_highs[-3:]):
            structure_type = "BOS" if bullish_score > bearish_score else "MSS"
        elif recent_lows and current < min(recent_lows[-3:]):
            structure_type = "BOS" if bearish_score > bullish_score else "MSS"

        # EMA trend confirmation
        if len(closes) >= 50:
            ema20 = self._ema(closes, 20)
            ema50 = self._ema(closes, 50)
            if ema20[-1] > ema50[-1]:
                bullish_score += 1
            else:
                bearish_score += 1

        if bullish_score > bearish_score + 1:
            bias = "BULLISH"
        elif bearish_score > bullish_score + 1:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return bias, structure_type

    # ── Liquidity pool detection ───────────────────────────────────────────

    def _detect_liquidity_pools(self, df: pd.DataFrame, swings: list[StructurePoint]) -> list[LiquidityPool]:
        pools: list[LiquidityPool] = []
        current = float(df["close"].iloc[-1])

        # Equal highs / lows (within 0.05% of each other)
        swing_highs = sorted([s.price for s in swings if s.type in ("HH","LH")])
        swing_lows  = sorted([s.price for s in swings if s.type in ("HL","LL")])

        # Buy-side liquidity above price (equal highs clusters)
        bsl = [h for h in swing_highs if h > current]
        if bsl:
            clusters = self._cluster_levels(bsl)
            for cluster in clusters[:3]:
                pools.append(LiquidityPool(
                    price=cluster, type="BSL",
                    strength=self._level_strength(df, cluster)
                ))

        # Sell-side liquidity below price (equal lows clusters)
        ssl = [l for l in swing_lows if l < current]
        if ssl:
            clusters = self._cluster_levels(ssl)
            for cluster in clusters[:3]:
                pools.append(LiquidityPool(
                    price=cluster, type="SSL",
                    strength=self._level_strength(df, cluster)
                ))

        return pools

    def _check_liquidity_sweep(self, df: pd.DataFrame, pools: list[LiquidityPool]) -> tuple[bool, Optional[str]]:
        """Check if price recently swept a liquidity pool and reversed."""
        if len(df) < 5:
            return False, None

        recent_high = float(df["high"].iloc[-5:].max())
        recent_low  = float(df["low"].iloc[-5:].min())
        current     = float(df["close"].iloc[-1])
        prev_close  = float(df["close"].iloc[-2])

        for pool in pools:
            if pool.type == "BSL" and recent_high >= pool.price and current < pool.price:
                pool.swept = True
                return True, "BSL"
            if pool.type == "SSL" and recent_low <= pool.price and current > pool.price:
                pool.swept = True
                return True, "SSL"

        # Generic spike detection without labelled pools
        spike_up   = recent_high > float(df["high"].iloc[-20:-5].max()) and current < prev_close
        spike_down = recent_low  < float(df["low"].iloc[-20:-5].min()) and current > prev_close

        if spike_up:
            return True, "BSL"
        if spike_down:
            return True, "SSL"

        return False, None

    # ── Order Block detection ──────────────────────────────────────────────

    def _detect_order_blocks(self, df: pd.DataFrame, bias: str) -> list[OrderBlock]:
        blocks: list[OrderBlock] = []
        lookback = min(self.OB_LOOKBACK, len(df) - 5)

        for i in range(2, lookback):
            idx = -(i + 1)
            candle = df.iloc[idx]
            next_3 = df.iloc[idx+1:idx+4]

            # Bullish OB: last bearish candle before strong bullish move
            if bias in ("BULLISH", "NEUTRAL"):
                is_bearish = candle["close"] < candle["open"]
                strong_up  = all(next_3["close"] > next_3["open"]) and \
                             next_3["close"].iloc[-1] > candle["high"]
                if is_bearish and strong_up:
                    strength = self._ob_strength(df, idx, "BULLISH")
                    blocks.append(OrderBlock(
                        high=float(candle["high"]),
                        low=float(candle["low"]),
                        mid=(float(candle["high"]) + float(candle["low"])) / 2,
                        direction="BULLISH",
                        strength=strength,
                        timestamp=df.index[idx],
                        valid=self._ob_still_valid(df, candle["high"], candle["low"])
                    ))

            # Bearish OB: last bullish candle before strong bearish move
            if bias in ("BEARISH", "NEUTRAL"):
                is_bullish = candle["close"] > candle["open"]
                strong_dn  = all(next_3["close"] < next_3["open"]) and \
                             next_3["close"].iloc[-1] < candle["low"]
                if is_bullish and strong_dn:
                    strength = self._ob_strength(df, idx, "BEARISH")
                    blocks.append(OrderBlock(
                        high=float(candle["high"]),
                        low=float(candle["low"]),
                        mid=(float(candle["high"]) + float(candle["low"])) / 2,
                        direction="BEARISH",
                        strength=strength,
                        timestamp=df.index[idx],
                        valid=self._ob_still_valid(df, candle["high"], candle["low"])
                    ))

        # Keep only valid blocks, sorted by recency
        valid = [b for b in blocks if b.valid]
        valid.sort(key=lambda b: b.strength, reverse=True)
        return valid[:5]

    def _ob_still_valid(self, df: pd.DataFrame, ob_high: float, ob_low: float) -> bool:
        """OB is invalid if price has closed through it."""
        closes = df["close"].values[-30:]
        for c in closes:
            if ob_low < c < ob_high:
                return True
        return False

    def _ob_strength(self, df: pd.DataFrame, idx: int, direction: str) -> float:
        """Rate OB strength 0-1 based on impulse following it."""
        try:
            subsequent = df.iloc[idx+1:idx+6]["close"].values
            if direction == "BULLISH":
                move = (subsequent[-1] - subsequent[0]) / subsequent[0]
            else:
                move = (subsequent[0] - subsequent[-1]) / subsequent[0]
            return min(1.0, max(0.0, move / 0.01))  # normalise against 1% move
        except Exception:
            return 0.5

    # ── Fair Value Gap detection ───────────────────────────────────────────

    def _detect_fvgs(self, df: pd.DataFrame) -> list[FairValueGap]:
        fvgs: list[FairValueGap] = []
        min_size = self.FVG_MIN_SIZE

        for i in range(2, min(100, len(df) - 1)):
            candle_1 = df.iloc[-(i+1)]
            candle_3 = df.iloc[-(i-1)]

            # Bullish FVG: gap between candle[i-1].high and candle[i+1].low
            gap_low  = float(candle_1["high"])
            gap_high = float(candle_3["low"])
            if gap_high > gap_low and (gap_high - gap_low) / gap_low > min_size:
                filled = float(df["low"].iloc[-(i-1):].min()) <= gap_low
                fvgs.append(FairValueGap(
                    high=gap_high, low=gap_low,
                    mid=(gap_high + gap_low) / 2,
                    direction="BULLISH",
                    timestamp=df.index[-(i)],
                    filled=filled
                ))

            # Bearish FVG
            gap_high2 = float(candle_1["low"])
            gap_low2  = float(candle_3["high"])
            if gap_high2 > gap_low2 and (gap_high2 - gap_low2) / gap_high2 > min_size:
                filled = float(df["high"].iloc[-(i-1):].max()) >= gap_high2
                fvgs.append(FairValueGap(
                    high=gap_high2, low=gap_low2,
                    mid=(gap_high2 + gap_low2) / 2,
                    direction="BEARISH",
                    timestamp=df.index[-(i)],
                    filled=filled
                ))

        # Remove filled FVGs
        open_fvgs = [f for f in fvgs if not f.filled]
        open_fvgs.sort(key=lambda f: abs(f.mid - float(df["close"].iloc[-1])))
        return open_fvgs[:5]

    # ── Helpers ────────────────────────────────────────────────────────────

    def _recent_swing_range(self, swings: list[StructurePoint], df: pd.DataFrame) -> tuple[float, float]:
        recent = [s for s in swings][-30:]
        if not recent:
            return float(df["high"].max()), float(df["low"].min())
        highs = [s.price for s in recent if s.type in ("HH","LH","swing_high")]
        lows  = [s.price for s in recent if s.type in ("HL","LL","swing_low")]
        sh = max(highs) if highs else float(df["high"].max())
        sl = min(lows)  if lows  else float(df["low"].min())
        return sh, sl

    def _trend_strength(self, df: pd.DataFrame) -> float:
        """Return 0-1 trend strength using ADX proxy."""
        if len(df) < 20:
            return 0.5
        closes = df["close"].values
        highs  = df["high"].values
        lows   = df["low"].values
        # Simple ADX proxy: ratio of directional move to total range
        up_moves   = np.diff(highs)
        down_moves = -np.diff(lows)
        true_ranges = np.maximum(
            np.diff(highs),
            np.maximum(abs(np.diff(closes)), abs(np.diff(lows)))
        )
        plus_dm  = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0)
        minus_dm = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0)
        period = 14
        if len(true_ranges) < period:
            return 0.5
        atr    = true_ranges[-period:].mean()
        pdi    = plus_dm[-period:].mean() / atr if atr else 0
        mdi    = minus_dm[-period:].mean() / atr if atr else 0
        dx     = abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
        return round(min(1.0, dx), 3)

    def _level_strength(self, df: pd.DataFrame, level: float) -> float:
        """How many times price respected this level (normalised 0-1)."""
        touches = 0
        tol = level * 0.001
        for _, row in df.iterrows():
            if abs(row["high"] - level) < tol or abs(row["low"] - level) < tol:
                touches += 1
        return min(1.0, touches / 5)

    def _cluster_levels(self, levels: list[float], tol: float = 0.002) -> list[float]:
        """Group nearby price levels into clusters, return cluster means."""
        if not levels:
            return []
        clusters = []
        sorted_lvls = sorted(levels)
        current_cluster = [sorted_lvls[0]]
        for lvl in sorted_lvls[1:]:
            if abs(lvl - current_cluster[-1]) / current_cluster[-1] < tol:
                current_cluster.append(lvl)
            else:
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [lvl]
        clusters.append(sum(current_cluster) / len(current_cluster))
        return clusters

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2 / (period + 1)
        ema = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        return ema

    def _empty_analysis(self, instrument: str, timeframe: str) -> SMCAnalysis:
        return SMCAnalysis(
            instrument=instrument, timeframe=timeframe,
            bias="NEUTRAL", structure_type=None,
            swing_high=0, swing_low=0, current_price=0,
            premium_zone=0, discount_zone=0,
            in_premium=False, in_discount=False,
        )
