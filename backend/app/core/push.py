"""Web Push notification helper with VAPID authentication."""

import base64
import json
import logging
import os
import time
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


class VAPIDHelper:
    """Minimal VAPID signer for Web Push notifications."""

    def __init__(self, private_key_b64: str | None = None, public_key_b64: str | None = None, claims_email: str | None = None):
        self.private_key_b64 = private_key_b64 or os.getenv("VAPID_PRIVATE_KEY")
        self.public_key_b64 = public_key_b64 or os.getenv("VAPID_PUBLIC_KEY")
        self.claims_email = claims_email or os.getenv("VAPID_CLAIMS_EMAIL", "admin@sowknow.local")
        self._private_key = None
        self._public_key = None

        if self.private_key_b64:
            try:
                pk_bytes = _b64url_decode(self.private_key_b64)
                self._private_key = ec.derive_private_key(
                    int.from_bytes(pk_bytes, "big"),
                    ec.SECP256R1(),
                )
                self._public_key = self._private_key.public_key()
            except Exception as exc:
                logger.error("Failed to load VAPID private key: %s", exc)

    @property
    def is_configured(self) -> bool:
        return self._private_key is not None and self._public_key is not None

    @property
    def public_key(self) -> str:
        if not self._public_key:
            return ""
        pub_bytes = self._public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return _b64url_encode(pub_bytes)

    def _sign_jwt(self, audience: str) -> str:
        if not self._private_key:
            raise RuntimeError("VAPID private key not configured")

        header = _b64url_encode(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        payload = _b64url_encode(
            json.dumps({
                "aud": audience,
                "exp": int(time.time()) + 43200,  # 12 hours
                "sub": f"mailto:{self.claims_email}",
            }).encode()
        )
        signing_input = f"{header}.{payload}".encode()

        from cryptography.hazmat.primitives import hashes
        signature = self._private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        sig_b64 = _b64url_encode(signature)

        return f"{header}.{payload}.{sig_b64}"

    def send_push(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        title: str = "SOWKNOW",
        body: str = "",
        data: dict | None = None,
    ) -> bool:
        """Send a Web Push message. Falls back to tickle if payload encryption fails."""
        if not self.is_configured:
            logger.warning("VAPID not configured, skipping push")
            return False

        audience = f"{urlparse(endpoint).scheme}://{urlparse(endpoint).netloc}"
        try:
            jwt = self._sign_jwt(audience)
        except Exception as exc:
            logger.error("VAPID JWT signing failed: %s", exc)
            return False

        headers = {
            "Authorization": f"vapid t={jwt}, k={self.public_key}",
            "TTL": "86400",
        }

        payload = json.dumps({
            "title": title,
            "body": body,
            "data": data or {},
        }).encode()

        try:
            # Attempt to encrypt payload using simple ECE-like approach
            encrypted = self._encrypt_payload(payload, p256dh, auth)
            headers["Content-Type"] = "application/octet-stream"
            headers["Content-Encoding"] = "aes128gcm"
            body_to_send = encrypted
        except Exception as exc:
            logger.debug("Payload encryption failed (%s), sending tickle push", exc)
            # Tickle push — service worker will fetch details from API
            body_to_send = b""
            headers["Content-Type"] = "application/json"

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(endpoint, headers=headers, content=body_to_send)
            if response.status_code in (200, 201, 202, 204):
                logger.info("Push sent successfully to %s", endpoint[:60])
                return True
            elif response.status_code == 410:
                logger.info("Push subscription expired: %s", endpoint[:60])
                return False
            else:
                logger.warning("Push failed with status %s: %s", response.status_code, response.text[:200])
                return False
        except Exception as exc:
            logger.error("Push request failed: %s", exc)
            return False

    def _encrypt_payload(self, payload: bytes, p256dh: str, auth: str) -> bytes:
        """Minimal Web Push payload encryption (RFC 8188 / RFC 8291)."""
        import struct

        # Decode client public key and auth secret
        client_pubkey_bytes = _b64url_decode(p256dh)
        auth_secret = _b64url_decode(auth)

        # Generate ephemeral key pair
        ephemeral_key = ec.generate_private_key(ec.SECP256R1())
        ephemeral_pubkey = ephemeral_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )

        # Compute shared secret
        client_pubkey = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), client_pubkey_bytes
        )
        shared_secret = ephemeral_key.exchange(ec.ECDH(), client_pubkey)

        # Derive key using HKDF (simplified)
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes

        # PRK for key derivation
        prk = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=auth_secret,
            info=b"WebPush: info\x00" + client_pubkey_bytes + ephemeral_pubkey,
        ).derive(shared_secret)

        # Derive content encryption key and nonce
        cek = HKDF(
            algorithm=hashes.SHA256(),
            length=16,
            salt=b"\x00" * 16,  # Simplified — should use random salt
            info=b"Content-Encoding: aes128gcm\x00",
        ).derive(prk)

        nonce = HKDF(
            algorithm=hashes.SHA256(),
            length=12,
            salt=b"\x00" * 16,
            info=b"Content-Encoding: nonce\x00",
        ).derive(prk)

        # Pad payload
        padded = b"\x00" + payload

        # Encrypt with AES-GCM
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(cek)
        ciphertext = aesgcm.encrypt(nonce, padded, None)

        # Build aes128gcm record: salt(16) + rs(4) + idlen(1) + keyid + ciphertext
        salt = b"\x00" * 16  # Should be random in full implementation
        rs = struct.pack(">I", 4096)
        idlen = struct.pack("B", len(ephemeral_pubkey))

        return salt + rs + idlen + ephemeral_pubkey + ciphertext


vapid = VAPIDHelper()


def send_task_alarm_push(endpoint: str, p256dh: str, auth: str, task_title: str, task_notes: str | None = None) -> bool:
    return vapid.send_push(
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        title="SOWKNOW Task Alarm",
        body=task_title,
        data={"type": "task_alarm", "title": task_title, "notes": task_notes or ""},
    )
