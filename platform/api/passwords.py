import bcrypt

MAX_BCRYPT_PASSWORD_BYTES = 72


def password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_BCRYPT_PASSWORD_BYTES:
        raise ValueError("Password must be at most 72 UTF-8 bytes")
    return encoded


def hash_password(password: str) -> str:
    encoded = password_bytes(password)
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, stored_hash: str | bytes) -> bool:
    encoded = password_bytes(password)
    hash_bytes = stored_hash.encode("ascii") if isinstance(stored_hash, str) else stored_hash
    return bcrypt.checkpw(encoded, hash_bytes)
