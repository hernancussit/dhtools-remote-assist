"""
Remote Assist Plugin for dHtools.
Autonomous Delegated Download Assistant with Invitation System,
Multi-User Cloud Sync, and Multi-Platform Notifications.
"""

import os
import json
import logging
import threading
from typing import Dict, Any, Optional, List
import requests
from flask import Blueprint, render_template, jsonify, request

try:
    from .core.telegram_bot import TelegramBot
    from .core.channels import NotificationDispatcher
    from .core.cloud_uploader import CloudUploader
    from .core.access_manager import AccessManager
    from .core.crypto import CryptoManager
except (ImportError, ValueError):
    from core.telegram_bot import TelegramBot
    from core.channels import NotificationDispatcher
    from core.cloud_uploader import CloudUploader
    from core.access_manager import AccessManager
    from core.crypto import CryptoManager

logger = logging.getLogger("dHtools.Plugin.RemoteAssist")


class Plugin:
    """
    Main plugin interface compliant with dHtools experimental plugin architecture.
    """

    def __init__(self, manager: Any = None, metadata: Optional[Dict[str, Any]] = None):
        self.manager = manager
        self.metadata = metadata or {}
        self.plugin_id = self.metadata.get("id", "remote_assist")
        self.name = self.metadata.get("name", "Remote Assist")

        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.plugin_dir, "config.json")
        self.crypto = CryptoManager(self.plugin_dir)
        self.config = self._load_config()

        # Gestor de accesos e invitaciones dinámicas
        static_ids = self.config.get("telegram", {}).get("allowed_user_ids", [])
        self.access_manager = AccessManager(self.plugin_dir, static_allowed_ids=static_ids)

        # Módulos desacoplados
        self.cloud_uploader = CloudUploader(self.config, manager=self.manager)
        self.telegram_bot = TelegramBot(
            self.config.get("telegram", {}),
            manager=self.manager,
            cloud_uploader=self.cloud_uploader,
            access_manager=self.access_manager,
        )
        self.notifier = NotificationDispatcher(self.config, telegram_bot=self.telegram_bot)

        self._telegram_thread: Optional[threading.Thread] = None
        logger.info("Plugin %s (Asistente Delegado) inicializado.", self.name)

    # -------------------------------------------------------------
    # Configuración Local
    # -------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        """Loads configuration from config.json with fallback to defaults, decrypting sensitive fields in memory."""
        raw_cfg: Dict[str, Any] = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw_cfg = json.load(f)
            except Exception as e:
                logger.error("Error al leer config.json: %s", e)
        else:
            example_path = os.path.join(self.plugin_dir, "config.example.json")
            if os.path.exists(example_path):
                try:
                    with open(example_path, "r", encoding="utf-8") as f:
                        raw_cfg = json.load(f)
                except Exception:
                    pass

        if not raw_cfg:
            raw_cfg = {
                "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
                "presets": {
                    "owner_username": "admin",
                    "default_quality": "1080p",
                    "default_format": "video",
                    "target_cloud": "auto",
                    "auto_upload_on_complete": True,
                },
                "whatsapp": {"enabled": False},
                "discord_webhook": {"enabled": False},
                "cloud_upload": {"enabled": True, "target": "auto", "auto_upload_on_complete": True},
                "general": {"download_quality_default": "best"},
            }

        return self.crypto.decrypt_config(raw_cfg)

    def _save_config(self) -> None:
        """Saves current in-memory config dictionary to config.json with sensitive fields encrypted at rest."""
        try:
            encrypted_cfg = self.crypto.encrypt_config(self.config)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(encrypted_cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error al escribir config.json: %s", e)

    def reload_config(self) -> Dict[str, Any]:
        """Reloads config from disk and updates child components."""
        self.config = self._load_config()
        tg_conf = self.config.get("telegram", {})
        self.telegram_bot.config = tg_conf
        self.telegram_bot.bot_token = tg_conf.get("bot_token", "")
        self.telegram_bot.default_chat_id = tg_conf.get("chat_id", "")
        self.telegram_bot.send_media_file = tg_conf.get("send_media_file", False)
        self.telegram_bot.max_media_size_mb = tg_conf.get("max_media_size_mb", 50)

        self.cloud_uploader.update_config(self.config)
        self.notifier.update_config(self.config)
        return self.config

    def _restart_telegram_bot(self) -> None:
        """Safely stops existing bot polling thread and restarts if enabled."""
        try:
            if self.telegram_bot:
                self.telegram_bot.stop()
        except Exception as e:
            logger.warning("Aviso al detener bot de Telegram: %s", e)

        if self.telegram_bot.is_enabled:
            logger.info("Iniciando hilo worker del bot de Telegram con nueva configuración...")
            self._telegram_thread = threading.Thread(
                target=self.telegram_bot.start_polling,
                name=f"{self.plugin_id}_telegram_worker",
                daemon=True,
            )
            self._telegram_thread.start()
        else:
            logger.info("Bot de Telegram deshabilitado o sin token.")

    # -------------------------------------------------------------
    # Hooks del Ciclo de Vida de dHtools
    # -------------------------------------------------------------

    def on_startup(self, app: Any = None, context: Optional[Dict[str, Any]] = None) -> None:
        """Starts the background Telegram polling worker."""
        if self.telegram_bot.is_enabled:
            logger.info("Iniciando hilo daemon del bot de Telegram en %s...", self.name)
            self._telegram_thread = threading.Thread(
                target=self.telegram_bot.start_polling,
                name=f"{self.plugin_id}_telegram_worker",
                daemon=True,
            )
            self._telegram_thread.start()
        else:
            logger.info("Bot de Telegram no habilitado o sin token.")

    def register_routes(self, app: Any) -> None:
        """Registers plugin Blueprint under /plugin/remote_assist/."""
        url_prefix = f"/plugin/{self.plugin_id}"

        bp = Blueprint(
            self.plugin_id,
            __name__,
            url_prefix=url_prefix,
            template_folder=os.path.join(self.plugin_dir, "templates"),
            static_folder=os.path.join(self.plugin_dir, "static"),
            static_url_path=f"{url_prefix}/static",
        )

        @bp.route("/", methods=["GET"])
        def dashboard():
            owner = self.config.get("presets", {}).get("owner_username", "admin")
            available_clouds = self.cloud_uploader.get_user_providers(owner)
            users_list = self.access_manager.list_users()
            active_users = [u for u in users_list if u.get("status") == "active"]

            tg_conf = self.config.get("telegram", {})
            raw_token = tg_conf.get("bot_token", "")
            masked_token = self.crypto.mask_token(raw_token) if raw_token else ""

            status_summary = {
                "telegram_enabled": self.telegram_bot.is_enabled,
                "telegram_running": self.telegram_bot.is_running,
                "bot_username": self.telegram_bot.bot_username,
                "whatsapp_enabled": self.config.get("whatsapp", {}).get("enabled", False),
                "discord_enabled": self.config.get("discord_webhook", {}).get("enabled", False),
                "cloud_enabled": self.cloud_uploader.is_enabled,
                "version": self.metadata.get("version", "1.0.0"),
                "authorized_users_count": len(active_users),
                "repository": self.metadata.get("repository", ""),
                "branch": self.metadata.get("branch", "main"),
            }

            return render_template(
                "index.html",
                status=status_summary,
                config=self.config,
                telegram_conf=tg_conf,
                masked_token=masked_token,
                presets=self.config.get("presets", {}),
                available_clouds=available_clouds,
                authorized_users=users_list,
            )

        @bp.route("/api/invitations/create", methods=["POST"])
        def api_create_invitation():
            data = request.get_json() or {}
            note = data.get("note", "").strip()
            max_uses = int(data.get("max_uses", 1))

            token = self.access_manager.create_invitation(max_uses=max_uses, note=note)
            bot_user = self.telegram_bot.bot_username or "TuBot"
            invite_url = f"https://t.me/{bot_user}?start={token}"

            return jsonify({
                "success": True,
                "token": token,
                "invite_url": invite_url,
                "bot_username": bot_user,
            })

        @bp.route("/api/users", methods=["GET"])
        def api_get_users():
            return jsonify({"success": True, "users": self.access_manager.list_users()})

        @bp.route("/api/users/revoke", methods=["POST"])
        def api_revoke_user():
            data = request.get_json() or {}
            user_id = data.get("user_id")
            if not user_id:
                return jsonify({"success": False, "message": "user_id no especificado"}), 400

            ok = self.access_manager.revoke_user(user_id)
            return jsonify({"success": ok, "message": "Acceso revocado exitosamente" if ok else "Usuario no encontrado"})

        @bp.route("/api/presets/save", methods=["POST"])
        def api_save_presets():
            data = request.get_json() or {}
            presets = self.config.setdefault("presets", {})
            if "owner_username" in data:
                presets["owner_username"] = str(data["owner_username"]).strip()
            if "default_quality" in data:
                presets["default_quality"] = str(data["default_quality"]).strip()
            if "default_format" in data:
                presets["default_format"] = str(data["default_format"]).strip()
            if "target_cloud" in data:
                presets["target_cloud"] = str(data["target_cloud"]).strip()
            if "auto_upload_on_complete" in data:
                presets["auto_upload_on_complete"] = bool(data["auto_upload_on_complete"])

            self._save_config()
            self.reload_config()
            return jsonify({"success": True, "message": "Presets guardados correctamente", "presets": presets})

        @bp.route("/api/reload", methods=["POST"])
        def api_reload():
            self.reload_config()
            return jsonify({"success": True, "message": "Configuración recargada."})

        @bp.route("/api/bot-config/save", methods=["POST"])
        def api_save_bot_config():
            data = request.get_json() or {}
            tg_conf = self.config.setdefault("telegram", {})

            enabled = bool(data.get("enabled", False))
            chat_id = str(data.get("chat_id", "")).strip()
            token_input = str(data.get("bot_token", "")).strip()
            send_media = bool(data.get("send_media_file", False))
            max_media_size = int(data.get("max_media_size_mb", 50))

            # Solo actualizar el token si no es el enmascarado y no está vacío
            if token_input and "••••" not in token_input:
                tg_conf["bot_token"] = token_input
            elif not token_input and not tg_conf.get("bot_token"):
                tg_conf["bot_token"] = ""

            tg_conf["enabled"] = enabled
            tg_conf["chat_id"] = chat_id
            tg_conf["send_media_file"] = send_media
            tg_conf["max_media_size_mb"] = max_media_size

            # Guardar con cifrado en disco y recargar en memoria
            self._save_config()
            self.reload_config()

            # Reiniciar worker del bot
            self._restart_telegram_bot()

            return jsonify({
                "success": True,
                "message": "Configuración del bot de Telegram guardada y cifrada en disco.",
                "telegram_enabled": self.telegram_bot.is_enabled,
                "telegram_running": self.telegram_bot.is_running,
                "bot_username": self.telegram_bot.bot_username,
                "masked_token": self.crypto.mask_token(tg_conf.get("bot_token", "")),
            })

        @bp.route("/api/test-channel", methods=["POST"])
        def api_test_channel():
            data = request.get_json() or {}
            channel = data.get("channel", "telegram")

            if channel == "telegram":
                if not self.telegram_bot.bot_token:
                    return jsonify({"success": False, "message": "Bot no configurado. Ingresa un token primero."}), 400

                bot_info = self.telegram_bot.get_me()
                if not bot_info:
                    return jsonify({"success": False, "message": "No se pudo conectar con Telegram. Verifica que el token sea correcto."}), 400

                username = bot_info.get("username", "Bot")
                chat_id = self.config.get("telegram", {}).get("chat_id")
                if chat_id:
                    ok = self.telegram_bot.send_message(
                        chat_id,
                        f"🔔 <b>Remote Assist</b>: Conexión con @{username} exitosa y cifrado en reposo activo.",
                    )
                    if ok:
                        return jsonify({"success": True, "message": f"Conectado como @{username} y mensaje enviado al chat {chat_id}."})
                    return jsonify({"success": True, "message": f"Conectado como @{username}, pero no se pudo entregar mensaje al chat {chat_id}."})

                return jsonify({"success": True, "message": f"Conectado con éxito a Telegram como @{username}."})

            elif channel == "whatsapp":
                return jsonify({"success": False, "message": "Canal WhatsApp no configurado aún."})
            elif channel == "discord":
                return jsonify({"success": False, "message": "Webhook de Discord no configurado aún."})

            return jsonify({"success": False, "message": f"Canal '{channel}' desconocido."}), 400

        @bp.route("/api/check-update", methods=["GET"])
        def api_check_update():
            repo = self.metadata.get("repository", "")
            branch = self.metadata.get("branch", "main")
            current_version = self.metadata.get("version", "1.0.0")

            if self.manager and hasattr(self.manager, "check_plugin_update"):
                try:
                    return jsonify(self.manager.check_plugin_update(self.plugin_id))
                except Exception as e:
                    logger.warning("Error en manager.check_plugin_update: %s", e)

            # Verificación alternativa vía GitHub Raw si se configuró repositorio
            if repo and "github.com" in repo:
                try:
                    clean_repo = repo.rstrip("/").replace("https://github.com/", "")
                    raw_url = f"https://raw.githubusercontent.com/{clean_repo}/{branch}/plugins/{self.plugin_id}/plugin.json"
                    resp = requests.get(raw_url, timeout=5)
                    if resp.status_code == 200:
                        remote_data = resp.json()
                        remote_version = remote_data.get("version", current_version)
                        has_update = (remote_version != current_version)
                        return jsonify({
                            "success": True,
                            "has_update": has_update,
                            "current_version": current_version,
                            "remote_version": remote_version,
                            "repository": repo,
                            "branch": branch,
                        })
                except Exception as e:
                    return jsonify({"success": False, "error": str(e), "current_version": current_version})

            return jsonify({
                "success": True,
                "has_update": False,
                "current_version": current_version,
                "repository": repo,
                "branch": branch,
            })

        app.register_blueprint(bp)
        logger.info("Rutas de %s registradas en %s", self.name, url_prefix)

    def on_download_complete(self, job_data: Dict[str, Any]) -> None:
        """
        Triggered when a download completes in dHtools.
        1. Despatches cloud upload to owner's cloud.
        2. Confirms directly to the Telegram guest who sent the link.
        3. Dispatches general multi-channel notifications.
        """
        extra = job_data.get("extra_params") or {}
        guest_chat_id = extra.get("telegram_chat_id")
        title = job_data.get("title") or job_data.get("filename") or "Descarga completada"
        job_id = job_data.get("job_id", "")
        filepath = job_data.get("filepath", "")

        presets = self.config.get("presets", {})
        owner = job_data.get("owner") or presets.get("owner_username", "admin")
        target_cloud = extra.get("target_cloud") or presets.get("target_cloud", "auto")
        should_cloud_upload = bool(presets.get("auto_upload_on_complete", True) or extra.get("user_cloud_sync"))

        cloud_display_name = target_cloud
        if should_cloud_upload and job_id:
            try:
                ok, res = self.cloud_uploader.upload_job(
                    job_id=job_id,
                    username=owner,
                    provider=(target_cloud if target_cloud != "auto" else None),
                )
                if ok:
                    active_clouds = self.cloud_uploader.get_user_providers(owner)
                    cloud_display_name = target_cloud if target_cloud != "auto" else (active_clouds[0] if active_clouds else "la nube")
                    logger.info("Subida a la nube iniciada para '%s' (%s)", title, cloud_display_name)
                else:
                    logger.warning("Fallo al iniciar subida para '%s': %s", title, res)
            except Exception as e:
                logger.error("Error al procesar subida a la nube: %s", e)

        # Confirmación directa al usuario de Telegram que envió el enlace
        if guest_chat_id and self.telegram_bot:
            try:
                self.telegram_bot.notify_guest_completion(
                    chat_id=guest_chat_id,
                    title=title,
                    cloud_name=cloud_display_name,
                    filepath=filepath,
                )
            except Exception as e:
                logger.error("Error al confirmar descarga al invitado: %s", e)

        # Notificación a canales generales (WhatsApp / Discord / Canal Telegram)
        try:
            self.notifier.notify_download_complete(job_data)
        except Exception as e:
            logger.error("Error al notificar por canales generales: %s", e)

    def on_download_error(self, job_data: Dict[str, Any], error: Optional[Any] = None) -> None:
        """
        Triggered when a download fails.
        Notifies the specific guest if applicable.
        """
        extra = job_data.get("extra_params") or {}
        guest_chat_id = extra.get("telegram_chat_id")
        title = job_data.get("title") or job_data.get("url") or "Descarga"

        if guest_chat_id and self.telegram_bot:
            try:
                self.telegram_bot.notify_guest_error(guest_chat_id, title, error=str(error) if error else None)
            except Exception as e:
                logger.error("Error al notificar fallo al invitado: %s", e)

        try:
            self.notifier.notify_download_error(job_data, error=str(error) if error else None)
        except Exception as e:
            logger.error("Error al despachar notificación de error: %s", e)

    # -------------------------------------------------------------
    # Protocolo de Inyección en la Interfaz Web y Navegación
    # -------------------------------------------------------------

    def get_user_nav_item(self, username: Optional[str] = None) -> Dict[str, Any]:
        """Injects direct navigation link into dHtools sidebar."""
        return {
            "title": "Remote Assist",
            "icon": "📡",
            "url": f"/plugin/{self.plugin_id}/",
            "badge": "EXP",
        }

    def get_telegram_commands(self) -> List[Dict[str, str]]:
        """Extra commands for the official dHtools bot."""
        return [
            {"command": "remote", "description": "Panel de control del Asistente Delegado"}
        ]
