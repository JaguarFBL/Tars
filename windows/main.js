const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { exec, spawn } = require('child_process');

let mainWindow;
let backendProcess = null;

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

  // Charger index.html depuis le même dossier
  mainWindow.loadFile('index.html');

  // Démarrer le backend
  startBackend();

  // Ouvrir les outils de développement (optionnel)
  // mainWindow.webContents.openDevTools();
}

function startBackend() {
  const backendPath = path.join(__dirname, 'Tars.exe');
  
  // Vérifier si Tars.exe existe
  const fs = require('fs');
  if (!fs.existsSync(backendPath)) {
    console.error(`Backend non trouvé à : ${backendPath}`);
    return;
  }
  
  // Démarrer le backend
  backendProcess = spawn(backendPath, [], {
    cwd: __dirname,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  
  backendProcess.stdout.on('data', (data) => {
    console.log(`Backend stdout: ${data}`);
  });
  
  backendProcess.stderr.on('data', (data) => {
    console.error(`Backend stderr: ${data}`);
  });
  
  backendProcess.on('close', (code) => {
    console.log(`Backend arrêté avec le code ${code}`);
    backendProcess = null;
  });
  
  console.log(`Backend démarré : ${backendPath}`);
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
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
  setTimeout(startBackend, 1000); // Attendre 1 seconde avant de redémarrer
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
