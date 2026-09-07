document.addEventListener('DOMContentLoaded', () => {
  const toast = document.getElementById('toast');
  const presetsForm = document.getElementById('presets-form');
  const btnCreateInvite = document.getElementById('btn-create-invite');
  const inviteResultBox = document.getElementById('invite-result-box');
  const generatedUrlInput = document.getElementById('generated-url');
  const btnCopyUrl = document.getElementById('btn-copy-url');
  const usersTableBody = document.getElementById('users-table-body');
  const testButtons = document.querySelectorAll('.btn-test');

  function showToast(message, type = 'info', duration = 3500) {
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast ${type}`;
    toast.classList.remove('hidden');

    setTimeout(() => {
      toast.classList.add('hidden');
    }, duration);
  }

  // -------------------------------------------------------------
  // 1. Guardar Presets del Dueño
  // -------------------------------------------------------------
  if (presetsForm) {
    presetsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn-save-presets');
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Guardando...';

      const payload = {
        owner_username: document.getElementById('owner_username').value,
        default_quality: document.getElementById('default_quality').value,
        default_format: document.getElementById('default_format').value,
        target_cloud: document.getElementById('target_cloud').value,
        auto_upload_on_complete: document.getElementById('auto_upload').checked,
      };

      try {
        const resp = await fetch('/plugin/remote_assist/api/presets/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
          showToast('✅ Presets de descarga y nube guardados.', 'success');
        } else {
          showToast(`❌ Error: ${data.message || 'No se pudieron guardar los presets'}`, 'error');
        }
      } catch (err) {
        showToast(`❌ Error de red: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  }

  // -------------------------------------------------------------
  // 1.5. Configuración del Bot de Telegram (Cifrado en Reposo)
  // -------------------------------------------------------------
  const botConfigForm = document.getElementById('bot-config-form');
  const btnToggleToken = document.getElementById('btn-toggle-token');
  const botTokenInput = document.getElementById('bot_token');
  const btnTestBot = document.getElementById('btn-test-bot');
  const botStatusIndicator = document.getElementById('bot-status-indicator');

  if (btnToggleToken && botTokenInput) {
    btnToggleToken.addEventListener('click', () => {
      if (botTokenInput.type === 'password') {
        botTokenInput.type = 'text';
        btnToggleToken.textContent = '🔒';
      } else {
        botTokenInput.type = 'password';
        btnToggleToken.textContent = '👁️';
      }
    });
  }

  if (botConfigForm) {
    botConfigForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn-save-bot-config');
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Guardando y Cifrando...';

      const payload = {
        enabled: document.getElementById('bot_enabled').checked,
        bot_token: document.getElementById('bot_token').value,
        chat_id: document.getElementById('bot_chat_id').value,
        send_media_file: document.getElementById('send_media_file').checked,
        max_media_size_mb: parseInt(document.getElementById('max_media_size').value, 10) || 50,
      };

      try {
        const resp = await fetch('/plugin/remote_assist/api/bot-config/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await resp.json();
        if (resp.ok && data.success) {
          showToast('🔒 ' + data.message, 'success');
          if (data.masked_token) {
            botTokenInput.value = data.masked_token;
          }
          if (botStatusIndicator) {
            const statusText = data.bot_username 
              ? `@${data.bot_username} (Conectado)` 
              : (data.telegram_running ? 'Activo' : 'Detenido');
            botStatusIndicator.innerHTML = `Estado: <b>${statusText}</b>`;
          }
        } else {
          showToast(`❌ Error: ${data.message || 'No se pudo guardar la configuración'}`, 'error');
        }
      } catch (err) {
        showToast(`❌ Error de red: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  }

  if (btnTestBot) {
    btnTestBot.addEventListener('click', async () => {
      const originalText = btnTestBot.textContent;
      btnTestBot.disabled = true;
      btnTestBot.textContent = 'Probando...';

      try {
        const resp = await fetch('/plugin/remote_assist/api/test-channel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ channel: 'telegram' }),
        });

        const data = await resp.json();
        if (resp.ok && data.success) {
          showToast(`✅ ${data.message}`, 'success', 4500);
        } else {
          showToast(`❌ ${data.message || 'Error en la conexión con el bot'}`, 'error', 4500);
        }
      } catch (err) {
        showToast(`❌ Error al conectar: ${err.message}`, 'error');
      } finally {
        btnTestBot.disabled = false;
        btnTestBot.textContent = originalText;
      }
    });
  }

  // -------------------------------------------------------------
  // 2. Generar Enlace de Invitación
  // -------------------------------------------------------------
  if (btnCreateInvite) {
    btnCreateInvite.addEventListener('click', async () => {
      const noteInput = document.getElementById('invite-note');
      const usesInput = document.getElementById('invite-uses');
      const originalText = btnCreateInvite.textContent;

      btnCreateInvite.disabled = true;
      btnCreateInvite.textContent = 'Generando...';

      try {
        const resp = await fetch('/plugin/remote_assist/api/invitations/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            note: noteInput.value,
            max_uses: parseInt(usesInput.value, 10) || 1,
          }),
        });

        const data = await resp.json();
        if (resp.ok && data.success) {
          generatedUrlInput.value = data.invite_url;
          inviteResultBox.classList.remove('hidden');
          showToast('✨ Enlace de invitación generado con éxito.', 'success');
          noteInput.value = '';
        } else {
          showToast('❌ Error al generar enlace de invitación.', 'error');
        }
      } catch (err) {
        showToast(`❌ Error de conexión: ${err.message}`, 'error');
      } finally {
        btnCreateInvite.disabled = false;
        btnCreateInvite.textContent = originalText;
      }
    });
  }

  // -------------------------------------------------------------
  // 3. Copiar Enlace al Portapapeles
  // -------------------------------------------------------------
  if (btnCopyUrl && generatedUrlInput) {
    btnCopyUrl.addEventListener('click', () => {
      generatedUrlInput.select();
      navigator.clipboard.writeText(generatedUrlInput.value).then(
        () => {
          showToast('📋 ¡Enlace copiado al portapapeles!', 'success');
        },
        () => {
          showToast('⚠️ No se pudo copiar automáticamente. Cópialo manualmente.', 'error');
        }
      );
    });
  }

  // -------------------------------------------------------------
  // 4. Revocar Usuario Autorizado
  // -------------------------------------------------------------
  if (usersTableBody) {
    usersTableBody.addEventListener('click', async (e) => {
      const revokeBtn = e.target.closest('.btn-revoke');
      if (!revokeBtn) return;

      const userId = revokeBtn.getAttribute('data-user-id');
      if (!confirm(`¿Estás seguro de que deseas revocar el acceso a este usuario (ID: ${userId})?`)) {
        return;
      }

      revokeBtn.disabled = true;
      revokeBtn.textContent = 'Revocando...';

      try {
        const resp = await fetch('/plugin/remote_assist/api/users/revoke', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId }),
        });

        const data = await resp.json();
        if (resp.ok && data.success) {
          showToast('🚫 Acceso revocado exitosamente.', 'success');
          const row = revokeBtn.closest('tr');
          if (row) {
            const pill = row.querySelector('.status-pill');
            if (pill) {
              pill.className = 'status-pill danger';
              pill.textContent = 'Revocado';
            }
            revokeBtn.parentElement.innerHTML = '<span class="text-muted text-sm">Acceso bloqueado</span>';
          }
        } else {
          showToast(`❌ Error: ${data.message || 'No se pudo revocar el acceso'}`, 'error');
          revokeBtn.disabled = false;
          revokeBtn.textContent = '🚫 Revocar';
        }
      } catch (err) {
        showToast(`❌ Error de red: ${err.message}`, 'error');
        revokeBtn.disabled = false;
        revokeBtn.textContent = '🚫 Revocar';
      }
    });
  }

  // -------------------------------------------------------------
  // 5. Botones de Prueba de Canales
  // -------------------------------------------------------------
  testButtons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      const channel = btn.getAttribute('data-channel');
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Enviando...';

      try {
        const response = await fetch('/plugin/remote_assist/api/test-channel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ channel: channel }),
        });

        const data = await response.json();
        if (response.ok && data.success) {
          showToast(`✅ ${channel.toUpperCase()}: ${data.message || 'Prueba exitosa'}`, 'success');
        } else {
          showToast(`❌ ${channel.toUpperCase()}: ${data.message || 'Error en prueba'}`, 'error');
        }
      } catch (err) {
        showToast(`❌ Error de conexión: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });

  // -------------------------------------------------------------
  // 6. Comprobar Actualizaciones desde GitHub
  // -------------------------------------------------------------
  const btnCheckUpdate = document.getElementById('btn-check-update');
  if (btnCheckUpdate) {
    btnCheckUpdate.addEventListener('click', async () => {
      const originalText = btnCheckUpdate.textContent;
      btnCheckUpdate.disabled = true;
      btnCheckUpdate.textContent = 'Comprobando...';

      try {
        const resp = await fetch('/plugin/remote_assist/api/check-update');
        const data = await resp.json();
        if (resp.ok && data.success) {
          if (data.has_update) {
            showToast(`🎉 ¡Nueva versión ${data.remote_version} disponible en GitHub!`, 'warning', 6000);
          } else {
            showToast(`✅ El plugin está al día (v${data.current_version}).`, 'success');
          }
        } else {
          showToast(`⚠️ No se pudo comprobar: ${data.error || 'Error de red'}`, 'error');
        }
      } catch (err) {
        showToast(`❌ Error al conectar: ${err.message}`, 'error');
      } finally {
        btnCheckUpdate.disabled = false;
        btnCheckUpdate.textContent = originalText;
      }
    });
  }
});
