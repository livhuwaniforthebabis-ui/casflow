"""
Configuration and environment variable management.
"""
import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class Settings:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    VIP_CHANNEL_ID: str = os.getenv("VIP_CHANNEL_ID", "")
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ])

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///smc_bot.db")

    # APIs
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET: str = os.getenv("BINANCE_SECRET", "")
    ALPHA_VANTAGE_KEY: str = os.getenv("ALPHA_VANTAGE_KEY", "")
    TWELVE_DATA_KEY: str = os.getenv("TWELVE_DATA_KEY", "")

    # Strategy settings
    MIN_CONFIDENCE: float = float(os.getenv("MIN_CONFIDENCE", "70"))
    MAX_SIGNALS_PER_DAY: int = int(os.getenv("MAX_SIGNALS_PER_DAY", "5"))
    MIN_RR_RATIO: float = float(os.getenv("MIN_RR_RATIO", "3.0"))
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))  # 5 min

    # Bot state
    PAUSED: bool = False

    # Instruments
    INSTRUMENTS: List[str] = field(default_factory=lambda: [
        "XAUUSD", "BTCUSD", "GBPUSD", "USDJPY", "NAS100", "US30"
    ])

    # Session times (UTC)
    LONDON_START: int = 7    # 07:00 UTC
    LONDON_END: int = 16     # 16:00 UTC
    NY_START: int = 13       # 13:00 UTC
    NY_END: int = 22         # 22:00 UTC

    # Timeframes used in analysis
    TIMEFRAMES: List[str] = field(default_factory=lambda: [
        "1D", "4H", "1H", "30min"
    ])
