"""
src/auth.py — User Authentication & Authorization

Provides:
  - User registration with bcrypt-hashed passwords
  - JWT token generation and validation
  - User context for request isolation
  - API key generation per user

JWT secret is derived from API_SECRET_KEY in .env.
If not set, a random secret is generated (tokens won't survive restart).
"""

import os
import time
import secrets
from typing import Optional, Dict
from src.logger import logger

import jwt
import bcrypt

# JWT configuration
JWT_SECRET = os.getenv("API_SECRET_KEY") or secrets.token_urlsafe(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_token(user_id: int, username: str, role: str = "trader") -> str:
    """Create a JWT token for authenticated user."""
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict]:
    """Decode and validate a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"JWT invalid: {e}")
        return None


def generate_api_key() -> str:
    """Generate a random API key for programmatic access."""
    return f"qs_{secrets.token_urlsafe(32)}"


# ═══════════════════════════════════════════════════════════════════════════
#  DATABASE OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════

def create_users_table():
    """Create users table if not exists."""
    from src.database import NewsDB
    db = NewsDB()
    db._execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        api_key TEXT UNIQUE,
        role TEXT DEFAULT 'trader',
        balance REAL DEFAULT 10000.0,
        currency TEXT DEFAULT 'USD',
        risk_percent REAL DEFAULT 1.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )""")
    db._execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    db._execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key)")


def register_user(username: str, password: str, role: str = "trader",
                  balance: float = 10000.0, currency: str = "USD") -> Dict:
    """
    Register a new user. Returns user dict with JWT token.
    Raises ValueError if username already taken.
    """
    from src.database import NewsDB
    db = NewsDB()

    # Check if username exists
    existing = db._query_one("SELECT id FROM users WHERE username = ?", (username,))
    if existing:
        raise ValueError(f"Username '{username}' already taken")

    pw_hash = hash_password(password)
    api_key = generate_api_key()

    db._execute(
        "INSERT INTO users (username, password_hash, api_key, role, balance, currency) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, pw_hash, api_key, role, balance, currency)
    )

    user = db._query_one(
        "SELECT id, username, role, balance, currency, api_key FROM users WHERE username = ?",
        (username,)
    )
    if not user:
        raise RuntimeError("User creation failed")

    token = create_token(user[0], user[1], user[2])

    logger.info(f"[AUTH] User registered: {username} (role={role})")

    return {
        "user_id": user[0],
        "username": user[1],
        "role": user[2],
        "balance": user[3],
        "currency": user[4],
        "api_key": user[5],
        "token": token,
    }


def login_user(username: str, password: str) -> Optional[Dict]:
    """
    Authenticate user and return JWT token.
    Returns None if credentials invalid.
    """
    from src.database import NewsDB
    db = NewsDB()

    user = db._query_one(
        "SELECT id, username, password_hash, role, balance, currency, api_key FROM users WHERE username = ?",
        (username,)
    )

    if not user:
        return None

    if not verify_password(password, user[2]):
        return None

    # Update last login
    db._execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user[0],))

    token = create_token(user[0], user[1], user[3])

    logger.info(f"[AUTH] User logged in: {username}")

    return {
        "user_id": user[0],
        "username": user[1],
        "role": user[3],
        "balance": user[4],
        "currency": user[5],
        "api_key": user[6],
        "token": token,
    }


def get_user_by_api_key(api_key: str) -> Optional[Dict]:
    """Look up user by API key (for programmatic access)."""
    from src.database import NewsDB
    db = NewsDB()

    user = db._query_one(
        "SELECT id, username, role, balance, currency FROM users WHERE api_key = ?",
        (api_key,)
    )
    if not user:
        return None

    return {
        "user_id": user[0],
        "username": user[1],
        "role": user[2],
        "balance": user[3],
        "currency": user[4],
    }


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Look up user by ID."""
    from src.database import NewsDB
    db = NewsDB()

    user = db._query_one(
        "SELECT id, username, role, balance, currency FROM users WHERE id = ?",
        (user_id,)
    )
    if not user:
        return None

    return {
        "user_id": user[0],
        "username": user[1],
        "role": user[2],
        "balance": user[3],
        "currency": user[4],
    }
