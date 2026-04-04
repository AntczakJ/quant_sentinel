"""
api/schemas/models.py - Pydantic data models and schemas
"""

from datetime import datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, Field

# ============================================================================
# Market Data Schemas
# ============================================================================

class Candle(BaseModel):
    """Single OHLCV candle"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

class CandleResponse(BaseModel):
    """Response containing candles"""
    symbol: str
    interval: str
    candles: List[Candle]
    limit: int

class TickerResponse(BaseModel):
    """Live ticker data"""
    symbol: str
    price: float = Field(..., description="Current price")
    change: float = Field(..., description="Price change in USD")
    change_pct: float = Field(..., description="Price change in percentage")
    timestamp: datetime
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None

class IndicatorResponse(BaseModel):
    """Technical indicators"""
    symbol: str
    rsi: Optional[float] = Field(None, description="Relative Strength Index (14)")
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bb_upper: Optional[float] = Field(None, description="Bollinger Band Upper")
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    timestamp: datetime

# ============================================================================
# Trading Signal Schemas
# ============================================================================

class SignalResponse(BaseModel):
    """Combined signal from all three models"""
    timestamp: datetime
    symbol: str

    # Individual model predictions
    rl_action: Literal["BUY", "SELL", "HOLD"]
    rl_confidence: float = Field(..., ge=0.0, le=1.0, description="RL model confidence 0-1")
    rl_epsilon: float = Field(..., description="Current epsilon (randomness)")

    lstm_prediction: float = Field(..., description="LSTM predicted next price")
    lstm_change_pct: float = Field(..., description="Predicted price change %")

    xgb_direction: Literal["UP", "DOWN", "NEUTRAL"]
    xgb_probability: float = Field(..., ge=0.0, le=1.0)

    # Consensus
    consensus: Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
    consensus_score: float = Field(..., ge=0.0, le=1.0)

    # Market data
    current_price: float
    current_rsi: Optional[float] = None

    # History
    signal_id: Optional[str] = None

class SignalHistoryItem(BaseModel):
    """Historical signal"""
    signal_id: Optional[str] = None
    timestamp: datetime
    direction: Optional[str] = None  # LONG/SHORT
    entry_price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    rsi: Optional[float] = None
    structure: Optional[str] = None
    # Legacy fields for backwards compatibility
    price: Optional[float] = None
    action: Optional[str] = None
    confidence: Optional[float] = None
    result: Optional[Literal["WIN", "LOSS", "BREAKEVEN"]] = None

# ============================================================================
# Portfolio Schemas
# ============================================================================

class PortfolioStatus(BaseModel):
    """Current portfolio status"""
    balance: float = Field(..., description="Current balance in PLN")
    initial_balance: float = Field(..., description="Initial balance in PLN")
    equity: float = Field(..., description="Current equity in PLN")
    pnl: float = Field(..., description="Profit/Loss in PLN")
    pnl_pct: float = Field(..., description="Profit/Loss %")
    currency: str = Field(default="PLN", description="Currency of balance")

    # Position info
    has_position: bool
    position_type: Optional[Literal["LONG", "SHORT"]] = None
    position_entry: Optional[float] = None  # In USD (gold price)
    position_unrealized_pnl: Optional[float] = None

    timestamp: datetime

class PortfolioHistory(BaseModel):
    """Portfolio equity history"""
    timestamps: List[datetime]
    equity_values: List[float]
    pnl_values: List[float]

# ============================================================================
# Model Stats Schemas
# ============================================================================

class ModelStats(BaseModel):
    """Statistics for a single ML model"""
    model_name: str
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    win_rate: Optional[float] = None

    # For RL Agent
    episodes: Optional[int] = None
    epsilon: Optional[float] = None
    last_training: Optional[datetime] = None

class AllModelsStats(BaseModel):
    """Combined stats for all models"""
    rl_stats: ModelStats
    lstm_stats: ModelStats
    xgb_stats: ModelStats
    ensemble_accuracy: Optional[float] = None
    last_update: datetime

# ============================================================================
# Training Schemas
# ============================================================================

class TrainingStartRequest(BaseModel):
    """Request to start training"""
    episodes: int = Field(default=100, ge=1, le=10000)
    save_model: bool = Field(default=True)

class TrainingStatus(BaseModel):
    """Training status"""
    is_training: bool
    current_episode: Optional[int] = None
    total_episodes: Optional[int] = None
    progress_pct: Optional[float] = None
    last_reward: Optional[float] = None
    avg_reward: Optional[float] = None
    started_at: Optional[datetime] = None
    eta_seconds: Optional[int] = None

# ============================================================================
# WebSocket Message Schemas
# ============================================================================

class PriceUpdateMessage(BaseModel):
    """WebSocket price update message"""
    type: Literal["price_update"]
    symbol: str
    price: float
    change: float
    change_pct: float
    timestamp: datetime

class SignalUpdateMessage(BaseModel):
    """WebSocket signal update message"""
    type: Literal["signal_update"]
    signal: SignalResponse
    timestamp: datetime

# ============================================================================
# Error Response
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

