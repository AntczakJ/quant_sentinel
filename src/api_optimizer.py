"""
src/api_optimizer.py - Professional API Rate Limiter for Twelve Data
Spec: 55 credits/min limit, Leaky Bucket algorithm, Batch requests, Exponential backoff
"""

import time
import asyncio
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from threading import Lock
import math

logger = logging.getLogger(__name__)

class CreditWeights:
    """Define credit costs for different Twelve Data endpoints"""
    PRICE = 1  # /price endpoint
    TIME_SERIES = 1  # /time_series endpoint (per symbol)
    INCOME_STATEMENT = 100  # /income_statement (DANGEROUS - avoid!)
    BALANCE_SHEET = 100  # /balance_sheet (DANGEROUS - avoid!)
    CASH_FLOW = 100  # /cash_flow (DANGEROUS - avoid!)
    QUOTE = 1  # /quote endpoint
    
    @staticmethod
    def get_cost(endpoint: str) -> int:
        """Get credit cost for endpoint"""
        costs = {
            'price': CreditWeights.PRICE,
            'time_series': CreditWeights.TIME_SERIES,
            'income_statement': CreditWeights.INCOME_STATEMENT,
            'balance_sheet': CreditWeights.BALANCE_SHEET,
            'cash_flow': CreditWeights.CASH_FLOW,
            'quote': CreditWeights.QUOTE,
        }
        return costs.get(endpoint, 1)


class RateLimiter:
    """
    Professional Rate Limiter using Leaky Bucket algorithm
    - Hard limit: 55 credits/minute
    - Safe margin: 52 credits/minute (operational limit)
    - Bucket refills every 60 seconds
    """
    
    def __init__(self, credits_per_minute: int = 55, safe_margin: int = 52):
        """
        Initialize rate limiter
        
        Args:
            credits_per_minute: Hard limit from Twelve Data (55 for Grow plan)
            safe_margin: Operational limit to leave buffer (52 to be safe)
        """
        self.max_credits = credits_per_minute
        self.safe_credits = safe_margin
        self.current_credits = safe_margin
        self.last_refill = time.time()
        self.lock = Lock()
        self.requests_made = []  # For analytics
        
        logger.info(f"🔧 RateLimiter initialized: {credits_per_minute} credits/min, safe margin: {safe_margin}")
    
    def _refill_bucket(self):
        """Refill bucket based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        
        if elapsed >= 60:
            # Full minute passed - reset to safe limit
            self.current_credits = self.safe_credits
            self.last_refill = now
            logger.debug(f"🔄 Bucket refilled: {self.current_credits} credits available")
        else:
            # Partial refill (linear interpolation)
            refill_rate = self.max_credits / 60  # Credits per second
            refill_amount = refill_rate * elapsed
            old_credits = self.current_credits
            self.current_credits = min(self.safe_credits, self.current_credits + refill_amount)
            
            if int(self.current_credits) > int(old_credits):
                logger.debug(f"⬆️ Partial refill: {int(old_credits)} → {int(self.current_credits)} credits")
    
    def can_use_credits(self, credits_needed: int) -> Tuple[bool, float]:
        """
        Check if we can use requested credits
        
        Returns:
            (can_use, wait_time_seconds)
        """
        with self.lock:
            self._refill_bucket()
            
            if self.current_credits >= credits_needed:
                return True, 0.0
            
            # Calculate wait time needed
            credits_deficit = credits_needed - self.current_credits
            refill_rate = self.max_credits / 60
            wait_time = credits_deficit / refill_rate
            
            return False, wait_time
    
    def use_credits(self, credits_needed: int, endpoint: str = "", symbol: str = "") -> bool:
        """
        Try to use credits
        
        Args:
            credits_needed: Number of credits to consume
            endpoint: API endpoint (for logging)
            symbol: Stock symbol (for logging)
        
        Returns:
            True if successful, False if rate limited
        """
        with self.lock:
            self._refill_bucket()
            
            if self.current_credits >= credits_needed:
                self.current_credits -= credits_needed
                self.requests_made.append({
                    'timestamp': datetime.now(),
                    'endpoint': endpoint,
                    'symbol': symbol,
                    'credits': credits_needed
                })
                
                logger.info(
                    f"✅ Used {credits_needed} credits | "
                    f"Remaining: {int(self.current_credits)}/{self.safe_credits} | "
                    f"Endpoint: {endpoint} | Symbol: {symbol}"
                )
                return True
            else:
                credits_deficit = credits_needed - self.current_credits
                wait_time = (credits_deficit / (self.max_credits / 60))
                logger.warning(
                    f"⛔ Rate limited! Need {credits_needed}, have {int(self.current_credits)} | "
                    f"Wait {wait_time:.1f}s | Endpoint: {endpoint}"
                )
                return False
    
    def wait_for_credits(self, credits_needed: int, max_wait_seconds: int = 65) -> bool:
        """
        Wait until we have enough credits
        
        Args:
            credits_needed: Credits needed
            max_wait_seconds: Maximum time to wait (default 65s for next minute)
        
        Returns:
            True if credits available, False if timeout
        """
        start_time = time.time()
        
        while time.time() - start_time < max_wait_seconds:
            can_use, wait_time = self.can_use_credits(credits_needed)
            if can_use:
                return True
            
            # Sleep for a bit (don't busy-wait)
            sleep_time = min(wait_time + 0.5, 5.0)  # Max 5 second waits
            logger.debug(f"⏳ Waiting {sleep_time:.1f}s for {credits_needed} credits...")
            time.sleep(sleep_time)
        
        logger.error(f"❌ Timeout waiting for {credits_needed} credits after {max_wait_seconds}s")
        return False
    
    def validate_endpoint_cost(self, endpoint: str, num_symbols: int = 1) -> Tuple[bool, int, Optional[str]]:
        """
        Validate if endpoint is affordable with current plan
        
        Returns:
            (is_affordable, cost, error_message)
        """
        unit_cost = CreditWeights.get_cost(endpoint)
        total_cost = unit_cost * num_symbols
        
        # Check for expensive endpoints
        if unit_cost >= 100:
            error_msg = (
                f"❌ Endpoint '{endpoint}' costs {unit_cost} credits/symbol! "
                f"Your plan limit is {self.max_credits}/min. "
                f"This endpoint would use {total_cost} credits for {num_symbols} symbols. "
                f"NOT ALLOWED with your current plan."
            )
            logger.error(error_msg)
            return False, total_cost, error_msg
        
        if total_cost > self.max_credits:
            error_msg = (
                f"⚠️ Endpoint '{endpoint}' would cost {total_cost} credits for {num_symbols} symbols, "
                f"but your limit is {self.max_credits}/min. Consider batching."
            )
            logger.warning(error_msg)
            return False, total_cost, error_msg
        
        return True, total_cost, None
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics"""
        with self.lock:
            self._refill_bucket()
            
            # Calculate recent activity
            now = datetime.now()
            one_min_ago = now - timedelta(minutes=1)
            recent_requests = [r for r in self.requests_made if r['timestamp'] > one_min_ago]
            recent_credits = sum(r['credits'] for r in recent_requests)
            
            return {
                'current_credits': int(self.current_credits),
                'safe_limit': self.safe_credits,
                'max_limit': self.max_credits,
                'credits_used_last_min': recent_credits,
                'recent_requests': len(recent_requests),
                'last_refill': self.last_refill,
                'all_requests_count': len(self.requests_made),
            }


