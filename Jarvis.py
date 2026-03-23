import os
import datetime
import asyncio
import pygame
import geocoder
import re
import threading
import speech_recognition as sr
import edge_tts
from google import genai
from groq import Groq
from pymongo import MongoClient
from evdev import InputDevice, categorize, ecodes, list_devices # BAJO NIVEL
import ctypes
import cv2
from PIL import Image
import socket



try:
    pygame.mixer.init()
except Exception as e:
    print(f"⚠️ Nota: Audio no inicializado ({e})")

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

client_gemini = genai.Client(api_key="")
client_groq = Groq(api_key="")


# Silenciar advertencias de ALSA y Jack
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
# Esto redirige los errores de C (ALSA) a la nada

libasound = ctypes.CDLL('libasound.so.2')
def silenciar_alsa():
    asound_error_handler = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
    def ignore_error(filename, line, function, err, fmt): pass
    c_ignore_error = asound_error_handler(ignore_error)
    libasound.snd_lib_error_set_handler(c_ignore_error)

silenciar_alsa()

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


def hablar(texto):
    """Genera voz neuronal humana al instante"""
    
    global INTERRUMPIR
    INTERRUMPIR = False  # Reiniciamos la bandera de interrupción cada vez que hablamos
    
    print(f"\n💠 JARVIS: {texto}")
    
    # Elegimos una voz de hombre, profesional y clara
    # 'es-ES-AlvaroNeural' suena muy parecido a un asistente moderno
    VOZ = "es-ES-AlvaroNeural" 
    ARCHIVO_AUDIO = "respuesta.mp3"

    async def comunicacion():
        communicate = edge_tts.Communicate(texto, VOZ, rate="+10%", pitch="-5Hz")
        await communicate.save(ARCHIVO_AUDIO)

    try:
        asyncio.run(comunicacion())
        pygame.mixer.music.load(ARCHIVO_AUDIO)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if INTERRUMPIR: break
            pygame.time.Clock().tick(10)
        pygame.mixer.music.unload()
    except: pass
    
        
        
def escuchar_microfono():
    r = sr.Recognizer()
    # Ajustes de sensibilidad para que no sea tan "sordo"
    r.energy_threshold = 300 
    r.dynamic_energy_threshold = True
    
    # FORZAMOS EL ÍNDICE 10 (El 'default' de tu lista)
    try:
        with sr.Microphone(device_index=10) as source:
            print("🎤 [JARVIS] Escuchando... (Hable ahora)")
            # Reducimos el tiempo de ajuste para que sea más rápido
            r.adjust_for_ambient_noise(source, duration=0.8)
            
            try:
                # Ponemos límites para que no se bloquee el programa
                audio = r.listen(source, timeout=5, phrase_time_limit=8)
                print("🧠 [JARVIS] Analizando...")
                texto = r.recognize_google(audio, language="es-ES")
                print(f"👤 Usted dijo: {texto}")
                return texto
            except sr.WaitTimeoutError:
                return None
            except sr.UnknownValueError:
                print("❓ [JARVIS] No entendí el audio.")
                return None
    except Exception as e:
        print(f"❌ Error de hardware de audio: {e}")
        return None

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
            
        return response.text, "Gemini"
    
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
                model="llama-3.1-8b-instant", 
            )
            if imagen_path and os.path.exists(imagen_path):
                os.remove(imagen_path) # Limpiamos la foto aunque Groq no la use
            
            return chat_completion.choices[0].message.content + aviso_vision,  "Groq"
        except Exception as e_groq:
            print(f"Error en Groq: {e_groq}")
            return "❌ Señor, mis sistemas de datos están fuera de línea.", "None"
        

#--- BUCLE PRINCIPAL ---
print("🚀 JARVIS ACTIVADO CON CONTROL DE HARDWARE")
print("⌨️  F2: Modo Híbrido | 🛑 ESC: Interrumpir voz")

# --- BUCLE PRINCIPAL DINÁMICO ---
while True:
    try:
        if MODO_VOZ:
            # Iniciamos la escucha
            usuario = escuchar_microfono()
            
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
    
    

