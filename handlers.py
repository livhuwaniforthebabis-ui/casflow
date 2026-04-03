"""
Telegram command handlers.
"""
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Lazy imports — resolved at runtime to avoid circular deps
def _get_settings():
    from bot.main import settings
    return settings

def _get_db():
    from bot.main import db
    return db

def _get_scanner():
    from bot.main import scanner
    return scanner

def _is_admin(user_id: int) -> bool:
    return user_id in _get_settings().ADMIN_IDS


# ── Public handlers ────────────────────────────────────────────────────────────

async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👑 *Welcome to the SMC VIP Trading Signal Bot*\n\n"
        "This bot delivers institutional-grade trading signals using *Smart Money Concepts*.\n\n"
        "*Available Commands:*\n"
        "• /dashboard — Live dashboard\n"
        "• /signals — Recent signals\n"
        "• /performance — Win rate & stats\n"
        "• /bias — Current market bias per instrument\n"
        "• /help — Help & documentation\n\n"
        "_Signals are sent automatically when high-probability setups are detected._"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *SMC VIP Bot — Help*\n\n"
        "*Strategy Overview:*\n"
        "• Top-down multi-timeframe analysis (Daily → 4H → 1H → 30M)\n"
        "• Smart Money Concepts: BOS, MSS, OB, FVG, Liquidity\n"
        "• Minimum 70% confidence required to send signal\n"
        "• Maximum 3-5 signals per day (quality over quantity)\n\n"
        "*Signal Format:*\n"
        "• Entry, SL, TP1/TP2/TP3\n"
        "• Risk-Reward minimum 1:3 (preferred 1:5+)\n"
        "• Confidence score 0-100%\n\n"
        "*Sessions Traded:*\n"
        "• London (07:00-16:00 UTC)\n"
        "• New York (13:00-22:00 UTC)\n\n"
        "*Instruments:*\n"
        "XAUUSD • BTCUSD • GBPUSD • USDJPY • NAS100 • US30"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def dashboard_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = _get_db()
    stats = db.get_performance_stats()
    active = db.get_active_signals()
    biases = db.get_latest_biases()

    bias_lines = ""
    for b in biases:
        emoji = "🟢" if b.bias == "BULLISH" else "🔴" if b.bias == "BEARISH" else "⚪"
        bias_lines += f"{emoji} {b.instrument}: *{b.bias}*\n"

    active_lines = ""
    for t in active[:5]:
        dir_e = "🟢" if t.direction == "BUY" else "🔴"
        active_lines += f"{dir_e} {t.instrument} {t.direction} @ `{t.entry}` | Conf: {t.confidence:.0f}%\n"

    text = (
        f"📊 *VIP DASHBOARD*\n"
        f"{'═' * 30}\n"
        f"*Performance*\n"
        f"Total Signals: `{stats['total_signals']}`\n"
        f"Wins: `{stats['wins']}` | Losses: `{stats['losses']}`\n"
        f"Win Rate: `{stats['win_rate']}%`\n"
        f"Avg Confidence: `{stats['avg_confidence']}%`\n\n"
        f"*Market Bias*\n"
        f"{bias_lines or 'No bias data yet.'}\n"
        f"*Active Trades ({len(active)})*\n"
        f"{active_lines or 'No active trades.'}\n"
        f"{'─' * 30}\n"
        f"_Updated: {datetime.now(timezone.utc).strftime('%H:%M UTC')}_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def signals_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = _get_db()
    recent = db.get_recent_signals(limit=5)

    if not recent:
        await update.message.reply_text("No signals yet.")
        return

    lines = []
    for s in recent:
        status_emoji = {
            "ACTIVE": "🔄", "TP1": "🥇", "TP2": "🥈",
            "TP3": "🏆", "SL": "🛑", "CLOSED": "✅"
        }.get(s.status, "❓")
        dir_e = "🟢" if s.direction == "BUY" else "🔴"
        lines.append(
            f"{status_emoji} {dir_e} *{s.instrument}* {s.direction} | "
            f"Entry `{s.entry}` | Conf `{s.confidence:.0f}%` | {s.status}"
        )

    text = "📋 *Recent Signals*\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def performance_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = _get_db()
    stats = db.get_performance_stats()

    bars = int(stats["win_rate"] / 10)
    bar  = "█" * bars + "░" * (10 - bars)

    text = (
        f"📈 *PERFORMANCE STATISTICS*\n"
        f"{'═' * 30}\n"
        f"Total Signals: `{stats['total_signals']}`\n"
        f"Wins: `{stats['wins']}` ✅\n"
        f"Losses: `{stats['losses']}` ❌\n\n"
        f"Win Rate: `{stats['win_rate']}%`\n"
        f"`[{bar}]`\n\n"
        f"Avg Confidence: `{stats['avg_confidence']}%`\n"
        f"Min RR: `1:{_get_settings().MIN_RR_RATIO}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def bias_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = _get_db()
    biases = db.get_latest_biases()

    if not biases:
        await update.message.reply_text("No bias data available yet. Run /force_scan first.")
        return

    lines = []
    for b in biases:
        emoji = "🟢" if b.bias == "BULLISH" else "🔴" if b.bias == "BEARISH" else "⚪"
        target = f"`{b.next_liquidity_target}`" if b.next_liquidity_target else "scanning..."
        lines.append(f"{emoji} *{b.instrument}*: {b.bias} | Next target: {target}")

    text = "🧭 *MARKET BIAS*\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── Admin handlers ─────────────────────────────────────────────────────────────

async def force_scan_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text("🔄 Forcing market scan...")
    scanner = _get_scanner()
    signals = await scanner.scan_all_instruments()
    for sig in signals:
        await scanner.send_signal(ctx.bot, sig)
    await update.message.reply_text(f"✅ Scan complete. {len(signals)} signal(s) generated.")


async def manual_signal_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text(
        "📝 *Manual Signal*\n\nUse format:\n"
        "`/manual_signal XAUUSD BUY 2324.50 2317.20 2331.00 2340.50 2355.00 86`\n"
        "(instrument direction entry sl tp1 tp2 tp3 confidence)",
        parse_mode=ParseMode.MARKDOWN
    )


async def pause_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    _get_settings().PAUSED = True
    await update.message.reply_text("⏸ Bot paused. No new scans will run.")


async def resume_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    _get_settings().PAUSED = False
    await update.message.reply_text("▶️ Bot resumed.")


async def button_callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "dashboard":
        await dashboard_handler(update, ctx)
    elif data == "signals":
        await signals_handler(update, ctx)
    elif data == "performance":
        await performance_handler(update, ctx)
