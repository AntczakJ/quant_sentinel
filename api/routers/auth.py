"""
api/routers/auth.py — User Authentication Endpoints

Provides:
  POST /auth/register  — Create new user account
  POST /auth/login     — Authenticate and get JWT token
  GET  /auth/me        — Get current user info (requires auth)
"""

import sys
import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    currency: str = Field(default="USD", pattern="^(USD|PLN|EUR)$")
    balance: float = Field(default=10000.0, ge=0)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register", summary="Register new user")
async def register(req: RegisterRequest):
    """
    Create a new user account.
    Returns JWT token + API key for programmatic access.
    """
    try:
        from src.auth import register_user, create_users_table
        create_users_table()
        result = register_user(
            username=req.username,
            password=req.password,
            balance=req.balance,
            currency=req.currency,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/login", summary="Login and get JWT token")
async def login(req: LoginRequest):
    """
    Authenticate with username + password.
    Returns JWT token valid for 7 days.
    """
    try:
        from src.auth import login_user, create_users_table
        create_users_table()
        result = login_user(req.username, req.password)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")


@router.get("/me", summary="Get current user info")
async def get_current_user(request: Request):
    """
    Returns authenticated user's profile.
    Requires Bearer token or X-API-Key header.
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
