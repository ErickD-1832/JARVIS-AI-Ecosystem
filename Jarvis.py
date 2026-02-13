import os
import google.generativeai as genai
from groq import Groq
from pymongo import MongoClient
import datetime
import edge_tts
import asyncio
import pygame
import geocoder

#---Configuracion ---
#---mongoDB

client = MongoClient("mongodb://localhost:27017/")
# Nombre de la base de datos 
db = client['Jarvis']
memoria = db['conversaciones']

# APIS (aqui ponemos las llaves)
genai.configure(api_key="")
client_groq = Groq(api_key="")


def hablar(texto):
    """Genera voz neuronal humana al instante"""
    print(f"\n💠 JARVIS: {texto}")
    
    # Elegimos una voz de hombre, profesional y clara
    # 'es-ES-AlvaroNeural' suena muy parecido a un asistente moderno
    VOZ = "es-ES-AlvaroNeural" 
    ARCHIVO_AUDIO = "respuesta.mp3"

    async def comunicacion():
        communicate = edge_tts.Communicate(texto, VOZ, rate="+10%", pitch="-5Hz")
        await communicate.save(ARCHIVO_AUDIO)

    # Ejecutar la generación
    asyncio.run(comunicacion())

    # Reproducir el archivo generado
    pygame.mixer.init()
    pygame.mixer.music.load(ARCHIVO_AUDIO)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        continue
    pygame.mixer.quit()

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

def obtener_respuesta(pregunta_actual):
    # 1. Recuperamos el historial de MongoDB
    historial = obtener_contexto(pregunta_actual)
    
    # 2. CAPTURAMOS DATOS REALES (TIEMPO Y ESPACIO)
    ahora = datetime.datetime.now()
    fecha_hora_actual = ahora.strftime("%A, %d de %B de %Y, %H:%M:%S")
    ubicacion = obtener_ubicacion()
    
    # 3. FILTRO CRÍTICO: ¿Es una pregunta sobre tiempo o lugar?
    # Esto evita que JARVIS lea respuestas viejas de la base de datos
    palabras_clave = ["hora", "fecha", "día", "donde estoy", "ubicación", "donde me encuentro", "donde vivo"]
    es_pregunta_tiempo_real = any(p in pregunta_actual.lower() for p in palabras_clave)

    # 4. MODO OFFLINE / MEMORIA DIRECTA
    # Solo usamos la respuesta guardada si NO es algo que requiera datos en tiempo real
    if not es_pregunta_tiempo_real:
        busqueda_directa = memoria.find_one({"pregunta": {"$regex": pregunta_actual, "$options": "i"}})
        if busqueda_directa:
            return f"{busqueda_directa['respuesta']}", "MemoriaLocal"

    # 5. PROMPT DE PERSONALIDAD (Aquí le "inyectamos" la realidad a la IA)
    instrucciones = (
        f"Eres JARVIS, un asistente avanzado. \n"
        f"DATOS DE SENSORES EN TIEMPO REAL:\n"
        f"📡 Ubicación: {ubicacion}\n"
        f"🕒 Fecha y Hora: {fecha_hora_actual}\n"
        f"Usa estos datos para responder si el usuario pregunta por ellos. \n"
        f"HISTORIAL DE CONVERSACIÓN:\n"
    )
    
    prompt_final = f"{instrucciones}{historial}\nUsuario: {pregunta_actual}"
    
    try:
        # Usamos gemini 2.5-flash para evitar el error de librería obsoleta
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt_final)
        return response.text, "Gemini"
    
    except Exception as e:
        print(f"❌ Error de Gemini: {e}")
        # RESPALDO CON GROQ
        try:
            chat_completion = client_groq.chat.completions.create(
                messages=[
                    {"role": "system", "content": f"Eres JARVIS. Ubicación: {ubicacion}. Hora: {fecha_hora_actual}."},
                    {"role": "user", "content": prompt_final}
                ],
                model="llama-3.1-8b-instant", 
            )
            return chat_completion.choices[0].message.content, "Groq"
        except Exception as e_groq:
            print(f"Error en Groq: {e_groq}")
            return "❌ Señor, mis sistemas de datos están fuera de línea.", "None"
    
#--- BUCLE PRINCIPAL ---
while True:
    usuario = input("\n👤 Señor, escriba su comando: ")
    if usuario.lower() in ["salir", "exit"]: break
    
    respuesta, ia_utilizada = obtener_respuesta(usuario)
    
    # Guardar lo que paso en MongoDB
    if ia_utilizada != "None":
        guardar_en_db(usuario, respuesta, ia_utilizada)
        
    
    hablar(respuesta)
