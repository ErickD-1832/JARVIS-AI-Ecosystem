from datetime import datetime
from sys import flags
import ctypes
import os
import sys
import subprocess
 
# Variables de entorno ANTES de cualquier import de audio
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['PYTHONWARNINGS'] = 'ignore'
os.environ['JACK_NO_AUDIO_RESERVATION'] = '1'
os.environ['SDL_AUDIODRIVER'] = 'alsa'        # Fuerza SDL a usar ALSA directamente
 
# Suprimir ALSA ANTES de cualquier import de audio
def silenciar_alsa():
    try:
        libasound = ctypes.CDLL('libasound.so.2')
        ERROR_HANDLER = ctypes.CFUNCTYPE(
            None, ctypes.c_char_p, ctypes.c_int,
            ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
        )
        libasound.snd_lib_error_set_handler(
            ERROR_HANDLER(lambda *_: None)
        )
        print("✅ [AUDIO] ALSA silenciado correctamente")
    except Exception as e:
        print(f"⚠️ [AUDIO] No se pudo silenciar ALSA: {e}")
 
silenciar_alsa()  # ← DEBE SER LO PRIMERO ANTES DE CUALQUIER IMPORT DE AUDIO
 
# Filtrar mensajes de JACK/PortAudio del stderr (los que llegan igual)
class FiltroStderr:
    BASURA = (
        "ALSA lib", "Cannot connect to server",
        "jack server", "JackShmReadWritePtr",
        "Cannot open device", "snd_func_refer",
        "snd_config_expand", "Unable to find definition",
        "Expression 'paInvalidSampleRate'"
    )
    def __init__(self, fd_original):
        self.fd = fd_original
    def write(self, data):
        if not any(b in data for b in self.BASURA):
            self.fd.write(data)
    def flush(self):
        self.fd.flush()
    def fileno(self):
        return self.fd.fileno()
 
sys.stderr = FiltroStderr(sys.stderr)


import datetime
import asyncio
import io
import re
import threading
import socket
 
import pygame
import geocoder
import re
import threading
import speech_recognition as sr
import edge_tts
from google import genai
from groq import Groq
from pymongo import MongoClient
from evdev import InputDevice, categorize, ecodes, list_devices
import cv2
from PIL import Image
import socket


# ANTES (causa conflicto con ALSA):
pygame.mixer.init()

# DESPUÉS (fuerza parámetros seguros):
try:
    pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=1024)
    pygame.mixer.init()
    pygame.init()
except Exception as e:
    print(f"⚠️ Audio: {e}")

MODO_VOZ = False
INTERRUMPIR = False

#---mongoDB 

client = MongoClient("mongodb://localhost:27017/")
# Nombre de la base de datos 
db = client['Jarvis']
memoria = db['conversaciones']

# APIS (aqui ponemos las llaves)
client_gemini = genai.Client(api_key="")
client_groq = Groq(api_key="")

def servidor_para_esqueleto():
    # Creamos un socket para escuchar a C#
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('localhost', 65432)) # Puerto de escucha
    server.listen(1)
    print("🔌 [SISTEMA] Esqueleto C# puede conectarse ahora...")

    while True:
        conn, addr = server.accept()
        data = conn.recv(1024).decode('utf-8')
        if data:
            print(f"📩 Recibido de C#: {data}")
            # Usamos tu función existente para obtener respuesta
            respuesta_texto, ia_usada = obtener_respuesta(data)
            # Guardamos en la DB como siempre
            guardar_en_db(data, respuesta_texto, ia_usada)
            # Enviamos la respuesta de vuelta al esqueleto C#
            conn.sendall(respuesta_texto.encode('utf-8'))
            # Opcional: Que Jarvis también lo diga en voz alta
            threading.Thread(target=hablar, args=(respuesta_texto,)).start()
        conn.close()

# Lanzar el servidor en un hilo aparte para no bloquear tu bucle de teclado
threading.Thread(target=servidor_para_esqueleto, daemon=True).start()

