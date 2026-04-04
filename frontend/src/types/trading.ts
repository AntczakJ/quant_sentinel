/**
 * src/types/trading.ts - Trading-related TypeScript types
 */

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Ticker {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  timestamp: string;
  high_24h?: number;
  low_24h?: number;
}

export interface Indicators {
  symbol: string;
  rsi?: number;
  macd?: number;
  macd_signal?: number;
  macd_histogram?: number;
  bb_upper?: number;
  bb_middle?: number;
  bb_lower?: number;
  timestamp: string;
}

export interface Signal {
  timestamp: string;
  symbol: string;

  // Individual models
  rl_action: 'BUY' | 'SELL' | 'HOLD';
  rl_confidence: number;
  rl_epsilon: number;

  lstm_prediction: number;
  lstm_change_pct: number;

  xgb_direction: 'UP' | 'DOWN' | 'NEUTRAL';
  xgb_probability: number;

  // Consensus
  consensus: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL';
  consensus_score: number;

  // Market data
  current_price: number;
  current_rsi?: number;

  signal_id?: string;
}

export interface Portfolio {
  balance: number;
  initial_balance: number;
  equity: number;
  pnl: number;
  pnl_pct: number;
  has_position: boolean;
  position_type?: 'LONG' | 'SHORT';
  position_entry?: number;
  position_unrealized_pnl?: number;
  timestamp: string;
}

export interface ModelStats {
  model_name: string;
  accuracy?: number;
  precision?: number;
  recall?: number;
  win_rate?: number;
  episodes?: number;
  epsilon?: number;
  last_training?: string;
}

export interface AllModelsStats {
  rl_stats: ModelStats;
  lstm_stats: ModelStats;
  xgb_stats: ModelStats;
  ensemble_accuracy?: number;
  last_update: string;
}

export interface TrainingStatus {
  is_training: boolean;
  current_episode?: number;
  total_episodes?: number;
  progress_pct?: number;
  last_reward?: number;
  avg_reward?: number;
  started_at?: string;
  eta_seconds?: number;
}

export interface WebSocketMessage {
  type: 'price_update' | 'signal_update' | 'ping';
  data?: any;
  timestamp?: string;
}

