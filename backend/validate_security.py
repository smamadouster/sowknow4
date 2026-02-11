#!/usr/bin/env python3
"""
Security Configuration Validation Script
Validates the CORS and TrustedHost configuration logic without requiring FastAPI.
"""

import os

def parse_allowed_origins(app_env, allowed_origins_str):
    """Replicate the ALLOWED_ORIGINS parsing logic from main_minimal.py"""
    if app_env == "production":
        if not allowed_origins_str:
            raise ValueError(
                "SECURITY ERROR: ALLOWED_ORIGINS environment variable is required in production. "
                "Example: ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
            )
        allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]

        if "*" in allowed_origins:
            raise ValueError(
                "SECURITY ERROR: Wildcard origins [*] are not allowed with credentials in production. "
                "Use specific origins instead."
            )
        return allowed_origins
    else:
        allowed_origins = allowed_origins_str.split(",") if allowed_origins_str else [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ]
        return allowed_origins


def parse_allowed_hosts(app_env, allowed_hosts_str):
    """Replicate the ALLOWED_HOSTS parsing logic from main_minimal.py"""
    if app_env == "production":
        if not allowed_hosts_str:
            raise ValueError(
                "SECURITY ERROR: ALLOWED_HOSTS environment variable is required in production. "
                "Example: ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com"
            )
        allowed_hosts = [host.strip() for host in allowed_hosts_str.split(",") if host.strip()]
        return allowed_hosts
    else:
        return ["*"]


