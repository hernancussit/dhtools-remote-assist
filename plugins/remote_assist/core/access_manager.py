"""
Access and Invitation Manager for Remote Assist plugin (dHtools).
Manages dynamic whitelist, one-time invitation links, and user revocation.
"""

import os
import json
import secrets
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("dHtools.Plugin.RemoteAssist.AccessManager")


class AccessManager:
    """
    Thread-safe access manager supporting invitation tokens,
    user approval, and revocation.
    """

    def __init__(self, plugin_dir: str, static_allowed_ids: Optional[List[int]] = None):
        self.plugin_dir = plugin_dir
        self.storage_path = os.path.join(plugin_dir, "whitelist.json")
        self.static_allowed_ids = set(static_allowed_ids or [])
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Loads whitelist and invitations from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "authorized_users" in data and "invitations" in data:
                        return data
            except Exception as e:
                logger.error("Error al cargar whitelist.json: %s", e)

        # Estructura por defecto
        initial = {
            "authorized_users": {},
            "invitations": {},
        }
        self._save(initial)
        return initial

    def _save(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Persists whitelist and invitations to disk safely."""
        to_save = data if data is not None else self._data
        try:
            temp_path = f"{self.storage_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2, ensure_ascii=False)
            try:
                os.replace(temp_path, self.storage_path)
            except OSError:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(to_save, f, indent=2, ensure_ascii=False)
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Error al guardar whitelist.json: %s", e)

    def is_authorized(self, user_id: int) -> bool:
        """Checks if a user is authorized to interact with the bot."""
        uid_str = str(user_id)
        with self._lock:
            # Comprueba lista estática (ej. el dueño o IDs en config.json)
            if user_id in self.static_allowed_ids or int(user_id) in self.static_allowed_ids:
                return True

            # Comprueba lista dinámica
            user = self._data.get("authorized_users", {}).get(uid_str)
            if user and user.get("status") == "active":
                return True

        return False

    def create_invitation(self, max_uses: int = 1, note: str = "") -> str:
        """Generates a secure, unique invitation token."""
        token = f"inv_{secrets.token_urlsafe(8)}"
        now_iso = datetime.now(timezone.utc).isoformat()

        invitation_record = {
            "token": token,
            "created_at": now_iso,
            "max_uses": max_uses,
            "uses": 0,
            "used_by": [],
            "status": "active",
            "note": note,
        }

        with self._lock:
            self._data["invitations"][token] = invitation_record
            self._save()

        logger.info("Nueva invitación creada: %s (Nota: %s)", token, note)
        return token

    def validate_and_use_invitation(
        self, token: str, user_id: int, first_name: str = "", username: str = ""
    ) -> Tuple[bool, str]:
        """
        Validates an invitation token and promotes the user to authorized status.
        """
        uid_str = str(user_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            inv = self._data.get("invitations", {}).get(token)
            if not inv:
                return False, "Enlace de invitación no válido o inexistente."

            if inv.get("status") != "active" or inv.get("uses", 0) >= inv.get("max_uses", 1):
                return False, "Este enlace de invitación ya ha sido utilizado o ha caducado."

            # Registrar uso de la invitación
            inv["uses"] = inv.get("uses", 0) + 1
            inv.setdefault("used_by", []).append(user_id)
            if inv["uses"] >= inv.get("max_uses", 1):
                inv["status"] = "depleted"

            # Agregar / Actualizar usuario en lista blanca
            self._data.setdefault("authorized_users", {})[uid_str] = {
                "user_id": user_id,
                "first_name": first_name or "Usuario",
                "username": username or "",
                "authorized_at": now_iso,
                "invited_by": token,
                "status": "active",
            }
            self._save()

        logger.info("Usuario %s (%s) autorizado exitosamente con token %s.", first_name, user_id, token)
        return True, "¡Acceso concedido exitosamente!"

    def revoke_user(self, user_id: int) -> bool:
        """Revokes an authorized user immediately."""
        uid_str = str(user_id)
        with self._lock:
            user = self._data.get("authorized_users", {}).get(uid_str)
            if user:
                user["status"] = "revoked"
                user["revoked_at"] = datetime.now(timezone.utc).isoformat()
                self._save()
                logger.info("Acceso revocado para usuario %s (ID: %s).", user.get("first_name"), user_id)
                return True
        return False

    def list_users(self) -> List[Dict[str, Any]]:
        """Returns all authorized/revoked users."""
        with self._lock:
            return list(self._data.get("authorized_users", {}).values())

    def list_invitations(self) -> List[Dict[str, Any]]:
        """Returns all generated invitations."""
        with self._lock:
            return list(self._data.get("invitations", {}).values())
