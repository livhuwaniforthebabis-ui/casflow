"""
Signal Generator
================
Runs multi-timeframe SMC analysis and produces trade signals
with confidence scoring, entry/SL/TP calculation, and anti-spam filtering.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from strategy.smc_engine import SMCEngine, SMCAnalysis

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    instrument: str
    direction: str          # BUY | SELL
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    rr_ratio: float
    confidence: float
    daily_bias: str
    structure_type: str
    liquidity_type: str
    poi_type: str
    poi_high: float
    poi_low: float
    session: str
    analysis_text: str
    signal_text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Confidence weights ─────────────────────────────────────────────────────────

WEIGHTS = {
    "daily_bias_aligned":   25,
    "structure_confirmed":  20,
    "liquidity_swept":      15,
    "ob_quality":           15,
    "fvg_present":          10,
    "session_timing":       10,
    "trend_strength":        5,
}


class SignalGenerator:
    def __init__(self, settings):
        self.settings = settings
        self.engine = SMCEngine()

    def generate_signal(
        self,
        analyses: dict[str, SMCAnalysis],   # {"1D": ..., "4H": ..., "1H": ..., "30min": ...}
        instrument: str,
    ) -> Optional[TradeSignal]:
        """
        Execute the SMC multi-timeframe workflow and return a signal or None.
        """
        daily   = analyses.get("1D")
        h4      = analyses.get("4H")
        h1      = analyses.get("1H")
        m30     = analyses.get("30min")

        if not all([daily, h4, h1, m30]):
            return None

        # ── Step 1: Higher TF Bias ────────────────────────────────────────
        if daily.bias == "NEUTRAL":
            logger.debug(f"{instrument}: Daily bias NEUTRAL — skipping")
            return None

        # ── Step 2: Intermediate confirmation ────────────────────────────
        aligned = (h4.bias == daily.bias or h1.bias == daily.bias)
        if not aligned:
            logger.debug(f"{instrument}: Lower TFs not aligned with daily bias")
            return None

        structure = h4.structure_type or h1.structure_type
        if structure is None:
            logger.debug(f"{instrument}: No BOS/MSS on H4 or H1")
            return None

        # ── Step 3: Execution TF — liquidity + POI ───────────────────────
        if not m30.liquidity_swept:
            logger.debug(f"{instrument}: No liquidity sweep on M30")
            return None

        # Determine direction after sweep
        if m30.sweep_direction == "SSL" and daily.bias == "BULLISH":
            direction = "BUY"
        elif m30.sweep_direction == "BSL" and daily.bias == "BEARISH":
            direction = "SELL"
        else:
            logger.debug(f"{instrument}: Sweep direction conflicts with bias")
            return None

        # Locate best POI
        poi, poi_type = self._best_poi(m30, direction)
        if poi is None:
            logger.debug(f"{instrument}: No valid POI found")
            return None

        # ── Calculate trade parameters ────────────────────────────────────
        current = m30.current_price
        if not self._price_at_poi(current, poi, poi_type):
            logger.debug(f"{instrument}: Price not at POI yet")
            return None

        entry, sl, tp1, tp2, tp3 = self._calculate_levels(
            direction, poi, poi_type, m30, daily
        )
        rr = self._calc_rr(entry, sl, tp3)

        if rr < self.settings.MIN_RR_RATIO:
            logger.debug(f"{instrument}: RR {rr:.1f} below minimum {self.settings.MIN_RR_RATIO}")
            return None

        # ── Confidence scoring ────────────────────────────────────────────
        session = self._current_session()
        confidence = self._score_confidence(
            daily=daily, h1=h1, m30=m30,
            structure=structure, poi_type=poi_type,
            session=session, direction=direction
        )

        if confidence < self.settings.MIN_CONFIDENCE:
            logger.debug(f"{instrument}: Confidence {confidence:.0f}% below threshold")
            return None

        # ── Build signal ──────────────────────────────────────────────────
        liq_type = self._liquidity_label(m30.sweep_direction)
        analysis_text = self._build_analysis(
            instrument, daily, h1, m30, structure, liq_type, poi_type, direction
        )
        signal_text = self._build_signal(
            instrument, direction, entry, sl, tp1, tp2, tp3, rr, confidence
        )

        return TradeSignal(
            instrument=instrument,
            direction=direction,
            entry=round(entry, self._price_dp(instrument)),
            stop_loss=round(sl, self._price_dp(instrument)),
            tp1=round(tp1, self._price_dp(instrument)),
            tp2=round(tp2, self._price_dp(instrument)),
            tp3=round(tp3, self._price_dp(instrument)),
            rr_ratio=round(rr, 1),
            confidence=round(confidence, 1),
            daily_bias=daily.bias,
            structure_type=structure,
            liquidity_type=liq_type,
            poi_type=poi_type,
            poi_high=poi.high if hasattr(poi, "high") else 0,
            poi_low=poi.low if hasattr(poi, "low") else 0,
            session=session,
            analysis_text=analysis_text,
            signal_text=signal_text,
        )

    # ── POI selection ──────────────────────────────────────────────────────

    def _best_poi(self, m30: SMCAnalysis, direction: str):
        """Return (poi_object, poi_type_str) for the best POI near price."""
        current = m30.current_price
        candidates = []

        # Order Blocks
        for ob in m30.order_blocks:
            if ob.direction == ("BULLISH" if direction == "BUY" else "BEARISH") and ob.valid:
                dist = abs(ob.mid - current) / current
                candidates.append((dist, ob, "Order Block"))

        # Breaker Blocks (OBs that have been swept — simplified: OB above price for sell, etc.)
        for ob in m30.order_blocks:
            opposite = "BEARISH" if direction == "BUY" else "BULLISH"
            if ob.direction == opposite and ob.valid:
                dist = abs(ob.mid - current) / current
                candidates.append((dist * 0.9, ob, "Breaker Block"))  # slight preference

        # FVGs
        for fvg in m30.fvgs:
            if fvg.direction == ("BULLISH" if direction == "BUY" else "BEARISH"):
                dist = abs(fvg.mid - current) / current
                candidates.append((dist, fvg, "Fair Value Gap"))

        if not candidates:
            return None, None

        candidates.sort(key=lambda x: x[0])
        _, best_poi, best_type = candidates[0]

        # Only use POI if price is within 0.5% of it
        if abs(best_poi.mid - current) / current > 0.005:
            return None, None

        return best_poi, best_type

    def _price_at_poi(self, price: float, poi, poi_type: str) -> bool:
        return poi.low <= price <= poi.high or abs(price - poi.mid) / price < 0.003

    # ── Level calculation ──────────────────────────────────────────────────

    def _calculate_levels(self, direction, poi, poi_type, m30, daily):
        entry = poi.mid
        atr   = self._atr_approx(m30)

        if direction == "BUY":
            sl  = poi.low - atr * 0.5
            tp1 = entry + (entry - sl) * 2
            tp2 = entry + (entry - sl) * 3.5
            tp3 = daily.swing_high if daily.swing_high > entry else entry + (entry - sl) * 5
        else:
            sl  = poi.high + atr * 0.5
            tp1 = entry - (sl - entry) * 2
            tp2 = entry - (sl - entry) * 3.5
            tp3 = daily.swing_low if daily.swing_low < entry else entry - (sl - entry) * 5

        return entry, sl, tp1, tp2, tp3

    def _atr_approx(self, analysis: SMCAnalysis) -> float:
        """Approximate ATR as a fraction of the swing range."""
        rng = analysis.swing_high - analysis.swing_low
        return rng * 0.02 if rng > 0 else analysis.current_price * 0.002

    def _calc_rr(self, entry: float, sl: float, tp3: float) -> float:
        risk   = abs(entry - sl)
        reward = abs(tp3 - entry)
        return reward / risk if risk > 0 else 0

    # ── Confidence scoring ─────────────────────────────────────────────────

    def _score_confidence(
        self, daily, h1, m30, structure, poi_type, session, direction
    ) -> float:
        score = 0.0

        # Daily bias aligned
        if daily.bias != "NEUTRAL":
            score += WEIGHTS["daily_bias_aligned"]

        # Structure confirmed
        if structure in ("BOS", "MSS"):
            score += WEIGHTS["structure_confirmed"] * (1.0 if structure == "BOS" else 0.8)

        # Liquidity swept
        if m30.liquidity_swept:
            swept_strength = max(
                (p.strength for p in m30.liquidity_pools if p.swept), default=0.5
            )
            score += WEIGHTS["liquidity_swept"] * swept_strength

        # OB quality
        best_ob_str = max(
            (ob.strength for ob in m30.order_blocks if ob.valid), default=0
        )
        score += WEIGHTS["ob_quality"] * best_ob_str

        # FVG present
        if m30.fvgs:
            score += WEIGHTS["fvg_present"]

        # Session timing
        if session in ("London", "New York"):
            score += WEIGHTS["session_timing"]
        elif session == "London/NY Overlap":
            score += WEIGHTS["session_timing"] * 1.2

        # Trend strength
        score += WEIGHTS["trend_strength"] * daily.trend_strength

        return min(100.0, score)

    # ── Text builders ──────────────────────────────────────────────────────

    def _build_analysis(
        self, instrument, daily, h1, m30, structure, liq_type, poi_type, direction
    ) -> str:
        bias_emoji = "🟢" if daily.bias == "BULLISH" else "🔴"
        return (
            f"📊 *MARKET ANALYSIS — {instrument}*\n"
            f"{'─' * 32}\n"
            f"{bias_emoji} *Daily Bias:* {daily.bias}\n"
            f"📐 *Structure:* 1H {structure} confirmed\n"
            f"💧 *Liquidity:* {liq_type}\n"
            f"🪤 *Inducement:* Retail traders trapped {'below support' if direction == 'BUY' else 'above resistance'}\n"
            f"🎯 *POI Identified:* {poi_type}\n"
            f"📍 *Price Zone:* {'Discount' if m30.in_discount else 'Premium'}\n"
            f"💪 *Trend Strength:* {int(daily.trend_strength * 100)}%\n"
            f"\n"
            f"*Conclusion:*\n"
            f"Smart money has {'swept sell-side liquidity and is likely to push price higher' if direction == 'BUY' else 'swept buy-side liquidity and is likely to push price lower'}. "
            f"Price is now returning to an institutional {poi_type} where a high-probability {direction} opportunity exists."
        )

    def _build_signal(
        self, instrument, direction, entry, sl, tp1, tp2, tp3, rr, confidence
    ) -> str:
        dir_emoji = "🟢 BUY" if direction == "BUY" else "🔴 SELL"
        stars = "⭐" * (5 if confidence >= 90 else 4 if confidence >= 80 else 3)
        return (
            f"💎 *VIP SIGNAL* {stars}\n"
            f"{'═' * 32}\n"
            f"📌 *Instrument:* `{instrument}`\n"
            f"📈 *Direction:* {dir_emoji}\n"
            f"{'─' * 32}\n"
            f"🎯 *Entry:* `{entry}`\n"
            f"🛑 *Stop Loss:* `{sl}`\n"
            f"{'─' * 32}\n"
            f"🥇 *TP1:* `{tp1}` _(partial close)_\n"
            f"🥈 *TP2:* `{tp2}` _(move SL to BE)_\n"
            f"🏆 *TP3:* `{tp3}` _(major target)_\n"
            f"{'─' * 32}\n"
            f"⚖️ *Risk:Reward:* `1:{rr}`\n"
            f"🧠 *Confidence:* `{confidence:.0f}%`\n"
            f"{'─' * 32}\n"
            f"⏰ `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`\n"
            f"_Follow risk management. Never risk more than 1-2% per trade._"
        )

    # ── Utilities ──────────────────────────────────────────────────────────

    def _current_session(self) -> str:
        hour = datetime.now(timezone.utc).hour
        s = self.settings
        in_london = s.LONDON_START <= hour < s.LONDON_END
        in_ny     = s.NY_START <= hour < s.NY_END
        if in_london and in_ny:
            return "London/NY Overlap"
        if in_london:
            return "London"
        if in_ny:
            return "New York"
        return "Off-Session"

    def _liquidity_label(self, sweep_dir: Optional[str]) -> str:
        if sweep_dir == "SSL":
            return "Sell-side liquidity swept ↓"
        if sweep_dir == "BSL":
            return "Buy-side liquidity swept ↑"
        return "Liquidity sweep detected"

    def _price_dp(self, instrument: str) -> int:
        """Decimal places for price display."""
        dp_map = {
            "BTCUSD": 0, "NAS100": 1, "US30": 0,
            "XAUUSD": 2, "GBPUSD": 5, "USDJPY": 3,
        }
        return dp_map.get(instrument, 2)