def monitoreo_teclado_bajo_nivel():
    global MODO_VOZ, INTERRUMPIR
    
    #Buscar el teclado automáticamente
    devices = [InputDevice(path)for path in list_devices()]
    teclado = None
    for device in devices:
        if "keyboard" in device.name.lower() or "at translated set 2 keyboard" in device.name.lower():
            teclado = device
            print(f"✅ Teclado detectado: {device.name} ({device.path})")
            break
    # Si no lo encuentra con el nombre, usamos el primero que no sea el de hotkeys
    if not teclado:
        for device in devices:
            if "wmi" not in device.name.lower() and "mouse" not in device.name.lower():
                teclado = device
                break
            
    if not teclado:
        print("❌ No se detectó ningún teclado compatible.")
        return
    print(f"📡 [KERNEL] JARVIS conectado a: {teclado.name}")
    
    # Bucle infinito escuchando el hardware
    for event in teclado.read_loop():
        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            if key_event.keystate == 1: # 1 es presionado
                # Scancode de f2 es 60
                if key_event.scancode == ecodes.KEY_F2:
                    MODO_VOZ = not MODO_VOZ
                    estado = "Voz" if MODO_VOZ else "ESCRITURA"
                    print(f"\n\n[HARDWARE] 🔄 MODO {estado} ACTIVADO.")
                    print("Señor, puede proceder...")
                # Scancode de ESC es 1   
                elif key_event.scancode == ecodes.KEY_ESC:
                    if pygame.mixer.music.get_busy():
                        pygame.mixer.music.stop()
                        print("\n[HARDWARE] 🛑 Interrupción solicitada.")
                        INTERRUMPIR = True

# Lanzamos el hilo de hardware inmediatamente
threading.Thread(target=monitoreo_teclado_bajo_nivel, daemon=True).start()

audio_lock = threading.Lock()

class SensorOido:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.device_index = 4  
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = False  
        self.recognizer.pause_threshold = 0.8

    def escuchar(self):
        mic = None
        try:
            # Usamos el candado para que ningún otro hilo (como evdev) 
            # interfiera en la inicialización en C del hardware de audio.
            with audio_lock:
                mic = sr.Microphone(device_index=self.device_index)
                # Forzamos una inicialización manual interna protegida por el lock
                if not hasattr(mic, "audio"):
                    mic.__enter__()
                    mic_abierto_manualmente = True
                else:
                    mic_abierto_manualmente = False

            # Fuera del lock ya podemos proceder a escuchar el buffer de forma segura
            with mic as fuente:
                print("👂 [SISTEMA] Escuchando...")
                audio = self.recognizer.listen(fuente, timeout=5, phrase_time_limit=10)
                
            print("🧠 [SISTEMA] Procesando voz...")
            peticion = self.recognizer.recognize_google(audio, language="es-ES")
            print(f"👤 Señor: {peticion}")
            return peticion

        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            print("⚠️ [SISTEMA] No entendí el audio.")
            return None
        except Exception as e:
            print(f"❌ Error inesperado en mic: {e}")
            return None
        finally:
            # Liberación segura libre de NoneType errors
            if mic is not None:
                try:
                    if 'mic_abierto_manualmente' in locals() and mic_abierto_manualmente:
                        mic.__exit__(None, None, None)
                except Exception:
                    pass
 


def hablar(texto):
    """Genera voz con edge_tts y reproduce con pygame de forma segura"""
    if not texto or not texto.strip():
        return

    async def _generar_y_reproducir():
        import io
        try:
            tts = edge_tts.Communicate(texto, voice="es-MX-JorgeNeural")
            audio_bytes = io.BytesIO()

            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    audio_bytes.write(chunk["data"])

            audio_bytes.seek(0)

            if audio_bytes.getbuffer().nbytes == 0:
                print("[VOZ] ❌ TTS no generó audio")
                return

            pygame.mixer.music.load(audio_bytes)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if INTERRUMPIR:
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(10)

        except Exception as e:
            print(f"[VOZ] ❌ Error: {e}")

    try:
        asyncio.run(_generar_y_reproducir())
    except RuntimeError:
        # Si ya hay un event loop corriendo (caso edge)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_generar_y_reproducir())
        loop.close()
    
        


