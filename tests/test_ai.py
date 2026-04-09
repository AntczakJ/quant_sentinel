#!/usr/bin/env python3
"""tests/test_ai.py - AI Engine tests"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from src.integrations.ai_engine import ask_ai_gold, OPENAI_KEY, client

    print("Testing AI Engine...")

    tests_passed = 0
    tests_total = 0

    # Test 1: OpenAI key
    try:
        assert OPENAI_KEY is not None and len(OPENAI_KEY) > 0
        print("[OK] OpenAI API key available")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] OpenAI API key: {e}")
    tests_total += 1

    # Test 2: Client initialized
    try:
        assert client is not None
        print("[OK] OpenAI client initialized")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] OpenAI client: {e}")
    tests_total += 1

    # Test 3: AI response
    try:
        response = ask_ai_gold("news", "Gold rising 2%")
        assert response is not None
        assert len(response) > 0
        print(f"[OK] AI response received ({len(response)} chars)")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] AI response: {e}")
    tests_total += 1

    print(f"\n{tests_passed}/{tests_total} tests passed")
    return 0 if tests_passed >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
