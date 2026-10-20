const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
const crypto = require('crypto');
const { spawn } = require('child_process');

const STARTUP_TIMEOUT_MS = 15000;
const HEALTH_TIMEOUT_MS = 500;
const HEALTH_RETRY_MS = 200;

const STARTUP_HTML = `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>TARS</title>
<style>
  html, body { margin: 0; height: 100%; }
  body {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 24px;
    text-align: center;
    background: #fafafa;
    color: #1c1c1e;
    font: 14px system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .detail { color: #8a8a90; font-size: 12px; }
</style>
</head>
<body><p>TARS d&eacute;marre&hellip;</p></body>
</html>`;

const STARTUP_MARKER = '<p>TARS d&eacute;marre&hellip;</p>';

let mainWindow;
let backendProcess = null;
let startupPromise = null;
let startupGeneration = 0;
let bootLoaded = false;

function loadApp({ url, port }) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (bootLoaded) {
    mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  } else {
    bootLoaded = true;
    mainWindow.loadURL(url);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[char]);
}

function showStartupPage(message) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const content = message
    ? `<p>TARS n'a pas pu d&eacute;marrer.</p><p class="detail">${escapeHtml(message)}</p>`
    : STARTUP_MARKER;
  const html = STARTUP_HTML.replace(STARTUP_MARKER, content);
  mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 400,
    height: 700,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  showStartupPage();

  startBackend()
    .then(loadApp)
    .catch(err => {
      console.error(`Backend indisponible : ${err.message}`);
      showStartupPage(err.message);
    });
}

async function startBackend() {
  if (startupPromise) return startupPromise;

  const backendPath = path.join(__dirname, 'Tars.exe');
  if (!fs.existsSync(backendPath)) {
    return Promise.reject(new Error(`Backend non trouvé à : ${backendPath}`));
  }

  const dataDir = path.join(app.getPath('userData'), 'data');
  fs.mkdirSync(dataDir, { recursive: true });

  const port = await getFreePort();
  const token = crypto.randomBytes(32).toString('hex');
  const nonce = crypto.randomBytes(24).toString('hex');
  const generation = ++startupGeneration;

  startupPromise = new Promise((resolve, reject) => {
    let settled = false;
    let deadlineTimer = null;
    let retryTimer = null;
    let child = null;

    const clearTimers = () => {
      clearTimeout(deadlineTimer);
      clearTimeout(retryTimer);
    };

    const fail = (err) => {
      if (settled) return;
      settled = true;
      clearTimers();
      if (generation === startupGeneration) startupPromise = null;
      if (child && backendProcess === child) {
        backendProcess = null;
        try { child.kill(); } catch (e) {}
      }
      reject(err);
    };

    const succeed = () => {
      if (settled) return;
      settled = true;
      clearTimers();
      resolve({
        port,
        nonce,
        url: `http://127.0.0.1:${port}/?boot=${encodeURIComponent(nonce)}`
      });
    };

    const pollHealth = () => {
      if (settled) return;
      const req = http.get({
        host: '127.0.0.1',
        port,
        path: '/health',
        timeout: HEALTH_TIMEOUT_MS
      }, res => {
        res.resume();
        if (settled) return;
        if (res.statusCode === 200) {
          succeed();
        } else {
          retryTimer = setTimeout(pollHealth, HEALTH_RETRY_MS);
        }
      });
      req.on('timeout', () => req.destroy());
      req.on('error', () => {
        if (!settled) retryTimer = setTimeout(pollHealth, HEALTH_RETRY_MS);
      });
    };

    deadlineTimer = setTimeout(() => {
      fail(new Error("TARS n'a pas répondu dans les 15 secondes."));
    }, STARTUP_TIMEOUT_MS);

    try {
      child = spawn(backendPath, [], {
        cwd: __dirname,
        env: {
          ...process.env,
          TARS_TOKEN: token,
          TARS_BOOT_NONCE: nonce,
          TARS_PORT: String(port),
          TARS_DATA: dataDir
        },
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe']
      });
    } catch (err) {
      fail(err);
      return;
    }
    backendProcess = child;

    pollHealth();

    child.on('error', err => fail(err));

    child.stdout.on('data', data => {
      console.log(`Backend stdout: ${data}`);
    });

    child.stderr.on('data', data => {
      console.error(`Backend stderr: ${data}`);
    });

    child.on('close', code => {
      if (backendProcess === child) {
        backendProcess = null;
        bootLoaded = false;
      }
      if (!settled) {
        fail(new Error(`Backend arrêté (code ${code}) avant d'être prêt.`));
      } else {
        if (generation === startupGeneration) startupPromise = null;
        console.log(`Backend arrêté avec le code ${code}`);
      }
    });
  });

  return startupPromise;
}

function stopBackend() {
  startupGeneration++;
  if (startupPromise) startupPromise.catch(() => {});
  startupPromise = null;
  bootLoaded = false;
  if (backendProcess) {
    const child = backendProcess;
    backendProcess = null;
    try { child.kill(); } catch (e) {}
    console.log('Backend arrêté');
  }
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  stopBackend();
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// API pour le frontend
ipcMain.on('restart-backend', () => {
  stopBackend();
  startBackend()
    .then(loadApp)
    .catch(err => {
      console.error(`Redémarrage impossible : ${err.message}`);
      showStartupPage(err.message);
    });
});

ipcMain.on('get-backend-status', (event) => {
  event.returnValue = backendProcess !== null && !backendProcess.killed;
});

// Gérer les erreurs du backend
ipcMain.handle('backend-status', async () => {
  return {
    running: backendProcess !== null && !backendProcess.killed,
    pid: backendProcess ? backendProcess.pid : null
  };
});