def guardar_en_db(pregunta, respuesta, ia_usada):
    log = {
        "fecha": datetime.datetime.now(),
        "pregunta": pregunta,
        "respuesta": respuesta,
        "IA": ia_usada
    }
    memoria.insert_one(log)
    
def obtener_contexto(pregunta_actual=""):
    # 1. Limpiamos la pregunta para evitar errores de símbolos
    limpia = "".join(e for e in pregunta_actual if e.isalnum() or e.isspace())
    palabras = limpia.split()
    
    # 2. Si no hay palabras, devolvemos los últimos mensajes por defecto
    if not palabras:
        recientes = list(memoria.find().sort("fecha", -1).limit(5))
        return "\n".join([f"Usuario: {m['pregunta']}\nJARVIS: {m['respuesta']}" for m in recientes])

    # 3. BUSQUEDA DINÁMICA: Intentamos buscar frases completas o palabras clave
    # Usamos $in para buscar coincidencias exactas de palabras importantes
    query = {"$or": [
        {"pregunta": {"$regex": pregunta_actual, "$options": "i"}}, # Frase completa
        {"pregunta": {"$regex": "|".join(palabras), "$options": "i"}} # Palabras sueltas
    ]}
    
    recuerdos = list(memoria.find(query).sort("fecha", -1).limit(10))
    
    # 4. DEBUG EN CONSOLA (Para que tú veas qué está pasando)
    print(f"🌐 [SISTEMA] Buscando: '{limpia}'")
    print(f"🧠 [SISTEMA] Recuerdos encontrados: {len(recuerdos)}")

    if not recuerdos:
        # Si no encuentra nada específico, trae lo último que se habló
        recuerdos = list(memoria.find().sort("fecha", -1).limit(5))

    contexto = "HISTORIAL DE MEMORIA:\n"
    vistos = set()
    final = []
    for m in recuerdos:
        if str(m['_id']) not in vistos:
            final.append(m)
            vistos.add(str(m['_id']))
            
    final.sort(key=lambda x: x['fecha'])
    
    texto_contexto = ""
    for msg in final:
        texto_contexto += f"Usuario: {msg['pregunta']}\nJARVIS: {msg['respuesta']}\n"
        
    return texto_contexto

# Obtener la ubicación actual del usuario (esto es opcional, pero puede ser útil para respuestas contextuales)

def obtener_ubicacion():
    try:
        # Detecta ubicación por IP
        g = geocoder.ip('me')
        if g.city:
            return f"{g.city}, {g.country}"
        return "Desconocida"
    except Exception:
        return "No disponible"


def clear_text(text):
    """
    Elimina símbolos de formato Markdown (#, *, _, `, etc.)
    que Gemini/Groq agregan y que estorban al hablar/leer.
    """
    if not text:
        return text

    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    
    # Quitar negritas/cursivas: **texto**, *texto*, __texto__, _texto_
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)

    # Quitar bullets de listas: -, *, + al inicio de línea
    text = re.sub(r'^[\-\*\+]\s+', '', text, flags=re.MULTILINE)

    # Quitar código en línea o bloques: `texto` o ```texto```
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`(.+?)`', r'\1', text)
 
    # Quitar cualquier # o * sueltos que queden
    text = text.replace('#', '').replace('*', '')
 
    # Limpiar espacios/líneas extra que dejan los reemplazos
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = text.strip()
 
    return text

def capturar_vision():
    """Tomar una foto y guardar temporalmente"""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ [SISTEMA] No se pudo acceder a la cámara")
        return None
        
    # Dejemos que la camara se ajuste a la luz 
    for _ in range(10): cap.read()
    
    ret, frame = cap.read()
    if ret:
        path_imagen = "ojos_jarvis.jpg"
        cv2.imwrite(path_imagen, frame)
        cap.release()
        return path_imagen
    
    cap.release()
    return None

