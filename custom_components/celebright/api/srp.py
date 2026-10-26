"""Cognito SRP (USER_SRP_AUTH) client maths, pure stdlib.

SRP-6a over the RFC 3526 3072-bit group with SHA-256 and Cognito's HKDF; the HTTP calls are in auth.py.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

# RFC 3526 group 15 (3072-bit MODP) — the group Cognito uses.
_N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64"
    "ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6B"
    "F12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB31"
    "43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF"
)
_G_HEX = "2"
_N = int(_N_HEX, 16)
_G = int(_G_HEX, 16)
_INFO_BITS = b"Caldera Derived Key"

# strftime("%a %b") is locale-dependent; Cognito needs the English names.
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex_hash(hex_string: str) -> str:
    return _sha256_hex(bytes.fromhex(hex_string))


def _pad_hex(value: int | str) -> str:
    """Hex string with a leading 00 if the high bit is set (signed-int encoding)."""
    h = format(value, "x") if isinstance(value, int) else value
    if len(h) % 2 == 1:
        return "0" + h
    if h[0] in "89abcdefABCDEF":
        return "00" + h
    return h


_K = int(_hex_hash("00" + _N_HEX + "0" + _G_HEX), 16)


def _timestamp() -> str:
    """Cognito's timestamp format: 'Tue Oct 6 14:03:09 UTC 2026' (day not zero-padded)."""
    now = datetime.now(timezone.utc)
    return (
        f"{_DAYS[now.weekday()]} {_MONTHS[now.month - 1]} {now.day} "
        f"{now:%H:%M:%S} UTC {now.year}"
    )


class SRPClient:
    """One SRP login attempt: build SRP_A, then answer the PASSWORD_VERIFIER challenge."""

    def __init__(self, pool_id: str, username: str, password: str) -> None:
        self._pool_name = pool_id.split("_", 1)[1]
        self._username = username
        self._password = password
        self._a = secrets.randbits(1024) % _N
        self._big_a = pow(_G, self._a, _N)
        if self._big_a % _N == 0:
            raise ValueError("SRP A must not be zero")

    def get_srp_a(self) -> str:
        """SRP_A for InitiateAuth (hex)."""
        return format(self._big_a, "x")

    def process_challenge(
        self, params: dict[str, str], timestamp: str | None = None
    ) -> dict[str, str]:
        """ChallengeResponses for the PASSWORD_VERIFIER step. Raises KeyError / ValueError on a bad challenge."""
        # Internal user id from the challenge, not the typed email.
        user_id = params["USER_ID_FOR_SRP"]
        salt_hex = params["SALT"]
        big_b = int(params["SRP_B"], 16)
        secret_block_b64 = params["SECRET_BLOCK"]

        if big_b % _N == 0:
            raise ValueError("SRP B must not be zero")
        u = int(_hex_hash(_pad_hex(self._big_a) + _pad_hex(big_b)), 16)
        if u == 0:
            raise ValueError("SRP u must not be zero")

        user_pass_hash = _sha256_hex(
            f"{self._pool_name}{user_id}:{self._password}".encode("utf-8")
        )
        x = int(_hex_hash(_pad_hex(salt_hex) + user_pass_hash), 16)
        s = pow(big_b - _K * pow(_G, x, _N), self._a + u * x, _N)

        prk = hmac.new(
            bytes.fromhex(_pad_hex(u)), bytes.fromhex(_pad_hex(s)), hashlib.sha256
        ).digest()
        key = hmac.new(prk, _INFO_BITS + b"\x01", hashlib.sha256).digest()[:16]

        ts = timestamp or _timestamp()
        msg = (
            self._pool_name.encode("utf-8")
            + user_id.encode("utf-8")
            + base64.standard_b64decode(secret_block_b64)
            + ts.encode("utf-8")
        )
        signature = base64.standard_b64encode(
            hmac.new(key, msg, hashlib.sha256).digest()
        ).decode("utf-8")

        return {
            "TIMESTAMP": ts,
            # Echo the challenge's USERNAME (the internal user id, not the typed email).
            "USERNAME": params.get("USERNAME", user_id),
            "PASSWORD_CLAIM_SECRET_BLOCK": secret_block_b64,
            "PASSWORD_CLAIM_SIGNATURE": signature,
        }
