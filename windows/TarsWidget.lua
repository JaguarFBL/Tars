-- Lua script pour le widget Rainmeter

function Initialize()
    -- Démarrer le backend si ce n'est pas déjà fait
    local backendPath = SKIN:GetVariable('CURRENTPATH') .. '\\Tars.exe'
    local file = io.popen('if exist "' .. backendPath .. '" (echo 1) else (echo 0)'):read('*l')
    if file == '1' then
        -- Le backend existe, vérifier s'il est en cours d'exécution
        local handle = io.popen('tasklist /FI "IMAGENAME eq Tars.exe" /FO CSV /NH'):read('*l')
        if not handle or handle == '' then
            -- Démarrer le backend
            os.execute('start "" /MIN "' .. backendPath .. '"')
        end
    end
end

function Update()
    -- Récupérer l'état depuis le backend
    local status = SKIN:GetMeasure('MeasureFetch'):GetStringValue()
    local statusText = 'TARS: '
    
    if status == 'off' then
        statusText = statusText .. 'Hors ligne'
        SKIN:Bang('!SetOption', 'TalkButton', 'Text', 'Démarrer')
    elseif status == 'listening' then
        statusText = statusText .. 'Écoute...'
        SKIN:Bang('!SetOption', 'TalkButton', 'Text', 'Arrêter')
    elseif status == 'thinking' then
        statusText = statusText .. 'Réfléchit'
        SKIN:Bang('!SetOption', 'TalkButton', 'Text', 'Arrêter')
    elseif status == 'speaking' then
        statusText = statusText .. 'Parle'
        SKIN:Bang('!SetOption', 'TalkButton', 'Text', 'Arrêter')
    else
        statusText = statusText .. status
    end
    
    SKIN:Bang('!SetOption', 'StatusText', 'Text', statusText)
    SKIN:Bang('!UpdateMeter', 'StatusText')
    SKIN:Bang('!UpdateMeter', 'TalkButton')
    SKIN:Bang('!Redraw')
end

-- Gérer le clic sur le bouton
function Toggle()
    local backendPath = SKIN:GetVariable('CURRENTPATH') .. '\\Tars.exe'
    
    -- Vérifier si Tars.exe est en cours d'exécution
    local handle = io.popen('tasklist /FI "IMAGENAME eq Tars.exe" /FO CSV /NH'):read('*l')
    
    if not handle or handle == '' then
        -- Démarrer le backend
        os.execute('start "" /MIN "' .. backendPath .. '"')
    else
        -- Arrêter le backend (plus complexe, nécessite de tuer le processus)
        os.execute('taskkill /IM Tars.exe /F')
    end
end