# NO SE TOCA AL MENOS QUE TU SEPAS LO QUE HACES!!!!!!!
def obtener_respuesta(pregunta_actual):
    # 1. Recuperamos el historial de MongoDB
    historial = obtener_contexto(pregunta_actual)
    
    # 2. CAPTURAMOS DATOS REALES (TIEMPO Y ESPACIO)
    ahora = datetime.datetime.now()
    fecha_hora_actual = ahora.strftime("%A, %d de %B de %Y, %H:%M:%S")
    ubicacion = obtener_ubicacion()
    
    # Buscamos si existe EXACTAMENTE la misma pregunta
    coincidencia_exacta = memoria.find_one({"pregunta": {"$regex": f"^{re.escape(pregunta_actual)}$", "$options": "i"}})
    
    recuerdos_exactos = ""
    if coincidencia_exacta:
        recuerdos_exactos = f"\n⚠️ RESPUESTA HISTÓRICA EXACTA:\nEn el pasado respondiste: {coincidencia_exacta['respuesta']}\n"
    
    # 3. FILTRO DE MEMORIA DE LARGO PLAZO (Búsqueda Semántica/Palabras)
    # Limpiamos la pregunta para buscar conceptos clave
    limpia = "".join(e for e in pregunta_actual if e.isalnum() or e.isspace()).lower()
    
    # --- NUEVO: FILTRO DE ACTIVACIÓN DE VISIÓN ---
    palabras_vision = ["mira", "que ves", "quién es", "que es esto", "analiza", "observa", "mírate"  , "veo", "foto", "imagen", "cámara", "despcribir", "detecta", "reconoce"]
    quiere_ver = any(palabra in limpia for palabra in palabras_vision)
    
    imagen_path = None
    if quiere_ver:
        print("📸 [SISTEMA] Activando sensores ópticos...")
        imagen_path = capturar_vision()
    
    palabras_importantes = [re.escape(p) for p in limpia.split() if len(p) > 2] # Solo palabras con significado
    
    # Query que busca en TODA la base de datos (sin límite de tiempo inicial)
    # Buscamos coincidencias en la pregunta o en respuestas pasadas
    
    query_memoria = {
        "$or": [
            {"pregunta": {"$regex": pregunta_actual, "$options": "i"}}, # Coincidencia de frase completa
            {"respuesta": {"$regex": pregunta_actual, "$options": "i"}}, # Coincidencia en respuestas pasadas
            {"pregunta": {"$regex": "|".join(palabras_importantes), "$options": "i"}}, # Coincidencia de palabras clave en preguntas
            {"respuesta": {"$regex": "|".join(palabras_importantes), "$options": "i"}} # Coincidencia de palabras clave en respuestas
        ]
    }
    # Traemos los 5 recuerdos más relevantes de cualquier fecha
    recuerdos_pasado = list(memoria.find(query_memoria).sort("fecha", -1).limit(5))
    
    contexto_largo_plazo = ""
    if recuerdos_pasado:
        contexto_largo_plazo = "\n--- RECUERDOS RELEVANTES DEL PASADO ---\n"
        for r in recuerdos_pasado:
            fecha_recuerdo = r['fecha'].strftime("%d/%m/%Y")
            contexto_largo_plazo += f"[{fecha_recuerdo}] Usuario: {r['pregunta']} | JARVIS: {r['respuesta']}\n"
            
    # 4. FILTRO CRÍTICO: Prioridad de Sensores
    # Si la pregunta es sobre tiempo o lugar, ignoramos recuerdos que puedan confundir
    palabras_tiempo = ["hora", "día", "fecha", "donde", "tiempo", "ubicación", "lugar", "dónde", "momento"]
    es_pregunta_actual = any(palabra in limpia for palabra in palabras_tiempo)
    
    # 5. CONSTRUCCIÓN DEL PROMPT FINAL
    instrucciones = (
        f"Eres JARVIS, un asistente con memoria persistente.\n"
        f"DATOS ACTUALES (Priorizar si preguntan por hoy/ahora):\n"
        f"📡 Ubicación: {ubicacion}\n"
        f"🕒 Fecha y Hora: {fecha_hora_actual}\n"
    )
    
    # Unimos todo: Instrucciones + Memoria Antigua + Chat Reciente
    prompt_final = (
        f"{instrucciones}\n"
        f"{recuerdos_exactos}\n"
        f"{contexto_largo_plazo}\n"
        f"HISTORIAL RECIENTE DEL CHAT:\n{historial}\n"
        f"Usuario: {pregunta_actual}\n"
        f"JARVIS:"
    )

    try:
        # Si capturamos una imagen, enviamos una lista con [texto, imagen]
        if imagen_path:
            img = Image.open(imagen_path)
            contenido_multimodal = [prompt_final, img]
        else:
            contenido_multimodal = [prompt_final]            
        # Usamos gemini 2.5-flash para evitar el error de librería obsoleta
        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash", 
            contents=contenido_multimodal
        )
        # Limpieza de archivo temporal
        if imagen_path and os.path.exists(imagen_path):
            os.remove(imagen_path)
            
        return clear_text(response.text), "Gemini"
    
    except Exception as e:
        print(f"❌ Error de Gemini: {e}")
        # RESPALDO CON GROQ
        try:
            # Si el usuario quería "ver" algo, le avisamos que el procesador visual falló
            aviso_vision = ""
            if "mira" in pregunta_actual.lower() or "que ves" in pregunta_actual.lower():
                aviso_vision = " (Nota: El sensor visual falló, responde solo con texto)."
                
            chat_completion = client_groq.chat.completions.create(
                messages=[
                    {"role": "system", "content": f"Eres JARVIS. Ubicación: {ubicacion}. Hora: {fecha_hora_actual}."},
                    {"role": "user", "content": prompt_final}
                ],
                model="meta-llama/llama-4-scout-17b-16e-instruct"
, 
            )
            if imagen_path and os.path.exists(imagen_path):
                os.remove(imagen_path) # Limpiamos la foto aunque Groq no la use
            
            return clear_text(chat_completion.choices[0].message.content) + aviso_vision, "Groq"
        except Exception as e_groq:
            print(f"Error en Groq: {e_groq}")
            return "❌ Señor, mis sistemas de datos están fuera de línea.", "None"

        
        

