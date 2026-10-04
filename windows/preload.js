const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  restartBackend: () => ipcRenderer.send('restart-backend'),
  getBackendStatus: () => ipcRenderer.sendSync('get-backend-status'),
  backendStatus: () => ipcRenderer.invoke('backend-status'),
  
  // Ajouter un listener pour les mises à jour du backend
  onBackendRestarted: (callback) => {
    ipcRenderer.on('backend-restarted', () => callback());
  }
});
