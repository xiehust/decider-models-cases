"""Password hashing and reset-token helpers."""
import hashlib
import hmac
import secrets

RESET_TOKEN_BYTES = 32


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


def new_reset_token() -> str:
    """Create a one-time token; the caller stores its hash and emails a link."""
    return secrets.token_urlsafe(RESET_TOKEN_BYTES)


def reset_token_matches(candidate: str, stored_hash: str) -> bool:
    digest = hashlib.sha256(candidate.encode()).hexdigest()
    return hmac.compare_digest(digest, stored_hash)
