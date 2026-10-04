package com.example.tars;

import android.content.Context;
import android.content.Intent;
import android.util.Log;
import com.getcapacitor.JSObject;
import com.getcapacitor.NativePlugin;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;

@NativePlugin
public class TarsPlugin extends Plugin {
    private static final String TAG = "TarsPlugin";
    private Thread backendThread = null;
    private Process backendProcess = null;
    
    @PluginMethod
    public void startBackend(PluginCall call) {
        Context context = getContext();
        
        // Vérifier si le backend est déjà démarré
        if (backendProcess != null && backendProcess.isAlive()) {
            Log.d(TAG, "Backend déjà en cours d'exécution");
            call.success();
            return;
        }
        
        // Démarrer le backend dans un thread séparé
        backendThread = new Thread(() -> {
            try {
                // Copier Tars.py dans les assets
                // Note: En pratique, il faudrait inclure Tars.py dans les assets et utiliser un runtime Python
                // Pour simplifier, on suppose que Termux est installé et que Tars.py est disponible
                
                // Méthode 1: Via Termux (nécessite Termux installé)
                Intent intent = new Intent();
                intent.setClassName("com.termux", "com.termux.app.RunCommandService");
                intent.setAction("com.termux.RUN_COMMAND");
                intent.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.example.tars/files/app/Tars.py");
                intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
                intent.putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "com.termux.RUN_COMMAND");
                context.startService(intent);
                
                call.success();
            } catch (Exception e) {
                Log.e(TAG, "Erreur lors du démarrage du backend: " + e.getMessage());
                call.error("Termux non installé ou erreur: " + e.getMessage());
            }
        });
        backendThread.start();
    }
    
    @PluginMethod
    public void stopBackend(PluginCall call) {
        if (backendProcess != null) {
            backendProcess.destroy();
            backendProcess = null;
        }
        if (backendThread != null) {
            backendThread.interrupt();
            backendThread = null;
        }
        call.success();
    }
    
    @PluginMethod
    public void isBackendRunning(PluginCall call) {
        boolean running = backendProcess != null && backendProcess.isAlive();
        JSObject ret = new JSObject();
        ret.put("running", running);
        call.success(ret);
    }
    
    @Override
    public void onDestroy() {
        stopBackend(null);
        super.onDestroy();
    }
}
