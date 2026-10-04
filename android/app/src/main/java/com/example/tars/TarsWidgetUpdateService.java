package com.example.tars;

import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.util.Log;

public class TarsWidgetUpdateService extends Service {
    private static final String TAG = "TarsWidgetUpdateService";
    private static final long UPDATE_INTERVAL = 1000; // 1 seconde
    
    private Handler handler = new Handler();
    private Runnable updateRunnable = new Runnable() {
        @Override
        public void run() {
            // Envoyer un broadcast pour mettre à jour le widget
            Intent updateIntent = new Intent("com.example.tars.WIDGET_UPDATE");
            sendBroadcast(updateIntent);
            
            // Planifier la prochaine mise à jour
            handler.postDelayed(this, UPDATE_INTERVAL);
        }
    };
    
    @Override
    public void onCreate() {
        super.onCreate();
        Log.d(TAG, "Service de mise à jour du widget démarré");
    }
    
    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Démarrer les mises à jour régulières
        handler.post(updateRunnable);
        return START_STICKY;
    }
    
    @Override
    public void onDestroy() {
        // Arrêter les mises à jour
        handler.removeCallbacks(updateRunnable);
        super.onDestroy();
        Log.d(TAG, "Service de mise à jour du widget arrêté");
    }
    
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
