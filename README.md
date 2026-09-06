# 📡 Remote Assist — Asistente Delegado de Descargas y Nube para dHtools [EXPERIMENTAL]

Plugin modular, desacoplado y multi-plataforma para **dHtools** (Python 3.11 / Flask / Docker Compose).
Opera como un **Servicio Delegado de Descarga y Nube**:
- **El Dueño (Usuario de dHtools):** Define presets fijos de descarga (calidad/formato), selecciona la nube de destino (Google Drive, OneDrive, etc.) y genera enlaces de invitación revocables.
- **Los Invitados (Amigos/Familiares/Clientes):** Ingresan mediante su enlace único (`t.me/Bot?start=inv_...`) y solo envían enlaces de video/audio directamente por chat. El bot automatiza la descarga en dHtools, sube el archivo a la nube del dueño y confirma al invitado cuando esté completado.
- **Protección Anti-Scraping / Anti-Búsquedas:** Si un desconocido encuentra el bot en el buscador de Telegram o mediante crawlers, el bot permanece como un muro cerrado y no procesa nada sin un token de invitación válido.

---

## 📂 Estructura del Plugin

Todo el código está encapsulado estrictamente dentro de `plugins/remote_assist/`:

```text
plugins/remote_assist/
├── plugin.json                 # Manifiesto oficial del plugin (SDK v1.0.0)
├── plugin.py                   # Clase principal Plugin, hooks del ciclo de vida y navegación
├── config.json                 # Configuración activa cifrada en disco (ignorado en git)
├── config.example.json         # Plantilla documentada de configuración
├── whitelist.json              # Base de datos local de invitados y tokens (ignorado en git)
├── .secret.key                 # Llave criptográfica AES-128 (ignorado estrictamente en git)
├── core/
│   ├── __init__.py
│   ├── crypto.py               # Cifrado simétrico en reposo (Fernet AES-128-CBC + HMAC-SHA256)
│   ├── access_manager.py       # Gestor dinámico de invitaciones, whitelist y revocación
│   ├── telegram_bot.py         # Bot autónomo (invitaciones, descargas y subida de archivos)
│   ├── channels.py             # Notificaciones multi-canal (Telegram, WhatsApp, Discord)
│   └── cloud_uploader.py       # Integración oficial: upload_job_to_cloud y upload_file_to_cloud
├── templates/
│   └── index.html              # Panel web: Configuración cifrada del bot, presets y lista blanca
└── static/
    ├── css/style.css           # Estilos modernos Dark-Mode / Glassmorphism
    └── js/main.js              # Lógica para bot, guardar presets, generar links y revocar
```

---

## 🔄 Flujo de Trabajo

```text
1. [Dueño en dHtools Web]  ──>  Configura token y chat del bot (cifrados automáticamente con AES).
                                Elige presets: 1080p, Video, Google Drive.
                                Genera enlace: https://t.me/TuBot?start=inv_abc123

2. [Invitado en Telegram]   ──>  Hace clic en el enlace y pulsa "Iniciar".
                                El bot le da la bienvenida: "Autorizado por Hernán".

3. [Uso Cotidiano]          ──>  El invitado puede:
                                  A) Pegar un enlace (YouTube, TikTok...) -> dHtools lo descarga.
                                  B) Adjuntar un archivo (PDF, video, imagen...) -> dHtools lo sube a la nube.

4. [dHtools Core]           ──>  Procesa la descarga o recibe el archivo por streaming.
                                Sube el archivo a Google Drive / OneDrive (nube del dueño).

5. [Confirmación]           ──>  El bot avisa al invitado:
                                "✅ ¡Archivo guardado en Google Drive con éxito!"
```

---

## 🔒 Cifrado Seguro de Credenciales en Reposo

El plugin implementa un estándar estricto de seguridad para almacenar tokens y credenciales de Telegram:
* **Cifrado Simétrico AES-128-CBC + HMAC-SHA256 (`Fernet`):** Los campos sensibles (`bot_token`, `chat_id`, etc.) nunca se guardan en texto claro en `config.json`. En su lugar, se almacenan con el prefijo `enc:<ciphertext_base64>`.
* **Llave Criptográfica Local (`.secret.key`):** Generada automáticamente en el primer inicio y protegida contra exclusión accidental en `.gitignore`.
* **Enmascaramiento en la Interfaz Web:** El token nunca se expone en texto plano en la vista HTML; se renderiza como `123456••••••••••••••••7890`. El usuario puede pulsar 👁️ para editarlo o conservarlo intacto sin revelar su valor real.
* **Descifrado en Memoria RAM:** Las credenciales solo se descifran en memoria durante el ciclo de vida del proceso en tiempo de ejecución.

---

## 🛡️ Seguridad Anti-Scraping y Anti-Búsquedas en Telegram

1. **Sin Enlace = Sin Acceso:**  
   Si un usuario o bot-crawler encuentra el `@username` de tu bot en el buscador global de Telegram y presiona `/start`, el bot responde:  
   `⛔ Este es un servicio privado. Requiere un enlace de invitación válido.`
2. **Uso Único:**  
   Los tokens de invitación (`inv_...`) pueden configurarse para 1 solo uso, evitando que el enlace sea compartido con terceros no autorizados.
3. **Revocación Inmediata:**  
   Desde el panel web `/plugin/remote_assist/`, puedes revocar el acceso a cualquier usuario con un solo clic. Su siguiente enlace será rechazado inmediatamente.

---

## ⚙️ Panel de Control Web (`/plugin/remote_assist/`)

El plugin inyecta un acceso directo en el sidebar de dHtools. Desde el panel puedes:
* **🤖 Configurar el Bot de Telegram:**
  * Habilitar o detener el servicio en segundo plano.
  * Ingresar o actualizar el API Token de @BotFather con visualización protegida y botón para mostrar/ocultar (👁️).
  * Configurar ID de chat o canal para avisos administrativos.
  * Habilitar reenvío de archivos al chat con límite configurable en megabytes (hasta 50 MB).
  * Botón **"💾 Guardar y Reiniciar Bot"** (aplica cambios en caliente sin reiniciar dHtools).
  * Botón **"🧪 Probar Conexión"** para validar el token y la comunicación con Telegram.
* **⚙️ Configurar Presets del Dueño:**
  * Usuario de dHtools propietario de las descargas y la nube.
  * Calidad por defecto (`best`, `1080p`, `720p`, `480p`, `audio_320`).
  * Formato (`video`, `audio`).
  * Nube de destino (selecciona entre las nubes activas de tu usuario).
  * Auto-subida a la nube al terminar.
* **🎟️ Crear Enlaces de Invitación:**
  * Define una nota (ej: *"Para María"*) y el límite de usos (1 uso, 3 usos, ilimitado).
  * Botón para copiar el enlace generado con un clic.
* **👥 Gestionar la Lista Blanca:**
  * Tabla interactiva con el nombre del usuario de Telegram, su User ID y la fecha de ingreso.
  * Botón rojo **Revocar** para bloquear el acceso en cualquier momento.

---

## 🧪 Pruebas Automatizadas

Para validar toda la lógica de invitaciones, lista blanca, presets, cifrado seguro y descarga automática:
```bash
python tests/test_plugin.py
```
Resultado:
```text
Ran 10 tests in 0.120s
OK
```

