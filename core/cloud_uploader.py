"""
Cloud Uploader module for Remote Assist plugin (dHtools).
Strictly compliant with dHtools multi-user cloud architecture and official Plugin SDK.
Supports both completed download jobs (upload_job_to_cloud) and direct file uploads (upload_file_to_cloud).
"""

import os
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("dHtools.Plugin.RemoteAssist.Cloud")


class CloudUploader:
    """
    Handles cloud synchronization per user using official dHtools SDK methods:
    - self.manager.get_user_cloud_providers(username)
    - self.manager.upload_job_to_cloud(plugin_id, job_id, username)
    - self.manager.upload_file_to_cloud(plugin_id, filepath, username)
    """

    def __init__(self, config: Dict[str, Any], manager: Any = None):
        self.config = config
        self.manager = manager

    @property
    def is_enabled(self) -> bool:
        cloud_conf = self.config.get("cloud_upload", {})
        return bool(cloud_conf.get("enabled", False))

    @property
    def auto_upload(self) -> bool:
        cloud_conf = self.config.get("cloud_upload", {})
        return bool(self.is_enabled and cloud_conf.get("auto_upload_on_complete", False))

    def update_config(self, new_config: Dict[str, Any]) -> None:
        self.config = new_config

    def get_user_providers(self, username: str) -> List[str]:
        """Queries active cloud storage providers for a specific dHtools user."""
        if not self.manager or not hasattr(self.manager, "get_user_cloud_providers"):
            logger.warning("Manager no disponible o no implementa get_user_cloud_providers.")
            return []
        try:
            providers = self.manager.get_user_cloud_providers(username)
            return providers if isinstance(providers, list) else []
        except Exception as e:
            logger.error("Error al consultar proveedores de nube para '%s': %s", username, e)
            return []

    def _resolve_target_provider(self, username: str, provider: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """Resolves target cloud provider for a given user."""
        active_providers = self.get_user_providers(username)

        target_provider = provider
        if not target_provider:
            configured_target = self.config.get("cloud_upload", {}).get("target", "auto")
            if configured_target and configured_target != "auto":
                target_provider = configured_target
            elif active_providers:
                target_provider = active_providers[0]

        if not target_provider:
            msg = f"El usuario '{username}' no tiene proveedores de nube activos en dHtools."
            return None, msg

        return target_provider, None

    def upload_job(
        self, job_id: str, username: str, provider: Optional[str] = None
    ) -> Tuple[bool, Any]:
        """
        Dispatches upload of a completed download job to a user's cloud storage.
        Uses official manager.upload_job_to_cloud(plugin_id, job_id, username).
        """
        if not self.manager or not hasattr(self.manager, "upload_job_to_cloud"):
            msg = "El SDK de dHtools (manager.upload_job_to_cloud) no está disponible en este entorno."
            logger.error(msg)
            return False, {"error": msg}

        if not job_id:
            return False, {"error": "ID de descarga (job_id) no proporcionado."}

        if not username:
            return False, {"error": "Nombre de usuario (owner) no proporcionado."}

        target_provider, err = self._resolve_target_provider(username, provider)
        if not target_provider:
            return False, {"error": err}

        logger.info(
            "Despachando subida de job '%s' a la nube '%s' para usuario '%s'...",
            job_id,
            target_provider,
            username,
        )

        try:
            ok, result = self.manager.upload_job_to_cloud(
                plugin_id=target_provider,
                job_id=job_id,
                username=username,
            )
            return ok, result
        except Exception as e:
            logger.error("Excepción al ejecutar upload_job_to_cloud: %s", e)
            return False, {"error": str(e)}

    def upload_file(
        self, filepath: str, username: str, provider: Optional[str] = None
    ) -> Tuple[bool, Any]:
        """
        Uploads an arbitrary local file (e.g. sent by a Telegram user) directly
        to the user's cloud storage using official manager.upload_file_to_cloud.
        """
        if not filepath or not os.path.exists(filepath):
            return False, {"error": f"El archivo local no existe: {filepath}"}

        if not username:
            return False, {"error": "Nombre de usuario (owner) no proporcionado."}

        target_provider, err = self._resolve_target_provider(username, provider)
        if not target_provider:
            return False, {"error": err}

        filename = os.path.basename(filepath)
        logger.info(
            "Subiendo archivo '%s' a la nube '%s' para usuario '%s' vía upload_file_to_cloud...",
            filename,
            target_provider,
            username,
        )

        # 1. Invocación oficial del SDK de dHtools
        if self.manager and hasattr(self.manager, "upload_file_to_cloud"):
            try:
                ok, result = self.manager.upload_file_to_cloud(
                    plugin_id=target_provider,
                    filepath=filepath,
                    username=username,
                )
                return ok, result
            except Exception as e:
                logger.error("Error al invocar manager.upload_file_to_cloud: %s", e)
                return False, {"error": str(e)}

        # 2. Fallback a instancia del plugin (compatibilidad de transición)
        if self.manager and hasattr(self.manager, "get_plugin_instance"):
            try:
                cloud_plugin = self.manager.get_plugin_instance(target_provider)
                if cloud_plugin and hasattr(cloud_plugin, "upload_file_for_user"):
                    return cloud_plugin.upload_file_for_user(filepath=filepath, username=username)
            except Exception as e:
                logger.error("Error al invocar plugin '%s': %s", target_provider, e)
                return False, {"error": str(e)}

        msg = "El método upload_file_to_cloud no está disponible en PluginManager."
        logger.error(msg)
        return False, {"error": msg}