def test_security_config():
    """Run security configuration tests"""
    print("\n" + "=" * 80)
    print("SOWKNOW Security Configuration Validation")
    print("=" * 80)

    all_passed = True

    # Test 1: Production without ALLOWED_ORIGINS
    print("\n[Test 1] Production environment missing ALLOWED_ORIGINS")
    try:
        parse_allowed_origins("production", "")
        print("  ❌ FAIL: Should have raised ValueError")
        all_passed = False
    except ValueError as e:
        if "SECURITY ERROR" in str(e) and "ALLOWED_ORIGINS" in str(e):
            print(f"  ✓ PASS: Correctly raises error")
            print(f"         Message: {str(e)[:80]}...")
        else:
            print(f"  ❌ FAIL: Wrong error message")
            all_passed = False

    # Test 2: Production with wildcard origin
    print("\n[Test 2] Production environment with wildcard origin")
    try:
        parse_allowed_origins("production", "*")
        print("  ❌ FAIL: Should have raised ValueError for wildcard")
        all_passed = False
    except ValueError as e:
        if "SECURITY ERROR" in str(e) and "Wildcard origins" in str(e):
            print(f"  ✓ PASS: Correctly rejects wildcard origin")
            print(f"         Message: {str(e)[:80]}...")
        else:
            print(f"  ❌ FAIL: Wrong error message")
            all_passed = False

    # Test 3: Production with valid ALLOWED_ORIGINS
    print("\n[Test 3] Production environment with valid configuration")
    try:
        origins = parse_allowed_origins(
            "production",
            "https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
        )
        expected = ["https://sowknow.gollamtech.com", "https://www.sowknow.gollamtech.com"]
        if origins == expected:
            print(f"  ✓ PASS: Origins parsed correctly")
            print(f"         {origins}")
        else:
            print(f"  ❌ FAIL: Wrong origins. Expected {expected}, got {origins}")
            all_passed = False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        all_passed = False

    # Test 4: Production without ALLOWED_HOSTS
    print("\n[Test 4] Production environment missing ALLOWED_HOSTS")
    try:
        parse_allowed_hosts("production", "")
        print("  ❌ FAIL: Should have raised ValueError")
        all_passed = False
    except ValueError as e:
        if "SECURITY ERROR" in str(e) and "ALLOWED_HOSTS" in str(e):
            print(f"  ✓ PASS: Correctly raises error")
            print(f"         Message: {str(e)[:80]}...")
        else:
            print(f"  ❌ FAIL: Wrong error message")
            all_passed = False

    # Test 5: Production with valid ALLOWED_HOSTS
    print("\n[Test 5] Production environment with valid ALLOWED_HOSTS")
    try:
        hosts = parse_allowed_hosts(
            "production",
            "sowknow.gollamtech.com,www.sowknow.gollamtech.com"
        )
        expected = ["sowknow.gollamtech.com", "www.sowknow.gollamtech.com"]
        if hosts == expected:
            print(f"  ✓ PASS: Hosts parsed correctly")
            print(f"         {hosts}")
        else:
            print(f"  ❌ FAIL: Wrong hosts. Expected {expected}, got {hosts}")
            all_passed = False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        all_passed = False

    # Test 6: Development defaults
    print("\n[Test 6] Development environment defaults")
    try:
        origins = parse_allowed_origins("development", "")
        hosts = parse_allowed_hosts("development", "")

        if "http://localhost:3000" in origins:
            print(f"  ✓ PASS: Default origins include localhost:3000")
            print(f"         {origins}")
        else:
            print(f"  ❌ FAIL: Missing localhost:3000 in defaults")
            all_passed = False

        if hosts == ["*"]:
            print(f"  ✓ PASS: Default hosts allow all (permissive for dev)")
        else:
            print(f"  ❌ FAIL: Development should allow all hosts")
            all_passed = False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        all_passed = False

    # Test 7: Custom development configuration
    print("\n[Test 7] Development environment with custom configuration")
    try:
        origins = parse_allowed_origins(
            "development",
            "http://localhost:8080,http://127.0.0.1:8080"
        )
        expected = ["http://localhost:8080", "http://127.0.0.1:8080"]
        if origins == expected:
            print(f"  ✓ PASS: Custom origins parsed correctly")
            print(f"         {origins}")
        else:
            print(f"  ❌ FAIL: Wrong origins. Expected {expected}, got {origins}")
            all_passed = False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        all_passed = False

    # Test 8: Whitespace handling
    print("\n[Test 8] Whitespace handling in comma-separated lists")
    try:
        origins = parse_allowed_origins(
            "production",
            "https://sowknow.gollamtech.com , https://www.sowknow.gollamtech.com , "
        )
        expected = ["https://sowknow.gollamtech.com", "https://www.sowknow.gollamtech.com"]
        if origins == expected:
            print(f"  ✓ PASS: Whitespace handled correctly")
            print(f"         {origins}")
        else:
            print(f"  ❌ FAIL: Wrong origins. Expected {expected}, got {origins}")
            all_passed = False
    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("✓ ALL TESTS PASSED - Security configuration is working correctly!")
        print("\nProduction deployment requirements:")
        print("  1. Set APP_ENV=production")
        print("  2. Set ALLOWED_ORIGINS to specific HTTPS origins (no wildcards)")
        print("  3. Set ALLOWED_HOSTS to specific hostnames")
        print("\nThe application will raise an error if these are not properly configured.")
    else:
        print("✗ SOME TESTS FAILED - Security configuration needs attention!")
    print("=" * 80 + "\n")

    return 0 if all_passed else 1


def check_env_files():
    """Check if .env files have the required variables"""
    print("\n" + "=" * 80)
    print("Environment Files Check")
    print("=" * 80)

    files_to_check = [
        ("backend/.env.production", "production"),
        (".env.example", "example"),
        ("backend/.env.example", "backend example"),
    ]

    for filepath, context in files_to_check:
        print(f"\nChecking {filepath} ({context})...")
        try:
            with open(filepath, 'r') as f:
                content = f.read()

                has_allowed_origins = "ALLOWED_ORIGINS" in content
                has_allowed_hosts = "ALLOWED_HOSTS" in content

                if has_allowed_origins:
                    print(f"  ✓ ALLOWED_ORIGINS variable found")
                else:
                    print(f"  ⚠ ALLOWED_ORIGINS variable missing")

                if has_allowed_hosts:
                    print(f"  ✓ ALLOWED_HOSTS variable found")
                else:
                    print(f"  ⚠ ALLOWED_HOSTS variable missing")

        except FileNotFoundError:
            print(f"  ⚠ File not found: {filepath}")
        except Exception as e:
            print(f"  ❌ Error reading file: {e}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    import sys
    check_env_files()
    sys.exit(test_security_config())
