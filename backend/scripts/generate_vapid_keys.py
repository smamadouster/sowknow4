#!/usr/bin/env python3
"""Generate VAPID keys for Web Push notifications."""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vapid_keys():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    print("VAPID Keys generated successfully!")
    print()
    print("Add these to your .env file:")
    print(f"VAPID_PUBLIC_KEY={b64url_encode(public_bytes)}")
    print(f"VAPID_PRIVATE_KEY={b64url_encode(private_bytes)}")
    print()
    print("And update your frontend public key in:")
    print("  frontend/hooks/usePushNotifications.ts")
    print("  frontend/public/sw.js (if hardcoded)")


if __name__ == "__main__":
    generate_vapid_keys()
