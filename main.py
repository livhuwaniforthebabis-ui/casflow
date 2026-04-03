"""
SMC VIP Trading Signal Bot - Main Entry Point
"""
import asyncio
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from config.settings import Settings
from bot.handlers import (
    start_handler, dashboard_handler, signals_handler,
    performance_handler, bias_handler, help_handler,
    force_scan_handler, manual_signal_handler, pause_handler, resume_handler,
    button_callback_handler
)
from strategy.scanner import MarketScanner
from data.database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

settings = Settings()
db = Database(settings.DATABASE_URL)
scanner = MarketScanner(settings, db)

async def run_scanner(app: Application):
    """Background task: scan markets every N minutes."""
    while True:
        try:
            if not settings.PAUSED:
                logger.info("Running market scan...")
                signals = await scanner.scan_all_instruments()
                for signal in signals:
                    await scanner.send_signal(app.bot, signal)
        except Exception as e:
            logger.error(f"Scanner error: {e}")
        await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

async def post_init(app: Application):
    """Start background scanner after bot initialises."""
    asyncio.create_task(run_scanner(app))

def main():
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Public commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("dashboard", dashboard_handler))
    app.add_handler(CommandHandler("signals", signals_handler))
    app.add_handler(CommandHandler("performance", performance_handler))
    app.add_handler(CommandHandler("bias", bias_handler))
    app.add_handler(CommandHandler("help", help_handler))

    # Admin commands
    app.add_handler(CommandHandler("force_scan", force_scan_handler))
    app.add_handler(CommandHandler("manual_signal", manual_signal_handler))
    app.add_handler(CommandHandler("pause", pause_handler))
    app.add_handler(CommandHandler("resume", resume_handler))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(button_callback_handler))

    logger.info("🚀 SMC VIP Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