#--- BUCLE PRINCIPAL ---
print("🚀 JARVIS ACTIVADO CON CONTROL DE HARDWARE")
print("⌨️  F2: Modo Híbrido | 🛑 ESC: Interrumpir voz")

# --- BUCLE PRINCIPAL DINÁMICO ---
oido = SensorOido()

hour_now = datetime.datetime.now().hour
if 5 <= hour_now < 12:
    saludo = "Buenos días"
elif 12 <= hour_now < 19:
    saludo = "Buenas tardes"
else:
    saludo = "Buenas noches"

mensaje_bienvenida = ("Todos los sistemas en línea. Diagnóstico completo sin anomalías. "
                    "Conexión con los núcleos de inteligencia establecida. "
                        f"{saludo}, señor. JARVIS a su disposición.")
print(f"\n🤖 JARVIS: {mensaje_bienvenida}")
hablar(mensaje_bienvenida)

while True:
    try:
        if MODO_VOZ:
            # Iniciamos la escucha
            usuario = oido.escuchar()
            
            # Si no captó nada o cambiaste el modo mientras escuchaba
            if not usuario:
                pygame.time.wait(100)
                continue
        else:
            # En modo escritura, usamos un pequeño truco:
            # Si presionas F2, para que el programa se entere, debes dar un Enter vacío
            usuario = input("\n👤 Señor: ")
            if not usuario and not MODO_VOZ: continue 
            if not usuario and MODO_VOZ: continue # Salta al siguiente ciclo (ahora en VOZ)

        if usuario.lower() in ["salir", "exit"]: break

        res, ia = obtener_respuesta(usuario)
        if ia != "None":
            guardar_en_db(usuario, res, ia)
        hablar(res)

    except KeyboardInterrupt:
        break
    
print("\n👋 JARVIS se está apagando. ¡Hasta luego!")
    
    
