"""Designer-managed scrypt decision key with no secret-bearing logs or outputs."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Callable, Sequence


SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
MIN_KEY_LENGTH = 12
MAX_KEY_LENGTH = 4096


class DecisionKeyUnavailable(Exception):
    """The designer has not installed a safe, readable decision-key hash."""


def default_key_path() -> Path:
    home = Path(os.environ.get("HOME") or Path.home())
    return home / ".config" / "urban-design" / "decision-key"


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _derive(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )


def _format_hash(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(secret, salt)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_encode(salt)}${_encode(digest)}\n"


def initialize_decision_key(
    *,
    path: str | Path | None = None,
    password_prompt: Callable[[str], str] | None = None,
) -> Path:
    """Create the designer-owned 0600 scrypt file once; never overwrite it."""

    destination = Path(path) if path is not None else default_key_path()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("A decision-key file already exists; refusing to overwrite it.")
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.parent.is_symlink() or not destination.parent.is_dir():
            raise OSError("Decision-key directory is not a regular directory.")
        os.chmod(destination.parent, 0o700)
    except OSError as exc:
        raise OSError("Could not prepare the private decision-key directory.") from exc

    prompt = password_prompt or getpass.getpass
    secret = prompt("Create decision key: ")
    confirmation = prompt("Confirm decision key: ")
    if not isinstance(secret, str) or not MIN_KEY_LENGTH <= len(secret) <= MAX_KEY_LENGTH:
        raise ValueError(f"Decision key must contain between {MIN_KEY_LENGTH} and {MAX_KEY_LENGTH} characters.")
    if not hmac.compare_digest(secret, confirmation):
        raise ValueError("Decision-key entries did not match.")

    contents = _format_hash(secret).encode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(destination, flags, 0o600)
        created = True
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as exc:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        if isinstance(exc, FileExistsError):
            raise
        raise OSError("Could not safely create the decision-key file.") from exc
    return destination


def _load_hash(path: str | Path | None) -> tuple[bytes, bytes]:
    source = Path(path) if path is not None else default_key_path()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise DecisionKeyUnavailable("Decision-key file is not a regular file.")
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                raise DecisionKeyUnavailable("Decision-key file permissions must be 0600.")
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise DecisionKeyUnavailable("Decision-key file is not owned by the current user.")
            contents = stream.read(4097)
        if len(contents) > 4096:
            raise DecisionKeyUnavailable("Decision-key file is malformed.")
        raw = contents.decode("ascii").strip()
        scheme, n_text, r_text, p_text, salt_text, digest_text = raw.split("$")
        if (scheme, int(n_text), int(r_text), int(p_text)) != (
            "scrypt",
            SCRYPT_N,
            SCRYPT_R,
            SCRYPT_P,
        ):
            raise DecisionKeyUnavailable("Decision-key file uses unsupported parameters.")
        salt = _decode(salt_text)
        expected = _decode(digest_text)
        if len(salt) != 16 or len(expected) != SCRYPT_DKLEN:
            raise DecisionKeyUnavailable("Decision-key file is malformed.")
        return salt, expected
    except DecisionKeyUnavailable:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise DecisionKeyUnavailable("Decision-key file is unavailable or malformed.") from exc


def verify_decision_key_strict(secret: str, *, path: str | Path | None = None) -> bool:
    """Verify a submitted key, propagating unavailable or malformed key files."""

    if not isinstance(secret, str) or not MIN_KEY_LENGTH <= len(secret) <= MAX_KEY_LENGTH:
        return False
    salt, expected = _load_hash(path)
    try:
        actual = _derive(secret, salt)
    except (UnicodeError, ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def verify_decision_key(secret: str, *, path: str | Path | None = None) -> bool:
    """Convenience verifier that fails closed for missing or malformed files."""

    try:
        return verify_decision_key_strict(secret, path=path)
    except (DecisionKeyUnavailable, UnicodeError, ValueError, TypeError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["init"]:
        print("Usage: python -m urban_design.decision_key init", file=sys.stderr)
        return 2
    try:
        initialize_decision_key()
    except (FileExistsError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Decision key initialized as a private scrypt hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