class BatchRequestGrouper:
    """
    Groups multiple API requests into batch requests
    Reduces HTTP overhead and helps manage credits
    """
    
    def __init__(self, max_symbols_per_batch: int = 10):
        """
        Initialize grouper
        
        Args:
            max_symbols_per_batch: Max symbols per single batch request
        """
        self.max_symbols_per_batch = max_symbols_per_batch
        logger.info(f"🔗 BatchRequestGrouper initialized: max {max_symbols_per_batch} symbols/batch")
    
    def group_symbols(self, symbols: List[str]) -> List[List[str]]:
        """
        Group symbols into batches
        
        Args:
            symbols: List of symbols to group
        
        Returns:
            List of symbol batches
        """
        batches = []
        for i in range(0, len(symbols), self.max_symbols_per_batch):
            batch = symbols[i:i + self.max_symbols_per_batch]
            batches.append(batch)
        
        logger.debug(f"📦 Grouped {len(symbols)} symbols into {len(batches)} batches")
        return batches
    
    def create_batch_url(self, endpoint: str, symbols: List[str], base_url: str = "https://api.twelvedata.com") -> str:
        """
        Create batch request URL with comma-separated symbols
        
        Args:
            endpoint: API endpoint
            symbols: List of symbols
            base_url: Base URL
        
        Returns:
            Batch request URL
        """
        symbol_str = ",".join(symbols)
        url = f"{base_url}/{endpoint}?symbol={symbol_str}"
        return url


class ExponentialBackoff:
    """
    Exponential backoff strategy for handling 429 errors
    """
    
    def __init__(self, base_delay: float = 1.0, max_delay: float = 65.0, max_retries: int = 5):
        """
        Initialize backoff strategy
        
        Args:
            base_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            max_retries: Maximum number of retry attempts
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        logger.info(f"🔄 ExponentialBackoff initialized: base {base_delay}s, max {max_delay}s, {max_retries} retries")
    
    def get_wait_time(self, attempt: int) -> float:
        """
        Calculate wait time for given attempt
        
        Args:
            attempt: Attempt number (0-indexed)
        
        Returns:
            Wait time in seconds
        """
        # Exponential: base_delay * 2^attempt + jitter
        delay = self.base_delay * (2 ** attempt)
        delay = min(delay, self.max_delay)
        
        # Add small random jitter to prevent thundering herd
        import random
        jitter = random.uniform(0, 0.1 * delay)
        delay += jitter
        
        return delay
    
    async def wait_and_retry(self, attempt: int, callback, *args, **kwargs):
        """
        Wait and retry a callback with exponential backoff
        
        Args:
            attempt: Attempt number
            callback: Async function to retry
            *args, **kwargs: Arguments for callback
        
        Returns:
            Result of callback or None if all retries exhausted
        """
        if attempt >= self.max_retries:
            logger.error(f"❌ Max retries ({self.max_retries}) exhausted")
            return None
        
        wait_time = self.get_wait_time(attempt)
        logger.warning(f"⏳ Exponential backoff: waiting {wait_time:.1f}s before retry (attempt {attempt + 1}/{self.max_retries})")
        
        await asyncio.sleep(wait_time)
        
        try:
            result = await callback(*args, **kwargs)
            logger.info(f"✅ Retry successful on attempt {attempt + 1}")
            return result
        except Exception as e:
            logger.error(f"❌ Retry failed: {e}")
            return await self.wait_and_retry(attempt + 1, callback, *args, **kwargs)


# Global rate limiter instance
global_rate_limiter = RateLimiter(credits_per_minute=55, safe_margin=52)
global_batch_grouper = BatchRequestGrouper(max_symbols_per_batch=10)
global_backoff = ExponentialBackoff(base_delay=1.0, max_delay=65.0, max_retries=5)


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter"""
    return global_rate_limiter


def get_batch_grouper() -> BatchRequestGrouper:
    """Get global batch grouper"""
    return global_batch_grouper


def get_backoff() -> ExponentialBackoff:
    """Get global exponential backoff"""
    return global_backoff

