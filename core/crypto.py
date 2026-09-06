"""
Cryptographic manager for Remote Assist plugin (dHtools).
Encrypts and decrypts sensitive bot tokens and credentials at rest using Fernet (AES-128-CBC + HMAC).
"""

import os
import copy
import logging
from typing import Dict, Any, Optional

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

logger = logging.getLogger("dHtools.Plugin.RemoteAssist.Crypto")

ENCRYPTED_PREFIX = "enc:"
SENSITIVE_PATHS = [
    ("telegram", "bot_token"),
    ("telegram", "chat_id"),
    ("whatsapp", "api_key"),
    ("discord_webhook", "webhook_url"),
]


class CryptoManager:
    """
    Handles transparent encryption and decryption of sensitive configuration fields.
    """

    def __init__(self, plugin_dir: str, custom_key: Optional[str] = None):
        self.plugin_dir = plugin_dir
        self.key_path = os.path.join(plugin_dir, ".secret.key")
        self._fernet = None
        self._init_cipher(custom_key)

    def _init_cipher(self, custom_key: Optional[str] = None) -> None:
        """Initializes the Fernet cipher instance."""
        if not HAS_CRYPTOGRAPHY:
            logger.warning("Librería 'cryptography' no encontrada. El cifrado en reposo estará desactivado.")
            return

        key_bytes = None
        if custom_key:
            key_bytes = custom_key.encode("utf-8") if isinstance(custom_key, str) else custom_key
        elif os.path.exists(self.key_path):
            try:
                with open(self.key_path, "rb") as f:
                    key_bytes = f.read().strip()
            except Exception as e:
                logger.error("Error al leer .secret.key: %s", e)

        if not key_bytes:
            # Generar nueva llave criptográfica segura
            key_bytes = Fernet.generate_key()
            try:
                with open(self.key_path, "wb") as f:
                    f.write(key_bytes)
                # Restringir permisos si el OS lo soporta
                try:
                    os.chmod(self.key_path, 0o600)
                except Exception:
                    pass
                logger.info("Nueva llave criptográfica generada y guardada en .secret.key")
            except Exception as e:
                logger.error("Error al persistir .secret.key: %s", e)

        try:
            self._fernet = Fernet(key_bytes)
        except Exception as e:
            logger.error("Fallo al inicializar Fernet con la llave proporcionada: %s", e)

    def encrypt(self, plain_text: str) -> str:
        """Encrypts a string and prefixes it with 'enc:'."""
        if not plain_text or not isinstance(plain_text, str):
            return plain_text or ""

        # Si ya está cifrado, no volver a cifrar
        if plain_text.startswith(ENCRYPTED_PREFIX):
            return plain_text

        if not self._fernet:
            return plain_text

        try:
            cipher_bytes = self._fernet.encrypt(plain_text.encode("utf-8"))
            return f"{ENCRYPTED_PREFIX}{cipher_bytes.decode('utf-8')}"
        except Exception as e:
            logger.error("Error al cifrar texto: %s", e)
            return plain_text

    def decrypt(self, cipher_text: str) -> str:
        """Decrypts a string prefixed with 'enc:'."""
        if not cipher_text or not isinstance(cipher_text, str):
            return cipher_text or ""

        if not cipher_text.startswith(ENCRYPTED_PREFIX):
            return cipher_text

        if not self._fernet:
            logger.warning("Intento de descifrar sin Fernet inicializado.")
            return cipher_text

        try:
            raw_cipher = cipher_text[len(ENCRYPTED_PREFIX):].encode("utf-8")
            plain_bytes = self._fernet.decrypt(raw_cipher)
            return plain_bytes.decode("utf-8")
        except Exception as e:
            logger.error("Error al descifrar texto: %s", e)
            return ""

    def encrypt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Returns a copy of the config dictionary with sensitive fields encrypted."""
        cfg = copy.deepcopy(config)
        for section, key in SENSITIVE_PATHS:
            if section in cfg and isinstance(cfg[section], dict):
                val = cfg[section].get(key)
                if val and isinstance(val, str) and not val.startswith(ENCRYPTED_PREFIX):
                    cfg[section][key] = self.encrypt(val)
        return cfg

    def decrypt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Returns a copy of the config dictionary with sensitive fields decrypted for in-memory use."""
        cfg = copy.deepcopy(config)
        for section, key in SENSITIVE_PATHS:
            if section in cfg and isinstance(cfg[section], dict):
                val = cfg[section].get(key)
                if val and isinstance(val, str) and val.startswith(ENCRYPTED_PREFIX):
                    cfg[section][key] = self.decrypt(val)
        return cfg

    @staticmethod
    def mask_token(token: str) -> str:
        """Masks a token for safe UI display (e.g. 123456:AA••••••••xy)."""
        if not token or not isinstance(token, str):
            return ""
        if len(token) <= 8:
            return "••••••••"
        prefix = token[:6]
        suffix = token[-4:]
        return f"{prefix}••••••••••••••••{suffix}"
