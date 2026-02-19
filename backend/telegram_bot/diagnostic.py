"""
Diagnostic script for Telegram Bot connectivity
Run this inside the telegram-bot container to verify connectivity to backend
"""
import asyncio
import os
import sys
import socket

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from network_utils import ResilientAsyncClient

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

async def test_dns_resolution():
    """Test if the backend hostname resolves"""
    print(f"Testing DNS resolution for backend...")
    try:
        # Extract hostname from URL
        from urllib.parse import urlparse
        parsed = urlparse(BACKEND_URL)
        hostname = parsed.hostname
        port = parsed.port or 80

        print(f"  Hostname: {hostname}")
        print(f"  Port: {port}")

        # Try to resolve the hostname
        addr_info = socket.getaddrinfo(hostname, port)
        print(f"  DNS Resolution: SUCCESS")
        for info in addr_info[:2]:
            print(f"    - {info[4]}")
        return True
    except Exception as e:
        print(f"  DNS Resolution: FAILED - {e}")
        return False

async def test_backend_connection():
    """Test connection to backend health endpoint"""
    print(f"\nTesting connection to backend at {BACKEND_URL}...")

    client = ResilientAsyncClient(base_url=BACKEND_URL, timeout=10.0)
    try:
        response = await client.get("/health")
        print(f"  Status Code: {response.status_code}")
        print(f"  Response: {response.text[:200]}")
        if response.status_code == 200:
            print(f"  Connection: SUCCESS")
            return True
        else:
            print(f"  Connection: FAILED (unexpected status)")
            return False
    except Exception as e:
        print(f"  Connection: FAILED - {e}")
        return False
    finally:
        await client.close()

async def main():
    print("=" * 60)
    print("Telegram Bot Connectivity Diagnostics")
    print("=" * 60)
    print(f"BACKEND_URL: {BACKEND_URL}")
    print()

    dns_ok = await test_dns_resolution()
    conn_ok = await test_backend_connection()

    print("\n" + "=" * 60)
    if dns_ok and conn_ok:
        print("All tests PASSED - Bot should be able to connect to backend")
    else:
        print("Some tests FAILED - Check the errors above")
        if not dns_ok:
            print("\nDNS Fix: Ensure both services are on the same Docker network")
            print("  docker network ls")
            print("  docker network inspect sowknow-net")
        if not conn_ok:
            print("\nConnection Fix: Check if backend is healthy")
            print("  docker ps | grep backend")
            print("  docker logs sowknow4-backend")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
