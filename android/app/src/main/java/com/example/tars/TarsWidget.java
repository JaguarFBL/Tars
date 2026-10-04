package com.example.tars;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.AsyncTask;
import android.util.Log;
import android.widget.RemoteViews;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public class TarsWidget extends AppWidgetProvider {
    private static final String TAG = "TarsWidget";
    private static final String WIDGET_UPDATE_ACTION = "com.example.tars.WIDGET_UPDATE";
    
    @Override
    public void onUpdate(Context context, AppWidgetManager appWidgetManager, int[] appWidgetIds) {
        // Mettre à jour tous les widgets
        for (int appWidgetId : appWidgetIds) {
            updateAppWidget(context, appWidgetManager, appWidgetId);
        }
        
        // Démarrer un service pour mettre à jour régulièrement
        Intent updateService = new Intent(context, TarsWidgetUpdateService.class);
        context.startService(updateService);
    }
    
    @Override
    public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        
        if (WIDGET_UPDATE_ACTION.equals(intent.getAction())) {
            AppWidgetManager appWidgetManager = AppWidgetManager.getInstance(context);
            ComponentName widget = new ComponentName(context, TarsWidget.class);
            int[] appWidgetIds = appWidgetManager.getAppWidgetIds(widget);
            for (int appWidgetId : appWidgetIds) {
                updateAppWidget(context, appWidgetManager, appWidgetId);
            }
        }
    }
    
    static void updateAppWidget(Context context, AppWidgetManager appWidgetManager, int appWidgetId) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.tars_widget);
        
        // Mettre à jour l'état depuis le backend
        new FetchStateTask(views, appWidgetManager, appWidgetId, context).execute();
        
        // Configurer le bouton
        Intent clickIntent = new Intent(context, TarsWidget.class);
        clickIntent.setAction("com.example.tars.WIDGET_CLICK");
        PendingIntent pendingIntent = PendingIntent.getBroadcast(
            context, 
            0, 
            clickIntent, 
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        views.setOnClickPendingIntent(R.id.widget_button, pendingIntent);
        
        appWidgetManager.updateAppWidget(appWidgetId, views);
    }
    
    static class FetchStateTask extends AsyncTask<Void, Void, String> {
        private RemoteViews views;
        private AppWidgetManager appWidgetManager;
        private int appWidgetId;
        private Context context;
        
        FetchStateTask(RemoteViews views, AppWidgetManager appWidgetManager, int appWidgetId, Context context) {
            this.views = views;
            this.appWidgetManager = appWidgetManager;
            this.appWidgetId = appWidgetId;
            this.context = context;
        }
        
        @Override
        protected String doInBackground(Void... voids) {
            try {
                URL url = new URL("http://localhost:8000/widget");
                HttpURLConnection connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(1000);
                connection.setReadTimeout(1000);
                
                int responseCode = connection.getResponseCode();
                if (responseCode == HttpURLConnection.HTTP_OK) {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream()));
                    StringBuilder response = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        response.append(line);
                    }
                    reader.close();
                    return response.toString();
                } else {
                    return "{\"status\":\"off\",\"error\":\"Backend non disponible (" + responseCode + ")\"}";
                }
            } catch (Exception e) {
                Log.e(TAG, "Erreur lors de la récupération de l'état: " + e.getMessage());
                return "{\"status\":\"off\",\"error\":\"Erreur réseau\"}";
            }
        }
        
        @Override
        protected void onPostExecute(String result) {
            try {
                org.json.JSONObject json = new org.json.JSONObject(result);
                String status = json.getString("status");
                
                // Mettre à jour le texte d'état
                String statusText = "TARS: ";
                switch (status) {
                    case "off":
                        statusText += "Hors ligne";
                        break;
                    case "listening":
                        statusText += "Écoute...";
                        break;
                    case "thinking":
                        statusText += "Réfléchit";
                        break;
                    case "speaking":
                        statusText += "Parle";
                        break;
                    default:
                        statusText += status;
                }
                
                views.setTextViewText(R.id.widget_status, statusText);
                
                // Mettre à jour le bouton en fonction de l'état
                if ("off".equals(status)) {
                    views.setTextViewText(R.id.widget_button, "Démarrer");
                } else {
                    views.setTextViewText(R.id.widget_button, "Arrêter");
                }
                
                appWidgetManager.updateAppWidget(appWidgetId, views);
            } catch (Exception e) {
                Log.e(TAG, "Erreur lors du parsing JSON: " + e.getMessage());
                views.setTextViewText(R.id.widget_status, "TARS: Erreur");
                appWidgetManager.updateAppWidget(appWidgetId, views);
            }
        }
    }
}
