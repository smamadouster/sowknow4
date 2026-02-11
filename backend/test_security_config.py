#!/usr/bin/env python3
"""
Test script to validate CORS, TrustedHost, and Nginx security configuration.
This script tests that the security middleware is properly configured.
"""

import os
import sys
import re
from pathlib import Path

def test_production_security():
    """Test production security configuration"""
    print("Testing Production Security Configuration...")
    print("=" * 70)

    # Set production environment
    os.environ["APP_ENV"] = "production"

    # Test 1: Missing ALLOWED_ORIGINS should raise error
    print("\n[Test 1] Testing missing ALLOWED_ORIGINS in production...")
    os.environ.pop("ALLOWED_ORIGINS", None)
    os.environ.pop("ALLOWED_HOSTS", None)

    try:
        # Import will fail with ValueError if security is enforced
        import importlib
        if 'app.main_minimal' in sys.modules:
            del sys.modules['app.main_minimal']

        from app import main_minimal
        print("  ❌ FAIL: Should have raised ValueError for missing ALLOWED_ORIGINS")
        return False
    except ValueError as e:
        if "SECURITY ERROR" in str(e) and "ALLOWED_ORIGINS" in str(e):
            print(f"  ✓ PASS: Correctly raised error: {e}")
        else:
            print(f"  ❌ FAIL: Wrong error message: {e}")
            return False

    # Test 2: Wildcard origin should raise error
    print("\n[Test 2] Testing wildcard origin rejection in production...")
    os.environ["ALLOWED_ORIGINS"] = "*"
    os.environ["ALLOWED_HOSTS"] = "sowknow.gollamtech.com"

    try:
        if 'app.main_minimal' in sys.modules:
            del sys.modules['app.main_minimal']

        from app import main_minimal
        print("  ❌ FAIL: Should have raised ValueError for wildcard origin")
        return False
    except ValueError as e:
        if "SECURITY ERROR" in str(e) and "Wildcard origins" in str(e):
            print(f"  ✓ PASS: Correctly rejected wildcard origin: {e}")
        else:
            print(f"  ❌ FAIL: Wrong error message: {e}")
            return False

    # Test 3: Valid configuration should work
    print("\n[Test 3] Testing valid production configuration...")
    os.environ["ALLOWED_ORIGINS"] = "https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
    os.environ["ALLOWED_HOSTS"] = "sowknow.gollamtech.com,www.sowknow.gollamtech.com"

    try:
        if 'app.main_minimal' in sys.modules:
            del sys.modules['app.main_minimal']

        from app import main_minimal

        # Check that origins were parsed correctly
        expected_origins = [
            "https://sowknow.gollamtech.com",
            "https://www.sowknow.gollamtech.com"
        ]
        if main_minimal.ALLOWED_ORIGINS == expected_origins:
            print(f"  ✓ PASS: Origins parsed correctly: {main_minimal.ALLOWED_ORIGINS}")
        else:
            print(f"  ❌ FAIL: Wrong origins. Expected: {expected_origins}, Got: {main_minimal.ALLOWED_ORIGINS}")
            return False

        # Check that hosts were parsed correctly
        expected_hosts = ["sowknow.gollamtech.com", "www.sowknow.gollamtech.com"]
        if main_minimal.ALLOWED_HOSTS == expected_hosts:
            print(f"  ✓ PASS: Hosts parsed correctly: {main_minimal.ALLOWED_HOSTS}")
        else:
            print(f"  ❌ FAIL: Wrong hosts. Expected: {expected_hosts}, Got: {main_minimal.ALLOWED_HOSTS}")
            return False

    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        return False

    print("\n" + "=" * 70)
    print("All production security tests passed! ✓")
    return True


def test_development_configuration():
    """Test development configuration"""
    print("\n\nTesting Development Configuration...")
    print("=" * 70)

    # Set development environment
    os.environ["APP_ENV"] = "development"
    os.environ.pop("ALLOWED_ORIGINS", None)
    os.environ.pop("ALLOWED_HOSTS", None)

    try:
        if 'app.main_minimal' in sys.modules:
            del sys.modules['app.main_minimal']

        from app import main_minimal

        # Check default origins
        print(f"\n  Default origins: {main_minimal.ALLOWED_ORIGINS}")
        if "http://localhost:3000" in main_minimal.ALLOWED_ORIGINS:
            print("  ✓ PASS: Includes localhost:3000")
        else:
            print("  ❌ FAIL: Missing localhost:3000")
            return False

        # Check default hosts
        print(f"\n  Default hosts: {main_minimal.ALLOWED_HOSTS}")
        if main_minimal.ALLOWED_HOSTS == ["*"]:
            print("  ✓ PASS: Allows all hosts in development")
        else:
            print("  ❌ FAIL: Should allow all hosts in development")
            return False

    except Exception as e:
        print(f"  ❌ FAIL: Unexpected error: {e}")
        return False

    print("\n" + "=" * 70)
    print("Development configuration test passed! ✓")
    return True


def test_nginx_configuration():
    """Test nginx security configuration"""
    print("\n\nTesting Nginx Security Configuration...")
    print("=" * 70)

    # Get the project root directory
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent
    nginx_configs = [
        project_root / "nginx" / "nginx-http-only.conf",
        project_root / "nginx" / "nginx.conf",
    ]

    success = True

    for nginx_conf in nginx_configs:
        if not nginx_conf.exists():
            print(f"  ❌ FAIL: Nginx config not found: {nginx_conf}")
            success = False
            continue

        print(f"\n  Checking: {nginx_conf.name}")

        try:
            content = nginx_conf.read_text()

            # Test 1: Check for server_tokens off
            if "server_tokens off" in content:
                print("    ✓ PASS: server_tokens off is set")
            else:
                print("    ❌ FAIL: server_tokens off is NOT set")
                success = False

            # Test 2: Check for no wildcard CORS headers in nginx
            if 'Access-Control-Allow-Origin "*"' in content:
                print("    ❌ FAIL: Found wildcard CORS header (should be in FastAPI)")
                success = False
            else:
                print("    ✓ PASS: No wildcard CORS headers in nginx")

            # Test 3: Check for security headers
            security_headers = {
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
            }

            for header, expected_value in security_headers.items():
                if header in content:
                    print(f"    ✓ PASS: {header} header is set")
                else:
                    print(f"    ⚠ WARN: {header} header not found")

            # Test 4: Check for rate limiting
            if "limit_req_zone" in content:
                print("    ✓ PASS: Rate limiting is configured")
            else:
                print("    ⚠ WARN: Rate limiting not found")

        except Exception as e:
            print(f"  ❌ FAIL: Error reading {nginx_conf}: {e}")
            success = False

    print("\n" + "=" * 70)
    if success:
        print("Nginx configuration test passed! ✓")
    else:
        print("Nginx configuration test failed! ✗")
    return success


def main():
    """Run all security tests"""
    print("\n" + "=" * 70)
    print("SOWKNOW Security Configuration Test Suite")
    print("=" * 70)

    success = True

    # Test development first (should always work)
    if not test_development_configuration():
        success = False

    # Test production security
    if not test_production_security():
        success = False

    # Test nginx configuration
    if not test_nginx_configuration():
        success = False

    print("\n" + "=" * 70)
    if success:
        print("✓ ALL TESTS PASSED - Security configuration is working correctly!")
        print("=" * 70)
        return 0
    else:
        print("✗ SOME TESTS FAILED - Security configuration needs attention!")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
