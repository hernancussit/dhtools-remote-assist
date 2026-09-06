"""
Multi-channel notification dispatcher for Remote Assist plugin (dHtools).
Supports Telegram, WhatsApp (Evolution API, Twilio, generic), and Discord/Webhooks.
"""

import os
import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("dHtools.Plugin.RemoteAssist.Channels")


class NotificationDispatcher:
    """Dispatches event notifications to all configured messaging platforms."""

    def __init__(self, config: Dict[str, Any], telegram_bot: Any = None):
        self.config = config
        self.telegram_bot = telegram_bot
        self._session = requests.Session()

    def update_config(self, new_config: Dict[str, Any]) -> None:
        self.config = new_config

    # -------------------------------------------------------------
    # High-level Event Handlers
    # -------------------------------------------------------------

    def notify_download_complete(self, job_data: Dict[str, Any]) -> None:
        """Dispatches download completion notification across all active channels."""
        title = job_data.get("title") or job_data.get("filename") or "Descarga sin título"
        filename = job_data.get("filename") or (os.path.basename(job_data.get("filepath", "")) if job_data.get("filepath") else "archivo")
        filepath = job_data.get("filepath", "")
        quality = job_data.get("quality", "N/A")
        format_type = job_data.get("format_type", "auto")
        owner = job_data.get("owner", "dHtools")
        url = job_data.get("url", "")

        size_text = ""
        if filepath and os.path.exists(filepath):
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            size_text = f" ({size_mb:.2f} MB)"

        # 1. Telegram
        tg_conf = self.config.get("telegram", {})
        if tg_conf.get("enabled") and tg_conf.get("notify_on_complete", True) and self.telegram_bot:
            caption = (
                f"✅ <b>Descarga Completada con Éxito</b>\n\n"
                f"🎬 <b>Título:</b> {title}\n"
                f"📦 <b>Archivo:</b> <code>{filename}</code>{size_text}\n"
                f"⚙️ <b>Calidad:</b> {quality} | <b>Formato:</b> {format_type}\n"
                f"👤 <b>Solicitado por:</b> {owner}\n"
            )
            if url:
                caption += f"🔗 <b>Origen:</b> <a href=\"{url}\">Ver enlace</a>\n"

            # Si está configurado para enviar archivo físico y el archivo existe
            if tg_conf.get("send_media_file", True) and filepath and os.path.exists(filepath):
                self.telegram_bot.send_media_auto(chat_id=None, filepath=filepath, caption=caption)
            else:
                self.telegram_bot.send_message(chat_id=None, text=caption)

        # 2. WhatsApp
        wa_conf = self.config.get("whatsapp", {})
        if wa_conf.get("enabled") and wa_conf.get("notify_on_complete", True):
            wa_text = (
                f"✅ *dHtools - Descarga Completada*\n\n"
                f"🎬 *Título:* {title}\n"
                f"📦 *Archivo:* {filename}{size_text}\n"
                f"⚙️ *Calidad:* {quality} | *Formato:* {format_type}\n"
                f"👤 *Usuario:* {owner}"
            )
            self._send_whatsapp(wa_text, filepath=filepath)

        # 3. Discord / Webhook
        discord_conf = self.config.get("discord_webhook", {})
        if discord_conf.get("enabled") and discord_conf.get("notify_on_complete", True):
            self._send_discord_webhook(
                title=f"✅ Descarga Completada: {title}",
                description=f"Se ha completado la descarga del archivo `{filename}`.",
                color=0x2ECC71,  # Verde
                fields=[
                    {"name": "Calidad", "value": str(quality), "inline": True},
                    {"name": "Formato", "value": str(format_type), "inline": True},
                    {"name": "Tamaño", "value": size_text.strip(" ()") or "N/A", "inline": True},
                    {"name": "Usuario", "value": str(owner), "inline": True},
                    {"name": "Enlace", "value": url or "N/A", "inline": False},
                ],
            )

    def notify_download_error(self, job_data: Dict[str, Any], error: Optional[str] = None) -> None:
        """Dispatches error notification across all active channels."""
        title = job_data.get("title") or job_data.get("url") or "Descarga desconocida"
        url = job_data.get("url", "")
        owner = job_data.get("owner", "dHtools")
        err_msg = str(error or job_data.get("error") or "Fallo desconocido durante la descarga.")

        # 1. Telegram
        tg_conf = self.config.get("telegram", {})
        if tg_conf.get("enabled") and tg_conf.get("notify_on_error", True) and self.telegram_bot:
            text = (
                f"❌ <b>Error en Descarga dHtools</b>\n\n"
                f"🎬 <b>Objetivo:</b> {title}\n"
                f"👤 <b>Solicitado por:</b> {owner}\n"
            )
            if url:
                text += f"🔗 <b>URL:</b> <code>{url}</code>\n"
            text += f"⚠️ <b>Detalle del error:</b>\n<code>{err_msg[:400]}</code>"
            self.telegram_bot.send_message(chat_id=None, text=text)

        # 2. WhatsApp
        wa_conf = self.config.get("whatsapp", {})
        if wa_conf.get("enabled") and wa_conf.get("notify_on_error", True):
            wa_text = (
                f"❌ *dHtools - Error en Descarga*\n\n"
                f"🎬 *Objetivo:* {title}\n"
                f"👤 *Usuario:* {owner}\n"
                f"⚠️ *Error:* {err_msg[:300]}"
            )
            self._send_whatsapp(wa_text)

        # 3. Discord
        discord_conf = self.config.get("discord_webhook", {})
        if discord_conf.get("enabled") and discord_conf.get("notify_on_error", True):
            self._send_discord_webhook(
                title=f"❌ Error en Descarga: {title}",
                description=f"```\n{err_msg[:800]}\n```",
                color=0xE74C3C,  # Rojo
                fields=[
                    {"name": "Usuario", "value": str(owner), "inline": True},
                    {"name": "URL", "value": url or "N/A", "inline": False},
                ],
            )

    # -------------------------------------------------------------
    # WhatsApp Provider Handlers
    # -------------------------------------------------------------

    def _send_whatsapp(self, text: str, filepath: Optional[str] = None) -> bool:
        """Sends WhatsApp message according to configured provider."""
        wa_conf = self.config.get("whatsapp", {})
        provider = wa_conf.get("provider", "evolution_api").lower()
        api_url = wa_conf.get("api_url", "").strip()
        api_key = wa_conf.get("api_key", "").strip()
        recipient = wa_conf.get("recipient_number", "").strip()

        if not api_url or not recipient:
            logger.warning("WhatsApp configurado pero faltan api_url o recipient_number.")
            return False

        try:
            if provider == "evolution_api":
                # Soporte estándar para Evolution API v1 / v2
                headers = {"apikey": api_key, "Content-Type": "application/json"}
                payload = {
                    "number": recipient,
                    "options": {"delay": 1200, "presence": "composing"},
                    "textMessage": {"text": text},
                }
                resp = self._session.post(api_url, json=payload, headers=headers, timeout=15)
                return resp.status_code in (200, 201)

            elif provider == "twilio":
                # Soporte para Twilio WhatsApp API
                # api_url format: https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json
                # api_key format: AccountSid:AuthToken
                if ":" in api_key:
                    account_sid, auth_token = api_key.split(":", 1)
                    auth = (account_sid, auth_token)
                else:
                    auth = None

                data = {
                    "From": "whatsapp:+14155238886",  # Twilio sandbox / business number
                    "To": f"whatsapp:{recipient if recipient.startswith('+') else '+' + recipient}",
                    "Body": text,
                }
                resp = self._session.post(api_url, data=data, auth=auth, timeout=15)
                return resp.status_code in (200, 201)

            else:
                # Webhook HTTP genérico
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                payload = {"recipient": recipient, "message": text, "filepath": filepath}
                resp = self._session.post(api_url, json=payload, headers=headers, timeout=15)
                return resp.status_code in (200, 201, 204)

        except Exception as e:
            logger.error("Error al enviar mensaje por WhatsApp (%s): %s", provider, e)
            return False

    # -------------------------------------------------------------
    # Discord / Generic Webhook Handler
    # -------------------------------------------------------------

    def _send_discord_webhook(
        self, title: str, description: str, color: int = 0x3498DB, fields: Optional[list] = None
    ) -> bool:
        """Sends rich embed payload to a Discord webhook URL."""
        discord_conf = self.config.get("discord_webhook", {})
        webhook_url = discord_conf.get("webhook_url", "").strip()
        if not webhook_url:
            return False

        payload = {
            "username": "dHtools Remote Assist",
            "avatar_url": "https://raw.githubusercontent.com/dHtools/assets/main/icon.png",
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                    "fields": fields or [],
                    "footer": {"text": "dHtools Automated Notification System"},
                }
            ],
        }

        try:
            resp = self._session.post(webhook_url, json=payload, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error("Error al enviar notificación a Discord Webhook: %s", e)
            return False

    def send_test(self, channel: str) -> Dict[str, Any]:
        """Triggers a test notification to verify channel credentials."""
        dummy_job = {
            "title": "Video de Prueba dHtools",
            "filename": "prueba_dhtools.mp4",
            "filepath": "",
            "quality": "1080p",
            "format_type": "mp4",
            "owner": "Admin Tester",
            "url": "https://dhtools.local",
        }

        if channel == "telegram":
            if not self.telegram_bot or not self.telegram_bot.is_enabled:
                return {"success": False, "message": "Bot de Telegram no está habilitado o falta token."}
            ok = self.telegram_bot.send_message(
                chat_id=None,
                text="🔔 <b>Mensaje de Prueba</b>\nEl plugin <i>Remote Assist</i> de dHtools está configurado correctamente en Telegram.",
            )
            return {"success": ok, "message": "Enviado con éxito" if ok else "Error al enviar mensaje"}

        elif channel == "whatsapp":
            ok = self._send_whatsapp("🔔 *Mensaje de Prueba*: dHtools Remote Assist conectado con éxito a WhatsApp.")
            return {"success": ok, "message": "Petición enviada al proveedor de WhatsApp" if ok else "Error al conectar con WhatsApp"}

        elif channel == "discord":
            ok = self._send_discord_webhook(
                title="🔔 Mensaje de Prueba",
                description="Conexión exitosa desde dHtools Remote Assist.",
                color=0x3498DB,
            )
            return {"success": ok, "message": "Notificación enviada a Discord" if ok else "Error al enviar a Discord"}

        return {"success": False, "message": f"Canal '{channel}' no reconocido"}
