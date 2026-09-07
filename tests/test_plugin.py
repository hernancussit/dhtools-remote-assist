"""
Unit and integration tests for dHtools Remote Assist Plugin.
Covers access management, invitations, auto-downloads, presets,
and direct file uploads to cloud.
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, WORKSPACE_ROOT)
sys.path.insert(0, os.path.join(WORKSPACE_ROOT, "plugins"))

from plugins.remote_assist.plugin import Plugin
from plugins.remote_assist.core.telegram_bot import TelegramBot
from plugins.remote_assist.core.access_manager import AccessManager
from plugins.remote_assist.core.cloud_uploader import CloudUploader
from plugins.remote_assist.core.crypto import CryptoManager
from flask import Flask


class MockCloudPlugin:
    """Simula un plugin de almacenamiento en la nube de dHtools (ej: Google Drive)."""
    def __init__(self):
        self.uploaded_files = []

    def upload_file_for_user(self, filepath: str, username: str):
        self.uploaded_files.append({"filepath": filepath, "username": username})
        return True, "Archivo subido exitosamente a Google Drive"


class MockPluginManager:
    """Simula la interfaz oficial de PluginManager de dHtools."""

    def __init__(self):
        self.enqueued_jobs = []
        self.cloud_uploads = []
        self.direct_files = []
        self.user_clouds = {
            "hernan": ["google_drive", "onedrive"],
            "admin": ["nextcloud"],
        }
        self.cloud_plugin_instances = {
            "google_drive": MockCloudPlugin(),
        }
        self.restart_called = False
        self.restart_delay = None

    def restart_process(self, delay: float = 1.5):
        self.restart_called = True
        self.restart_delay = delay

    def enqueue_download(
        self,
        url: str,
        quality: str = "best",
        format_type: str = "video",
        owner: str = "admin",
        title: str = "",
        extra_params: dict = None,
    ):
        job = {
            "job_id": f"job_{len(self.enqueued_jobs) + 1}",
            "url": url,
            "quality": quality,
            "format_type": format_type,
            "owner": owner,
            "title": title or "Descarga",
            "extra_params": extra_params or {},
            "status": "queued",
        }
        self.enqueued_jobs.append(job)
        return job

    def get_queue_status(self, username: str = None):
        return {
            "active_jobs": [],
            "queued_jobs": self.enqueued_jobs,
            "total_active": 0,
            "total_queued": len(self.enqueued_jobs),
            "total": len(self.enqueued_jobs),
        }

    def get_user_cloud_providers(self, username: str):
        return self.user_clouds.get(username, [])

    def upload_job_to_cloud(self, plugin_id: str, job_id: str, username: str, progress_callback=None):
        self.cloud_uploads.append({"plugin_id": plugin_id, "job_id": job_id, "username": username})
        return True, f"Subida despachada hacia {plugin_id} para {username}"

    def upload_file_to_cloud(self, plugin_id: str, filepath: str, username: str):
        filename = os.path.basename(filepath)
        self.direct_files.append({"plugin_id": plugin_id, "filepath": filepath, "username": username})
        return True, {
            "web_link": f"https://drive.google.com/file/d/{filename}/view",
            "filename": filename,
            "plugin_id": plugin_id,
        }

    def get_plugin_instance(self, plugin_id: str):
        return self.cloud_plugin_instances.get(plugin_id)


class TestRemoteAssistDelegatedAssistant(unittest.TestCase):

    def setUp(self):
        self.plugin_dir = os.path.join(WORKSPACE_ROOT, "plugins", "remote_assist")
        self.whitelist_file = os.path.join(self.plugin_dir, "whitelist.json")
        self.config_file = os.path.join(self.plugin_dir, "config.json")
        self.secret_key_file = os.path.join(self.plugin_dir, ".secret.key")

        self.initial_config = None
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.initial_config = f.read()
            except Exception:
                pass

    def tearDown(self):
        if os.path.exists(self.whitelist_file):
            try:
                os.remove(self.whitelist_file)
            except Exception:
                pass

        if self.initial_config is not None:
            try:
                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(self.initial_config)
            except Exception:
                pass

        if os.path.exists(self.secret_key_file):
            try:
                os.remove(self.secret_key_file)
            except Exception:
                pass

    def test_01_access_manager_invitations_and_revocation(self):
        am = AccessManager(self.plugin_dir, static_allowed_ids=[999999])
        self.assertTrue(am.is_authorized(999999))
        self.assertFalse(am.is_authorized(12345))

        token = am.create_invitation(max_uses=1, note="Para Maria")
        self.assertTrue(token.startswith("inv_"))

        ok, _ = am.validate_and_use_invitation(token, user_id=12345, first_name="Maria", username="maria_tg")
        self.assertTrue(ok)
        self.assertTrue(am.is_authorized(12345))

        # Reutilización bloqueada
        ok2, _ = am.validate_and_use_invitation(token, user_id=67890, first_name="Pedro")
        self.assertFalse(ok2)

        # Revocación
        rev_ok = am.revoke_user(12345)
        self.assertTrue(rev_ok)
        self.assertFalse(am.is_authorized(12345))

    def test_02_bot_invitation_welcome_and_stranger_rejection(self):
        config = {
            "enabled": True,
            "bot_token": "TEST_TOKEN",
            "chat_id": "12345",
            "presets": {"owner_username": "hernan"},
        }
        mock_manager = MockPluginManager()
        am = AccessManager(self.plugin_dir)
        bot = TelegramBot(config=config, manager=mock_manager, access_manager=am)

        # Extraño sin token
        with patch.object(bot, "send_message") as mock_send:
            bot._handle_start(chat_id=111, user_id=111, first_name="Curioso", username="hacker", token=None)
            mock_send.assert_called_once()
            self.assertIn("Servicio Privado", mock_send.call_args[0][1])

        # Invitado con token válido
        token = am.create_invitation(max_uses=1, note="Para Carlos")
        with patch.object(bot, "send_message") as mock_send_invite:
            bot._handle_start(chat_id=222, user_id=222, first_name="Carlos", username="carlos_tg", token=token)
            mock_send_invite.assert_called_once()
            self.assertIn("Bienvenido/a Carlos", mock_send_invite.call_args[0][1])
            self.assertTrue(am.is_authorized(222))

    def test_03_zero_friction_auto_download(self):
        config = {
            "enabled": True,
            "bot_token": "TEST_TOKEN",
            "chat_id": "12345",
            "presets": {
                "owner_username": "hernan",
                "default_quality": "1080p",
                "default_format": "video",
                "target_cloud": "google_drive",
                "auto_upload_on_complete": True,
            },
        }
        mock_manager = MockPluginManager()
        am = AccessManager(self.plugin_dir)
        bot = TelegramBot(config=config, manager=mock_manager, access_manager=am)

        token = am.create_invitation(max_uses=1)
        am.validate_and_use_invitation(token, user_id=555, first_name="Juan")

        with patch.object(bot, "send_message") as mock_send:
            bot._handle_auto_download(
                url="https://youtube.com/watch?v=sample123",
                chat_id=555,
                user_id=555,
                first_name="Juan",
            )
            mock_send.assert_called_once()
            self.assertEqual(len(mock_manager.enqueued_jobs), 1)
            job = mock_manager.enqueued_jobs[0]
            self.assertEqual(job["owner"], "hernan")
            self.assertEqual(job["quality"], "1080p")
            self.assertEqual(job["extra_params"]["telegram_chat_id"], 555)

    def test_04_direct_file_upload_to_cloud(self):
        """Prueba la recepción de archivos desde Telegram y su subida directa a la nube del dueño."""
        config = {
            "enabled": True,
            "bot_token": "TEST_TOKEN",
            "chat_id": "12345",
            "presets": {
                "owner_username": "hernan",
                "target_cloud": "google_drive",
            },
        }
        mock_manager = MockPluginManager()
        am = AccessManager(self.plugin_dir)
        uploader = CloudUploader(config=config, manager=mock_manager)
        bot = TelegramBot(config=config, manager=mock_manager, cloud_uploader=uploader, access_manager=am)

        # Autorizar a Sofia
        token = am.create_invitation(max_uses=1)
        am.validate_and_use_invitation(token, user_id=777, first_name="Sofia")

        # Archivo ficticio en disco
        test_file = os.path.join(self.plugin_dir, "test_doc.pdf")
        with open(test_file, "wb") as f:
            f.write(b"%PDF-1.4 test file content")

        try:
            # Simular extracción del payload
            doc_message = {
                "document": {
                    "file_id": "file_abc123",
                    "file_name": "test_doc.pdf",
                    "file_size": len(b"%PDF-1.4 test file content"),
                }
            }
            payload = bot._extract_file_payload(doc_message)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["filename"], "test_doc.pdf")

            # Mockear _download_telegram_file para devolver nuestro test_file
            with patch.object(bot, "_download_telegram_file", return_value=test_file):
                with patch.object(bot, "send_message") as mock_send:
                    bot._handle_direct_file_upload(payload, chat_id=777, user_id=777, first_name="Sofia")

                    # Debe haber invocado upload_file_to_cloud en mock_manager
                    self.assertEqual(len(mock_manager.direct_files), 1)
                    upload_rec = mock_manager.direct_files[0]
                    self.assertEqual(upload_rec["plugin_id"], "google_drive")
                    self.assertEqual(upload_rec["username"], "hernan")

                    # Debe haber enviado confirmación a Sofia
                    self.assertTrue(mock_send.called)
                    success_msg = mock_send.call_args[0][1]
                    self.assertIn("guardado en la nube", success_msg)
                    self.assertIn("Google Drive", success_msg)
                    self.assertIn("https://drive.google.com/file/d/test_doc.pdf/view", success_msg)
        finally:
            if os.path.exists(test_file):
                try:
                    os.remove(test_file)
                except Exception:
                    pass

    def test_05_blueprint_api_invitations_and_presets(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        mock_manager = MockPluginManager()
        plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.0"})
        plugin.register_routes(app)
        client = app.test_client()

        resp_inv = client.post(
            "/plugin/remote_assist/api/invitations/create",
            json={"note": "Prueba API", "max_uses": 2},
        )
        self.assertEqual(resp_inv.status_code, 200)
        data_inv = resp_inv.get_json()
        self.assertTrue(data_inv["success"])

    @patch("requests.get")
    def test_06_github_updates_and_manifest_repository(self, mock_get):
        """Verifica que plugin.json incluya repository y branch y que el endpoint /api/check-update funcione."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"version": "2.0.0"}
        mock_get.return_value = mock_resp

        manifest_path = os.path.join(self.plugin_dir, "plugin.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertIn("repository", manifest)
        self.assertIn("branch", manifest)
        self.assertEqual(manifest["branch"], "main")
        self.assertTrue(manifest["repository"].startswith("https://github.com/"))

        app = Flask(__name__)
        app.config["TESTING"] = True
        mock_manager = MockPluginManager()
        plugin = Plugin(manager=mock_manager, metadata=manifest)
        plugin.register_routes(app)
        client = app.test_client()

        resp = client.get("/plugin/remote_assist/api/check-update")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("has_update"))
        self.assertEqual(data.get("remote_version"), "2.0.0")
        self.assertEqual(data.get("current_version"), manifest["version"])
        self.assertEqual(data.get("branch"), manifest["branch"])

    def test_07_crypto_manager_encryption_decryption_and_masking(self):
        """Verifica que CryptoManager use AES-128-CBC + HMAC y maneje prefijos enc: y enmascarado."""
        crypto = CryptoManager(self.plugin_dir)
        raw_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456"

        # Cifrado
        encrypted = crypto.encrypt(raw_token)
        self.assertTrue(encrypted.startswith("enc:"))
        self.assertNotEqual(encrypted, raw_token)

        # Idempotencia: no volver a cifrar si ya tiene enc:
        double_encrypted = crypto.encrypt(encrypted)
        self.assertEqual(double_encrypted, encrypted)

        # Descifrado
        decrypted = crypto.decrypt(encrypted)
        self.assertEqual(decrypted, raw_token)

        # Diccionario con configuración
        test_cfg = {
            "telegram": {"bot_token": raw_token, "chat_id": "987654321"},
            "presets": {"owner_username": "hernan"},
        }
        enc_cfg = crypto.encrypt_config(test_cfg)
        self.assertTrue(enc_cfg["telegram"]["bot_token"].startswith("enc:"))
        self.assertTrue(enc_cfg["telegram"]["chat_id"].startswith("enc:"))
        self.assertEqual(enc_cfg["presets"]["owner_username"], "hernan")

        dec_cfg = crypto.decrypt_config(enc_cfg)
        self.assertEqual(dec_cfg["telegram"]["bot_token"], raw_token)
        self.assertEqual(dec_cfg["telegram"]["chat_id"], "987654321")

        # Enmascaramiento para la UI
        masked = CryptoManager.mask_token(raw_token)
        self.assertTrue(masked.startswith("123456"))
        self.assertTrue(masked.endswith("3456"))
        self.assertIn("••••", masked)
        self.assertNotIn("ABCdefGHIjklMNOpqrsTUVwxyz", masked)

    def test_08_plugin_config_encrypted_at_rest_on_disk(self):
        """Verifica que al guardar la configuración con el plugin, los campos en config.json estén cifrados."""
        mock_manager = MockPluginManager()
        plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.0"})

        secret_token = "9988776655:SECRET_TOKEN_TELEGRAM_KEY"
        secret_chat = "1122334455"
        plugin.config["telegram"]["bot_token"] = secret_token
        plugin.config["telegram"]["chat_id"] = secret_chat

        # Guardar en disco
        plugin._save_config()

        # Inspeccionar config.json en disco en crudo
        with open(plugin.config_path, "r", encoding="utf-8") as f:
            raw_disk_content = f.read()
            raw_json = json.loads(raw_disk_content)

        # Asegurar que los tokens en disco están cifrados y el texto plano NO existe en el archivo
        self.assertNotIn(secret_token, raw_disk_content)
        self.assertTrue(raw_json["telegram"]["bot_token"].startswith("enc:"))
        self.assertTrue(raw_json["telegram"]["chat_id"].startswith("enc:"))

        # Al recargar, la memoria debe contener los valores descifrados transparentemente
        reloaded = plugin._load_config()
        self.assertEqual(reloaded["telegram"]["bot_token"], secret_token)
        self.assertEqual(reloaded["telegram"]["chat_id"], secret_chat)

    def test_09_api_save_bot_config_and_token_protection(self):
        """Prueba la API /api/bot-config/save y la preservación del token cuando se envía enmascarado."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        mock_manager = MockPluginManager()
        plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.0"})
        plugin.register_routes(app)
        client = app.test_client()

        # 1. Guardar nueva configuración de bot con token real
        resp = client.post(
            "/plugin/remote_assist/api/bot-config/save",
            json={
                "enabled": True,
                "bot_token": "BOT_TOKEN_XYZ_123456789",
                "chat_id": "777888",
                "send_media_file": True,
                "max_media_size_mb": 45,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("cifrada en disco", data.get("message"))
        self.assertIn("••••", data.get("masked_token"))

        # Verificar que en memoria está el token real
        self.assertEqual(plugin.config["telegram"]["bot_token"], "BOT_TOKEN_XYZ_123456789")
        self.assertEqual(plugin.config["telegram"]["max_media_size_mb"], 45)

        # 2. Guardar modificaciones subsecuentes sin cambiar el token (enviando el valor enmascarado)
        resp2 = client.post(
            "/plugin/remote_assist/api/bot-config/save",
            json={
                "enabled": True,
                "bot_token": data["masked_token"],  # El frontend reenvía el valor enmascarado
                "chat_id": "999000",
                "send_media_file": False,
                "max_media_size_mb": 30,
            },
        )
        self.assertEqual(resp2.status_code, 200)
        # El token original NO debe haber sido pisado por los puntos
        self.assertEqual(plugin.config["telegram"]["bot_token"], "BOT_TOKEN_XYZ_123456789")
        self.assertEqual(plugin.config["telegram"]["chat_id"], "999000")
        self.assertEqual(plugin.config["telegram"]["max_media_size_mb"], 30)

    @patch.object(TelegramBot, "get_me")
    def test_10_api_test_channel_telegram(self, mock_get_me):
        """Prueba el endpoint /api/test-channel para verificar la conexión con Telegram."""
        mock_get_me.return_value = {"username": "MiBotDePrueba", "id": 12345}

        app = Flask(__name__)
        app.config["TESTING"] = True
        mock_manager = MockPluginManager()
        plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.0"})
        plugin.register_routes(app)
        client = app.test_client()

        # Sin token configurado
        plugin.telegram_bot.bot_token = ""
        resp_fail = client.post("/plugin/remote_assist/api/test-channel", json={"channel": "telegram"})
        self.assertEqual(resp_fail.status_code, 400)

        # Con token y get_me mockeado
        plugin.telegram_bot.bot_token = "VALID_TOKEN"
        resp_ok = client.post("/plugin/remote_assist/api/test-channel", json={"channel": "telegram"})
        self.assertEqual(resp_ok.status_code, 200)
        data = resp_ok.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("@MiBotDePrueba", data.get("message"))

    def test_11_dashboard_namespaced_template_no_collision(self):
        """Verifica que el dashboard renderice su propia plantilla y no colisione con el index.html principal de dHtools."""
        import tempfile
        with tempfile.TemporaryDirectory() as fake_app_templates:
            with open(os.path.join(fake_app_templates, "index.html"), "w") as f:
                f.write("<html><head><title>dHtools - Suite Multimedia</title></head><body>Descargas</body></html>")

            app = Flask(__name__, template_folder=fake_app_templates)
            app.config["TESTING"] = True
            mock_manager = MockPluginManager()
            plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.0"})
            plugin.register_routes(app)
            client = app.test_client()

            # Probar con /
            resp_slash = client.get("/plugin/remote_assist/")
            self.assertEqual(resp_slash.status_code, 200)
            html_slash = resp_slash.get_data(as_text=True)
            self.assertIn("Asistente Delegado Remote Assist", html_slash)
            self.assertNotIn("dHtools - Suite Multimedia", html_slash)

            # Probar sin /
            resp_no_slash = client.get("/plugin/remote_assist")
            self.assertEqual(resp_no_slash.status_code, 200)
            html_no_slash = resp_no_slash.get_data(as_text=True)
            self.assertIn("Asistente Delegado Remote Assist", html_no_slash)

    def test_12_restart_process_sdk(self):
        """Verifica que el método restart_server y el endpoint /api/restart invoquen self.manager.restart_process."""
        mock_manager = MockPluginManager()
        plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.2"})

        # Método directo
        ok = plugin.restart_server(delay=2.0)
        self.assertTrue(ok)
        self.assertTrue(mock_manager.restart_called)
        self.assertEqual(mock_manager.restart_delay, 2.0)

        # Endpoint HTTP
        app = Flask(__name__)
        app.config["TESTING"] = True
        plugin.register_routes(app)
        client = app.test_client()

        mock_manager.restart_called = False
        resp = client.post("/plugin/remote_assist/api/restart", json={"delay": 3.0})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("3.0s", data.get("message"))
        self.assertTrue(mock_manager.restart_called)
        self.assertEqual(mock_manager.restart_delay, 3.0)

        # Sin soporte en manager
        plugin_no_manager = Plugin(manager=None, metadata={"id": "remote_assist", "version": "1.0.2"})
        self.assertFalse(plugin_no_manager.restart_server())

    def test_13_session_user_and_clean_cloud_options(self):
        """Verifica que el dashboard use la sesión activa para el dueño y formatee las nubes sin volcar diccionarios crudos."""
        mock_manager = MockPluginManager()
        # Simular retorno del SDK real de dHtools con objetos dict complejos
        mock_manager.user_clouds["pedro"] = [
            {
                "id": "google_drive",
                "name": "google drive",
                "icon": "📁",
                "enabled": False,
                "auto_upload": False,
                "status_label": "desactivado",
            }
        ]

        app = Flask(__name__)
        app.secret_key = "test_secret_key"
        app.config["TESTING"] = True
        plugin = Plugin(manager=mock_manager, metadata={"id": "remote_assist", "version": "1.0.3"})
        plugin.register_routes(app)
        client = app.test_client()

        # Establecer sesión activa de pedro
        with client.session_transaction() as sess:
            sess["username"] = "pedro"

        resp = client.get("/plugin/remote_assist/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 1. Debe aparecer pedro en el campo de solo lectura
        self.assertIn('value="pedro"', html)
        self.assertIn("readonly", html)

        # 2. El desplegable debe mostrar el icono y nombre legible, NO el diccionario crudo
        self.assertIn("📁 Google Drive (Desactivado en dHtools)", html)
        self.assertNotIn("{'id': 'google_drive'", html)

        # 3. Al guardar presets, debe forzar el usuario de la sesión aunque envíen otro
        save_resp = client.post(
            "/plugin/remote_assist/api/presets/save",
            json={
                "owner_username": "atacante_intruso",
                "default_quality": "720p",
                "target_cloud": "google_drive",
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        save_data = save_resp.get_json()
        self.assertTrue(save_data["success"])
        # El owner debe ser pedro (sesión activa), no el atacante
        self.assertEqual(save_data["presets"]["owner_username"], "pedro")


if __name__ == "__main__":
    unittest.main()
