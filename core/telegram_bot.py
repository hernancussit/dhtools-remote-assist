"""
Telegram Bot client and command worker for dHtools Remote Assist Plugin.
Autonomous, delegated download assistant with one-time invitation links,
zero-friction URL downloads, and direct file-to-cloud uploads.
"""

import os
import time
import logging
import threading
from typing import Optional, Dict, Any, List, Tuple
import requests

logger = logging.getLogger("dHtools.Plugin.RemoteAssist.Telegram")


class TelegramBot:
    """
    Autonomous Telegram Bot that operates as a Delegated Assistant:
    - Scrapers and global searches find a closed wall.
    - Authorized guests access via invite tokens (/start inv_...).
    - Guests send URLs (auto-download) or files (auto-upload to cloud).
    """

    API_BASE = "https://api.telegram.org/bot"
    FILE_BASE = "https://api.telegram.org/file/bot"
    MAX_INCOMING_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB (Límite oficial de Telegram Bot API getFile)

    def __init__(
        self,
        config: Dict[str, Any],
        manager: Any = None,
        cloud_uploader: Any = None,
        access_manager: Any = None,
    ):
        self.config = config
        self.manager = manager
        self.cloud_uploader = cloud_uploader
        self.access_manager = access_manager
        self.bot_token = config.get("bot_token", "").strip()
        self.default_chat_id = config.get("chat_id", "")
        self.send_media_file: bool = config.get("send_media_file", False)
        self.max_media_size_mb: int = config.get("max_media_size_mb", 50)

        self._incoming_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "incoming_files"
        )
        os.makedirs(self._incoming_dir, exist_ok=True)

        self._stop_event = threading.Event()
        self._bot_info: Optional[Dict[str, Any]] = None
        self._is_running = False
        self._session = requests.Session()

    @property
    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", False) and self.bot_token)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def bot_username(self) -> str:
        if self._bot_info:
            return self._bot_info.get("username", "")
        return ""

    def get_me(self) -> Optional[Dict[str, Any]]:
        """Verifies bot token and retrieves bot metadata."""
        if not self.bot_token:
            return None
        url = f"{self.API_BASE}{self.bot_token}/getMe"
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    self._bot_info = data.get("result")
                    return self._bot_info
            logger.error("Error al validar token de Telegram: %s", resp.text)
        except Exception as e:
            logger.error("Fallo de conexión con Telegram getMe: %s", e)
        return None

    def start_polling(self) -> None:
        """Main long-polling loop intended to run in a background daemon thread."""
        if not self.is_enabled:
            logger.info("Bot de Telegram desactivado o sin token configurado.")
            return

        bot_data = self.get_me()
        if not bot_data:
            logger.error("No se pudo autenticar con Telegram. Abortando polling.")
            return

        username = bot_data.get("username", "UnknownBot")
        logger.info("🤖 Bot de Telegram @%s activo como Asistente Delegado de dHtools.", username)

        self._is_running = True
        self._stop_event.clear()
        offset = None

        retry_delay = 2
        while not self._stop_event.is_set():
            try:
                params: Dict[str, Any] = {"timeout": 20}
                if offset is not None:
                    params["offset"] = offset

                url = f"{self.API_BASE}{self.bot_token}/getUpdates"
                response = self._session.get(url, params=params, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        for update in updates:
                            update_id = update.get("update_id")
                            offset = update_id + 1
                            self._handle_update(update)
                    retry_delay = 2
                elif response.status_code == 409:
                    logger.warning("Conflicto 409: Otra instancia de bot está usando este token.")
                    time.sleep(10)
                else:
                    logger.warning("Respuesta inesperada de getUpdates (%d): %s", response.status_code, response.text)
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)

            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException as req_err:
                logger.warning("Error de red en Telegram polling: %s. Reintentando en %ds...", req_err, retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
            except Exception as e:
                logger.error("Error inesperado en worker de Telegram: %s", e, exc_info=True)
                time.sleep(5)

        self._is_running = False
        logger.info("Worker de Telegram detenido limpiamente.")

    def stop(self) -> None:
        """Signals the polling loop to terminate."""
        self._stop_event.set()

    def _is_user_authorized(self, user_id: int) -> bool:
        """Checks authorization via the dynamic AccessManager."""
        if self.access_manager:
            return self.access_manager.is_authorized(user_id)
        allowed = self.config.get("allowed_user_ids", [])
        return bool(not allowed or user_id in allowed or str(user_id) in allowed)

    def _extract_file_payload(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extracts file information from document, video, audio, or photo messages."""
        if message.get("document"):
            doc = message["document"]
            return {
                "file_id": doc.get("file_id"),
                "filename": doc.get("file_name") or f"document_{doc.get('file_id')[:8]}",
                "file_size": doc.get("file_size", 0),
                "type": "document",
            }
        elif message.get("video"):
            vid = message["video"]
            return {
                "file_id": vid.get("file_id"),
                "filename": vid.get("file_name") or f"video_{vid.get('file_id')[:8]}.mp4",
                "file_size": vid.get("file_size", 0),
                "type": "video",
            }
        elif message.get("audio"):
            aud = message["audio"]
            ext = ".mp3"
            title = aud.get("file_name") or aud.get("title")
            return {
                "file_id": aud.get("file_id"),
                "filename": f"{title}{ext}" if title and not title.endswith(ext) else (title or f"audio_{aud.get('file_id')[:8]}.mp3"),
                "file_size": aud.get("file_size", 0),
                "type": "audio",
            }
        elif message.get("photo"):
            photos = message["photo"]
            if isinstance(photos, list) and photos:
                best_photo = photos[-1]
                return {
                    "file_id": best_photo.get("file_id"),
                    "filename": f"photo_{best_photo.get('file_id')[:8]}.jpg",
                    "file_size": best_photo.get("file_size", 0),
                    "type": "photo",
                }
        return None

    def _download_telegram_file(self, file_id: str, filename: str) -> Optional[str]:
        """Downloads a file from Telegram API servers to local disk."""
        try:
            # 1. getFile metadata
            get_file_url = f"{self.API_BASE}{self.bot_token}/getFile"
            resp = self._session.get(get_file_url, params={"file_id": file_id}, timeout=15)
            if resp.status_code != 200 or not resp.json().get("ok"):
                logger.error("Error en getFile (%d): %s", resp.status_code, resp.text)
                return None

            file_path = resp.json()["result"]["file_path"]
            download_url = f"{self.FILE_BASE}{self.bot_token}/{file_path}"

            # 2. Stream download
            local_path = os.path.join(self._incoming_dir, filename)
            logger.info("Descargando archivo desde Telegram hacia %s...", local_path)

            with self._session.get(download_url, stream=True, timeout=60) as dl_resp:
                dl_resp.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in dl_resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            return local_path
        except Exception as e:
            logger.error("Error al descargar archivo desde Telegram: %s", e)
            return None

    def _handle_update(self, update: Dict[str, Any]) -> None:
        """Parses and dispatches incoming updates."""
        message = update.get("message") or update.get("channel_post")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        from_user = message.get("from", {})
        user_id = from_user.get("id", chat_id)
        first_name = from_user.get("first_name", "Usuario")
        username = from_user.get("username", "")
        text = (message.get("text") or "").strip()

        # -------------------------------------------------------------
        # Manejo de /start (Invitaciones y Bienvenida)
        # -------------------------------------------------------------
        if text.startswith("/start"):
            parts = text.split()
            token_arg = parts[1].strip() if len(parts) > 1 else None
            self._handle_start(chat_id, user_id, first_name, username, token_arg)
            return

        # -------------------------------------------------------------
        # Verificación estricta de Lista Blanca
        # -------------------------------------------------------------
        if not self._is_user_authorized(user_id):
            logger.warning("Acceso denegado a usuario no autorizado: %s (ID: %s)", first_name, user_id)
            self.send_message(
                chat_id,
                "⛔ <b>Acceso Restringido</b>\n"
                "Este bot es privado y opera únicamente mediante invitación.\n"
                "Pídele un enlace de acceso al administrador para comenzar.",
            )
            return

        # -------------------------------------------------------------
        # Recepción y Subida de Archivos Directos a la Nube
        # -------------------------------------------------------------
        file_payload = self._extract_file_payload(message)
        if file_payload:
            self._handle_direct_file_upload(file_payload, chat_id, user_id, first_name)
            return

        # -------------------------------------------------------------
        # Enlace Directo (Flujo Cero Fricción para Descarga de Medios)
        # -------------------------------------------------------------
        if text.startswith("http://") or text.startswith("https://"):
            self._handle_auto_download(text, chat_id, user_id, first_name)
            return

        # -------------------------------------------------------------
        # Comandos Opcionales de Ayuda y Estado
        # -------------------------------------------------------------
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower().split("@")[0]
            args = parts[1:]
            self._execute_guest_command(cmd, args, chat_id, user_id, first_name)

    def _handle_start(
        self, chat_id: Any, user_id: int, first_name: str, username: str, token: Optional[str]
    ) -> None:
        """Processes /start with or without invitation token."""
        owner_name = self.config.get("presets", {}).get("owner_username", "el administrador")

        # 1. Si el usuario envía un token de invitación
        if token and self.access_manager:
            ok, msg = self.access_manager.validate_and_use_invitation(
                token=token,
                user_id=user_id,
                first_name=first_name,
                username=username,
            )
            if ok:
                welcome_msg = (
                    f"🎉 <b>¡Bienvenido/a {first_name}!</b>\n\n"
                    f"Has sido autorizado/a por <b>{owner_name}</b> para utilizar este servicio.\n\n"
                    f"✨ <b>¿Cómo usarlo?</b>\n"
                    f"• <b>Para descargar:</b> Envíame cualquier enlace (YouTube, Instagram, TikTok...).\n"
                    f"• <b>Para respaldar en la nube:</b> Envíame cualquier archivo o documento directamente aquí."
                )
                self.send_message(chat_id, welcome_msg)
                return
            else:
                self.send_message(chat_id, f"⛔ <b>Invitación no válida:</b>\n{msg}")
                return

        # 2. Si no tiene token pero YA estaba autorizado
        if self._is_user_authorized(user_id):
            self.send_message(
                chat_id,
                f"👋 <b>¡Hola de nuevo, {first_name}!</b>\n"
                f"Envíame un enlace de video para descargarlo o cualquier archivo para subirlo a la nube.",
            )
            return

        # 3. Si es un usuario desconocido o scraper buscando en Telegram
        self.send_message(
            chat_id,
            "⛔ <b>Servicio Privado</b>\n"
            "Este asistente multimedia opera exclusivamente bajo invitación privada.\n"
            "Si tienes un enlace de invitación, ábrelo para desbloquear el acceso.",
        )

    def _handle_direct_file_upload(
        self, file_payload: Dict[str, Any], chat_id: Any, user_id: int, first_name: str
    ) -> None:
        """
        Receives an uploaded file from Telegram and uploads it directly
        to the owner's configured cloud storage in dHtools.
        """
        file_id = file_payload["file_id"]
        filename = file_payload["filename"]
        file_size = file_payload.get("file_size", 0)
        file_size_mb = file_size / (1024 * 1024)

        # Límite oficial de descarga de Telegram Bot API
        if file_size > self.MAX_INCOMING_SIZE_BYTES:
            self.send_message(
                chat_id,
                f"⚠️ <b>Archivo demasiado grande:</b> <code>{filename}</code> ({file_size_mb:.1f} MB)\n"
                f"La API oficial de Bots de Telegram limita la recepción de archivos a un máximo de 20 MB.",
            )
            return

        presets = self.config.get("presets", {})
        owner_username = presets.get("owner_username", "admin")
        target_cloud = presets.get("target_cloud", "auto")

        self.send_message(
            chat_id,
            f"📥 <b>Recibiendo archivo:</b> <code>{filename}</code> ({file_size_mb:.2f} MB)\n"
            f"⏳ <i>Descargando y preparando subida a la nube...</i>",
        )

        local_path = self._download_telegram_file(file_id, filename)
        if not local_path or not os.path.exists(local_path):
            self.send_message(chat_id, f"❌ No se pudo recibir el archivo <code>{filename}</code> desde Telegram.")
            return

        try:
            if not self.cloud_uploader:
                self.send_message(chat_id, "❌ Módulo de nube no inicializado.")
                return

            cloud_name = target_cloud
            if target_cloud == "auto":
                active = self.cloud_uploader.get_user_providers(owner_username)
                cloud_name = active[0] if active else "la nube"

            ok, result = self.cloud_uploader.upload_file(
                filepath=local_path,
                username=owner_username,
                provider=(target_cloud if target_cloud != "auto" else None),
            )

            if ok:
                display_cloud = cloud_name.replace("_", " ").title()
                web_link = result.get("web_link") if isinstance(result, dict) else None
                cloud_filename = (result.get("filename") if isinstance(result, dict) else None) or filename

                msg = (
                    f"✅ <b>¡Archivo guardado en la nube!</b>\n\n"
                    f"📄 <b>Archivo:</b> <code>{cloud_filename}</code>\n"
                    f"☁️ <b>Destino:</b> <b>{display_cloud}</b>\n"
                )
                if web_link:
                    msg += f"🔗 <b>Enlace:</b> <a href=\"{web_link}\">Abrir en {display_cloud}</a>\n"

                msg += "\nRespaldado con éxito en el almacenamiento de dHtools. 🎉"
                self.send_message(chat_id, msg)
                logger.info("Archivo %s subido a %s para usuario %s (Link: %s)", filename, display_cloud, owner_username, web_link)
            else:
                err_msg = result.get("error") if isinstance(result, dict) else str(result)
                self.send_message(
                    chat_id,
                    f"❌ <b>Error al subir a la nube:</b>\n<code>{err_msg}</code>",
                )
        finally:
            # Limpieza del archivo temporal local para no saturar disco
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

    def _handle_auto_download(self, url: str, chat_id: Any, user_id: int, first_name: str) -> None:
        """Zero-friction download handler using owner presets."""
        if not self.manager or not hasattr(self.manager, "enqueue_download"):
            logger.error("Manager no disponible para encolar descarga.")
            self.send_message(chat_id, "❌ Error del servidor: El servicio de descargas de dHtools no está disponible.")
            return

        presets = self.config.get("presets", {})
        owner_username = presets.get("owner_username", "admin")
        quality = presets.get("default_quality", "1080p")
        format_type = presets.get("default_format", "video")
        target_cloud = presets.get("target_cloud", "auto")
        auto_cloud = presets.get("auto_upload_on_complete", True)

        extra_params: Dict[str, Any] = {
            "source": "remote_assist_telegram",
            "telegram_chat_id": chat_id,
            "telegram_user_id": user_id,
            "telegram_user_name": first_name,
            "user_cloud_sync": auto_cloud,
            "target_cloud": target_cloud,
        }

        try:
            job_result = self.manager.enqueue_download(
                url=url,
                quality=quality,
                format_type=format_type,
                owner=owner_username,
                title="",
                extra_params=extra_params,
            )

            job_id = job_result.get("job_id") if isinstance(job_result, dict) else "N/A"

            msg = (
                f"📥 <b>Descarga iniciada</b>\n\n"
                f"• <b>Formato:</b> <code>{format_type.upper()} ({quality})</code>\n"
                f"• <b>Tarea:</b> <code>{job_id}</code>\n\n"
                f"⏳ <i>Descargando... Te avisaré por aquí apenas esté completada y guardada en la nube.</i>"
            )
            self.send_message(chat_id, msg)
            logger.info("Descarga encolada para invitado %s (ID: %s, Job: %s)", first_name, user_id, job_id)

        except Exception as e:
            logger.error("Error al encolar descarga automática: %s", e)
            self.send_message(chat_id, f"❌ Error al iniciar la descarga: <code>{str(e)}</code>")

    def _execute_guest_command(
        self, cmd: str, args: List[str], chat_id: Any, user_id: int, first_name: str
    ) -> None:
        """Handles simple informational commands for authorized guests."""
        if cmd in ("/status", "/estado"):
            presets = self.config.get("presets", {})
            owner_username = presets.get("owner_username", "admin")
            if self.manager and hasattr(self.manager, "get_queue_status"):
                status_data = self.manager.get_queue_status(username=owner_username)
                active = status_data.get("active_jobs", [])
                queued = status_data.get("queued_jobs", [])
                msg = (
                    f"📊 <b>Estado de Descargas</b>\n"
                    f"• En progreso: <b>{len(active)}</b>\n"
                    f"• En espera: <b>{len(queued)}</b>\n\n"
                )
                if active:
                    for j in active[:3]:
                        msg += f"▶️ {j.get('title', 'Descargando...')} ({j.get('percent', 0)}%)\n"
                else:
                    msg += "💤 No hay descargas en curso."
                self.send_message(chat_id, msg)
            else:
                self.send_message(chat_id, "🟢 El servicio está activo y listo para recibir enlaces o archivos.")

        elif cmd in ("/help", "/ayuda"):
            self.send_message(
                chat_id,
                "💡 <b>Instrucciones:</b>\n\n"
                "• <b>Descargar videos/música:</b> Pega cualquier enlace aquí directamente.\n"
                "• <b>Subir archivos a la nube:</b> Adjunta y envía cualquier archivo (hasta 20 MB) por aquí.\n\n"
                "El bot procesará y respaldará todo automáticamente en la nube configurada.",
            )

        elif cmd in ("/ping",):
            self.send_message(chat_id, "🏓 <b>Pong!</b> Servicio activo.")

    def notify_guest_completion(
        self, chat_id: Any, title: str, cloud_name: str = "Nube", filepath: Optional[str] = None
    ) -> None:
        """Sends final success notice to the Telegram user who requested the download."""
        msg = (
            f"✅ <b>¡Descarga Completada!</b>\n\n"
            f"🎬 <b>{title}</b>\n"
            f"☁️ Guardado con éxito en: <b>{cloud_name}</b>\n\n"
            f"¡Ya está disponible en el almacenamiento! 🎉"
        )
        self.send_message(chat_id, msg)

        if self.send_media_file and filepath and os.path.exists(filepath):
            self.send_media_auto(chat_id, filepath, caption=f"📦 {title}")

    def notify_guest_error(self, chat_id: Any, title: str, error: Optional[str] = None) -> None:
        """Notifies guest if download failed."""
        msg = (
            f"❌ <b>No se pudo completar la descarga</b>\n\n"
            f"🎬 <b>{title}</b>\n"
            f"⚠️ <i>{error or 'El servidor no pudo procesar el enlace.'}</i>"
        )
        self.send_message(chat_id, msg)

    def send_message(self, chat_id: Any, text: str, parse_mode: str = "HTML") -> bool:
        """Sends an HTML text message to a specific chat/channel."""
        if not self.bot_token:
            return False
        target_chat = chat_id or self.default_chat_id
        if not target_chat:
            return False

        url = f"{self.API_BASE}{self.bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }

        try:
            resp = self._session.post(url, json=payload, timeout=15)
            return bool(resp.status_code == 200 and resp.json().get("ok"))
        except Exception as e:
            logger.error("Excepción al enviar mensaje a Telegram: %s", e)
            return False

    def send_media_auto(self, chat_id: Any, filepath: str, caption: str = "") -> bool:
        """Sends media file if <= 50MB."""
        if not self.bot_token or not filepath or not os.path.exists(filepath):
            return False
        target_chat = chat_id or self.default_chat_id
        if not target_chat:
            return False

        try:
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            filename = os.path.basename(filepath)

            if file_size_mb > self.max_media_size_mb:
                return False

            ext = os.path.splitext(filename)[1].lower()
            endpoint = "sendVideo" if ext in {".mp4", ".mkv", ".webm"} else "sendDocument"
            file_field = "video" if endpoint == "sendVideo" else "document"

            url = f"{self.API_BASE}{self.bot_token}/{endpoint}"
            data = {"chat_id": target_chat, "caption": caption, "parse_mode": "HTML"}

            with open(filepath, "rb") as f:
                resp = self._session.post(url, data=data, files={file_field: (filename, f)}, timeout=120)
            return bool(resp.status_code == 200 and resp.json().get("ok"))
        except Exception as e:
            logger.error("Error al enviar archivo por Telegram: %s", e)
            return False
