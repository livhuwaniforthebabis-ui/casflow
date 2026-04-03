"""
Market Scanner
==============
Orchestrates scanning all instruments, running SMC analysis,
generating signals, monitoring open trades, and sending Telegram messages.
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from telegram import Bot
from telegram.constants import ParseMode

from config.settings import Settings
from data.database import Database, Signal
from data.fetcher import DataFetcher
from strategy.smc_engine import SMCEngine
from strategy.signal_generator import SignalGenerator, TradeSignal

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.fetcher = DataFetcher(settings)
        self.engine = SMCEngine()
        self.generator = SignalGenerator(settings)

    # ── Main scan ──────────────────────────────────────────────────────────

    async def scan_all_instruments(self) -> list[TradeSignal]:
        signals_today = self.db.get_signals_today()
        if signals_today >= self.settings.MAX_SIGNALS_PER_DAY:
            logger.info(f"Daily signal limit ({self.settings.MAX_SIGNALS_PER_DAY}) reached.")
            return []

        signals: list[TradeSignal] = []
        session = self._current_session()

        if session == "Off-Session":
            logger.info("Off-session — skipping scan.")
            return []

        for instrument in self.settings.INSTRUMENTS:
            try:
                sig = await self._scan_instrument(instrument)
                if sig:
                    signals.append(sig)
                    # Respect daily cap
                    if signals_today + len(signals) >= self.settings.MAX_SIGNALS_PER_DAY:
                        break
            except Exception as e:
                logger.error(f"Error scanning {instrument}: {e}")
            await asyncio.sleep(0.5)  # rate limit

        return signals

    async def _scan_instrument(self, instrument: str) -> Optional[TradeSignal]:
        analyses = {}
        for tf in self.settings.TIMEFRAMES:
            df = self.fetcher.get_ohlcv(instrument, tf)
            if df is not None:
                analyses[tf] = self.engine.analyse(df, instrument, tf)
        return self.generator.generate_signal(analyses, instrument)

    # ── Signal sending ─────────────────────────────────────────────────────

    async def send_signal(self, bot: Bot, signal: TradeSignal):
        channel = self.settings.VIP_CHANNEL_ID
        if not channel:
            logger.warning("VIP_CHANNEL_ID not set — cannot send signal.")
            return

        try:
            # 1. Send analysis first
            await bot.send_message(
                chat_id=channel,
                text=signal.analysis_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(2)

            # 2. Send signal
            msg = await bot.send_message(
                chat_id=channel,
                text=signal.signal_text,
                parse_mode=ParseMode.MARKDOWN,
            )

            # 3. Save to DB
            self.db.save_signal({
                "instrument":    signal.instrument,
                "direction":     signal.direction,
                "entry":         signal.entry,
                "stop_loss":     signal.stop_loss,
                "tp1":           signal.tp1,
                "tp2":           signal.tp2,
                "tp3":           signal.tp3,
                "rr_ratio":      signal.rr_ratio,
                "confidence":    signal.confidence,
                "daily_bias":    signal.daily_bias,
                "structure_type":signal.structure_type,
                "liquidity_type":signal.liquidity_type,
                "poi_type":      signal.poi_type,
                "session":       signal.session,
                "status":        "ACTIVE",
                "telegram_message_id": msg.message_id,
            })

            logger.info(f"Signal sent: {signal.instrument} {signal.direction} @ {signal.entry}")

        except Exception as e:
            logger.error(f"Failed to send signal: {e}")

    # ── Trade monitoring ───────────────────────────────────────────────────

    async def monitor_active_trades(self, bot: Bot):
        """Check active trades against current prices and send updates."""
        active = self.db.get_active_signals()
        channel = self.settings.VIP_CHANNEL_ID

        for trade in active:
            price = self.fetcher.get_current_price(trade.instrument)
            if price is None:
                continue

            update_msg = self._check_trade_update(trade, price)
            if update_msg:
                try:
                    await bot.send_message(
                        chat_id=channel,
                        text=update_msg,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception as e:
                    logger.error(f"Failed to send trade update: {e}")

    def _check_trade_update(self, trade: Signal, price: float) -> Optional[str]:
        direction = trade.direction
        status    = None
        msg       = None

        if direction == "BUY":
            if price >= trade.tp3:
                status = "TP3"
                msg    = self._update_msg(trade, "TP3 HIT 🏆", "Full profit secured!")
            elif price >= trade.tp2:
                status = "TP2"
                msg    = self._update_msg(trade, "TP2 HIT 🥈", "Move SL to TP1. Riding to TP3.")
            elif price >= trade.tp1:
                status = "TP1"
                msg    = self._update_msg(trade, "TP1 HIT 🥇", "Partial profits secured. Move SL to breakeven.")
            elif price <= trade.stop_loss:
                status = "SL"
                msg    = self._update_msg(trade, "STOP LOSS HIT 🛑", "Trade closed. Risk managed. Next opportunity soon.")

        else:  # SELL
            if price <= trade.tp3:
                status = "TP3"
                msg    = self._update_msg(trade, "TP3 HIT 🏆", "Full profit secured!")
            elif price <= trade.tp2:
                status = "TP2"
                msg    = self._update_msg(trade, "TP2 HIT 🥈", "Move SL to TP1. Riding to TP3.")
            elif price <= trade.tp1:
                status = "TP1"
                msg    = self._update_msg(trade, "TP1 HIT 🥇", "Partial profits secured. Move SL to breakeven.")
            elif price >= trade.stop_loss:
                status = "SL"
                msg    = self._update_msg(trade, "STOP LOSS HIT 🛑", "Trade closed. Risk managed.")

        if status and status != trade.status:
            self.db.update_signal_status(
                trade.id, status,
                closed_at=datetime.now(timezone.utc) if status in ("TP3","SL") else None
            )
            return msg

        return None

    def _update_msg(self, trade: Signal, headline: str, advice: str) -> str:
        dir_emoji = "🟢" if trade.direction == "BUY" else "🔴"
        return (
            f"🔔 *TRADE UPDATE*\n"
            f"{'─' * 28}\n"
            f"{dir_emoji} *{trade.instrument} {trade.direction}*\n\n"
            f"*{headline}*\n"
            f"_{advice}_\n"
            f"{'─' * 28}\n"
            f"Entry: `{trade.entry}` | SL: `{trade.stop_loss}`\n"
            f"TP1: `{trade.tp1}` | TP2: `{trade.tp2}` | TP3: `{trade.tp3}`"
        )

    def _current_session(self) -> str:
        hour = datetime.now(timezone.utc).hour
        s = self.settings
        if s.LONDON_START <= hour < s.LONDON_END and s.NY_START <= hour < s.NY_END:
            return "London/NY Overlap"
        if s.LONDON_START <= hour < s.LONDON_END:
            return "London"
        if s.NY_START <= hour < s.NY_END:
            return "New York"
        return "Off-Session"
