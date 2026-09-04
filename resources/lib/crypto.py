"""Device-bound encryption for storing Videoland credentials and session tokens.

Kodi's add-on settings (settings.xml) are plain text readable by any local
process on the box. This module encrypts sensitive values before they are handed
to the settings layer so the raw email/password/session signature never touches
disk in clear text.

Security model
--------------
* A random 256-bit master key is generated once and stored in the add-on data
  directory with 0600 permissions, so only the user that owns the profile can
  read it. Settings copied to another machine do not carry the key and therefore
  cannot be decrypted there.
* Values are encrypted with an authenticated stream cipher:
    - key = PBKDF2-HMAC-SHA256(master_key, random_salt)
    - keystream = repeated SHA256(key || counter) XORed with the plaintext
      (a CTR-mode stream construction)
    - an HMAC-SHA256 authentication tag over salt/nonce/ciphertext makes the
      blob tamper-evident.
  Every value gets a fresh random salt and counter seed, so ciphertexts are
  non-deterministic and can't be substituted between fields.

Only the ciphertext lives in Kodi settings; plaintext credentials never persist.
This uses only the Python standard library so it runs on any Kodi installation.
"""

import base64
import hashlib
import hmac
import json
import os

_MASTER_LEN = 32  # 256-bit master key
_PBKDF2_ITERATIONS = 600000
_KEY_DIGEST = hashlib.sha256
_BLOCK = 32


class CipherError(Exception):
    """Raised when secrets cannot be safely handled."""


def _key_file_path(data_dir):
    if not data_dir:
        raise CipherError("Geen opslagmap beschikbaar voor de cryptosleutel")
    return os.path.join(data_dir, ".credentials_key")


def _load_or_create_master(data_dir):
    """Return the device master key, generating and securing it on first use."""
    path = _key_file_path(data_dir)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        pass
    try:
        os.makedirs(data_dir, exist_ok=True)
        key = os.urandom(_MASTER_LEN)
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key
    except OSError as exc:
        raise CipherError("Kan de cryptosleutel niet aanmaken: {}".format(exc))


def _derive(master, salt):
    return hashlib.pbkdf2_hmac("sha256", master, salt, _PBKDF2_ITERATIONS, dklen=_KEY_DIGEST().digest_size)


def _keystream(key, nonce, length):
    """Produce ``length`` bytes of key = SHA256(key || nonce || counter)."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(_KEY_DIGEST(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_plain(data_dir, plaintext):
    """Encrypt ``plaintext`` (str) and return a portable base64 token."""
    master = _load_or_create_master(data_dir)
    salt = os.urandom(16)
    nonce = os.urandom(16)
    key = _derive(master, salt)
    raw = plaintext.encode("utf-8")
    mask = _keystream(key, nonce, len(raw))
    ct = bytes(a ^ b for a, b in zip(raw, mask))
    tag = hmac.new(key, salt + nonce + ct, _KEY_DIGEST).digest()
    payload = {
        "v": 1,
        "kdf": "pbkdf2-sha256",
        "cipher": "ctr-xor",
        "mac": "hmac-sha256",
        "salt": b64(salt),
        "nonce": b64(nonce),
        "ct": b64(ct),
        "tag": b64(tag),
    }
    return b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def decrypt_plain(data_dir, token):
    """Decrypt a token produced by :func:`encrypt_plain`. Returns str or None."""
    if not token:
        return None
    try:
        payload = json.loads(base64.b64decode(token).decode("utf-8"))
        if payload.get("v") != 1 or payload.get("cipher") != "ctr-xor":
            return None
        master = _load_or_create_master(data_dir)
        salt = un64(payload["salt"])
        nonce = un64(payload["nonce"])
        ct = un64(payload["ct"])
        key = _derive(master, salt)
        expected = hmac.new(key, salt + nonce + ct, _KEY_DIGEST).digest()
        if not hmac.compare_digest(expected, un64(payload["tag"])):
            return None
        mask = _keystream(key, nonce, len(ct))
        return bytes(a ^ b for a, b in zip(ct, mask)).decode("utf-8")
    except (KeyError, ValueError, CipherError):
        return None


def b64(raw):
    return base64.b64encode(raw).decode("ascii")


def un64(text):
    return base64.b64decode(text.encode("ascii"))


def encrypt_json(data_dir, obj):
    """Encrypt an arbitrary JSON-serialisable object into a settings token."""
    return encrypt_plain(data_dir, json.dumps(obj, separators=(",", ":")))


def decrypt_json(data_dir, token):
    """Decrypt a settings token back into an object. Returns {} on failure."""
    plain = decrypt_plain(data_dir, token)
    if plain is None:
        return {}
    try:
        return json.loads(plain)
    except (ValueError, TypeError):
        return {}
