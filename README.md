# JARVIS-AI-Ecosystem

Asistente de voz con memoria persistente.

- `Gabriel.py` — cerebro en Python (voz, TTS, memoria MongoDB, puente TCP)
- `JarvisUI/` — interfaz en Avalonia (C#) que habla con Python por socket
- `pu.py` — diagnóstico de audio/micrófonos

## Arranque

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # y rellena GEMINI_API_KEY / GROQ_API_KEY
python Gabriel.py           # UI: dotnet run --project JarvisUI
```

## Teclado

| Tecla | Acción |
|---|---|
| `F2` | alterna modo voz / escritura |
| `ESC` | interrumpe la voz en curso |
| `/voz`, `/escritura` | cambia de modo desde la consola |
| `/limpiar` | detiene la voz |
| `/salir` | cierra el asistente |

`F2` a nivel kernel requiere `evdev` y permisos de lectura en `/dev/input`
(grupo `input` o root). Sin eso, `F2` sigue funcionando dentro de la terminal.

## Configuración (`.env`)

| Variable | Por defecto | Descripción |
|---|---|---|
| `GEMINI_API_KEY` | — | cerebro principal |
| `GROQ_API_KEY` | — | cerebro de respaldo |
| `MODELOS_GEMINI` | cadena de 4 modelos | se prueban en orden (evita 404/503) |
| `MODELOS_GROQ` | cadena de 3 modelos | ídem |
| `MONGO_URI` | `mongodb://localhost:27017/` | memoria |
| `MONGO_DB` / `MONGO_COLECCION` | `Jarvis` / `conversaciones` | colección usada |
| `PUERTO_ESQUELETO` | `65432` | puerto del socket para la UI C# |
| `MIC_INDICE` / `MIC_NOMBRE` | dispositivo por defecto | micrófono de entrada |
| `VOZ_EDGE` | `es-MX-JorgeNeural` | voz de edge-tts |
| `SDL_AUDIODRIVER` | SDL decide | forzarlo a `alsa` puede abortar el proceso |

Si MongoDB no está corriendo, el asistente **arranca igual** pero sin memoria.
Si ninguna llave está configurada, arranca pero no responde.

## Notas

- El audio sale por PulseAudio/ALSA según lo que detecte SDL; no fuerces `alsa`
  salvo que tu sistema lo requiera (el ALSA de Anaconda suele estar roto).
- `edge-tts` necesita la versión **7.3.1+**; las anteriores devuelven HTTP 403.
- El puente con la UI C# es texto plano sobre TCP: `localhost:65432`.
# Gabriel-
