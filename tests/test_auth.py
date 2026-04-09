"""
tests/test_auth.py — Tests for authentication system (Phase B3)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPasswordHashing:
    def test_hash_and_verify(self):
        from src.auth import hash_password, verify_password
        pw = "test_password_123"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_different_hashes_for_same_password(self):
        from src.auth import hash_password
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # bcrypt uses random salt


class TestJWT:
    def test_create_and_decode_token(self):
        from src.auth import create_token, decode_token
        token = create_token(user_id=1, username="testuser", role="trader")
        assert isinstance(token, str)
        payload = decode_token(token)
        assert payload is not None
        assert payload["user_id"] == 1
        assert payload["username"] == "testuser"
        assert payload["role"] == "trader"

    def test_invalid_token_returns_none(self):
        from src.auth import decode_token
        assert decode_token("invalid.token.here") is None
        assert decode_token("") is None

    def test_api_key_generation(self):
        from src.auth import generate_api_key
        key = generate_api_key()
        assert key.startswith("qs_")
        assert len(key) > 20


class TestUserRegistration:
    def test_register_and_login(self):
        from src.auth import create_users_table, register_user, login_user
        import random
        create_users_table()

        username = f"test_user_{random.randint(10000, 99999)}"
        result = register_user(username, "secure_pass_123")
        assert result["username"] == username
        assert "token" in result
        assert "api_key" in result
        assert result["api_key"].startswith("qs_")

        # Login with correct password
        login_result = login_user(username, "secure_pass_123")
        assert login_result is not None
        assert login_result["username"] == username

        # Login with wrong password
        assert login_user(username, "wrong_pass") is None

    def test_duplicate_username_raises(self):
        from src.auth import create_users_table, register_user
        import random
        create_users_table()

        username = f"dup_user_{random.randint(10000, 99999)}"
        register_user(username, "pass123")
        with pytest.raises(ValueError, match="already taken"):
            register_user(username, "pass456")

    def test_get_user_by_api_key(self):
        from src.auth import create_users_table, register_user, get_user_by_api_key
        import random
        create_users_table()

        username = f"apikey_user_{random.randint(10000, 99999)}"
        result = register_user(username, "pass123")
        api_key = result["api_key"]

        user = get_user_by_api_key(api_key)
        assert user is not None
        assert user["username"] == username

        assert get_user_by_api_key("qs_nonexistent") is None
