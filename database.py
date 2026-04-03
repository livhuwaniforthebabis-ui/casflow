"""
Database layer using SQLAlchemy (supports SQLite + PostgreSQL).
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Boolean, Text, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)
Base = declarative_base()


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)   # BUY / SELL
    entry = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    tp1 = Column(Float, nullable=False)
    tp2 = Column(Float, nullable=False)
    tp3 = Column(Float, nullable=False)
    rr_ratio = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)

    # Analysis metadata
    daily_bias = Column(String(20))
    structure_type = Column(String(20))    # BOS / MSS
    liquidity_type = Column(String(50))
    poi_type = Column(String(30))          # OB / BB / FVG
    session = Column(String(20))           # London / NY

    # Lifecycle
    status = Column(String(20), default="ACTIVE")  # ACTIVE/TP1/TP2/TP3/SL/CLOSED
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    telegram_message_id = Column(Integer, nullable=True)

    # Result tracking
    result_pips = Column(Float, nullable=True)
    won = Column(Boolean, nullable=True)


class BiasHistory(Base):
    __tablename__ = "bias_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument = Column(String(20), nullable=False)
    bias = Column(String(20), nullable=False)    # BULLISH / BEARISH / NEUTRAL
    daily_high = Column(Float, nullable=True)
    daily_low = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    next_liquidity_target = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instruments_scanned = Column(Integer, default=0)
    signals_generated = Column(Integer, default=0)
    signals_sent = Column(Integer, default=0)
    scan_duration_ms = Column(Integer, nullable=True)
    scanned_at = Column(DateTime, default=datetime.utcnow)


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if "sqlite" in url else {}
        self.engine = create_engine(url, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        logger.info("Database initialised.")

    @contextmanager
    def session(self) -> Session:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ── Signal operations ──────────────────────────────────────────────────

    def save_signal(self, signal_data: dict) -> Signal:
        with self.session() as s:
            sig = Signal(**signal_data)
            s.add(sig)
            s.flush()
            s.refresh(sig)
            return sig

    def get_active_signals(self) -> list[Signal]:
        with self.session() as s:
            return s.query(Signal).filter(Signal.status == "ACTIVE").all()

    def update_signal_status(self, signal_id: int, status: str, closed_at=None):
        with self.session() as s:
            sig = s.query(Signal).filter(Signal.id == signal_id).first()
            if sig:
                sig.status = status
                if closed_at:
                    sig.closed_at = closed_at
                    sig.won = status in ("TP1", "TP2", "TP3")

    def get_signals_today(self) -> int:
        from sqlalchemy import func
        today = datetime.utcnow().date()
        with self.session() as s:
            return s.query(func.count(Signal.id)).filter(
                func.date(Signal.created_at) == today
            ).scalar() or 0

    def get_performance_stats(self) -> dict:
        with self.session() as s:
            total = s.query(Signal).filter(Signal.status != "ACTIVE").count()
            won = s.query(Signal).filter(Signal.won == True).count()
            win_rate = (won / total * 100) if total > 0 else 0
            avg_conf = s.query(Signal).with_entities(
                Signal.confidence
            ).all()
            avg_confidence = sum(r[0] for r in avg_conf) / len(avg_conf) if avg_conf else 0
            return {
                "total_signals": total,
                "wins": won,
                "losses": total - won,
                "win_rate": round(win_rate, 1),
                "avg_confidence": round(avg_confidence, 1),
            }

    def get_recent_signals(self, limit: int = 10) -> list[Signal]:
        with self.session() as s:
            return (
                s.query(Signal)
                .order_by(Signal.created_at.desc())
                .limit(limit)
                .all()
            )

    # ── Bias operations ────────────────────────────────────────────────────

    def save_bias(self, bias_data: dict):
        with self.session() as s:
            b = BiasHistory(**bias_data)
            s.add(b)

    def get_latest_biases(self) -> list[BiasHistory]:
        """Return the most recent bias record per instrument."""
        with self.session() as s:
            from sqlalchemy import func
            subq = (
                s.query(
                    BiasHistory.instrument,
                    func.max(BiasHistory.recorded_at).label("max_ts")
                ).group_by(BiasHistory.instrument).subquery()
            )
            return (
                s.query(BiasHistory)
                .join(subq, (BiasHistory.instrument == subq.c.instrument) &
                      (BiasHistory.recorded_at == subq.c.max_ts))
                .all()
            )

    # ── Scan log ───────────────────────────────────────────────────────────

    def log_scan(self, data: dict):
        with self.session() as s:
            s.add(ScanLog(**data))
