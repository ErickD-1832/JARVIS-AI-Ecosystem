import os
import google.generativeai as genai
from groq import Groq
from pymongo import MongoClient
import datetime
import edge_tts
import asyncio
import pygame

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
    print(f"\nJARVIS: {texto}")
    
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
    print(f"---> [SISTEMA] Buscando: '{limpia}'")
    print(f"---> [SISTEMA] Recuerdos encontrados: {len(recuerdos)}")

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

def obtener_respuesta(pregunta_actual):
    # 1. Recuperamos la memoria local (Esto funciona SIEMPRE, con o sin internet)
    historial = obtener_contexto(pregunta_actual)
    
    # --- EL TRUCO DEL MODO OFFLINE ---
    # Si preguntas algo exacto que ya está en la DB, te lo responde directamente
    # sin pasar por Gemini.
    palabras_usuario = pregunta_actual.lower().split()
    # Buscamos si hay una respuesta exacta para esta pregunta en el historial
    busqueda_directa = memoria.find_one({"pregunta": {"$regex": pregunta_actual, "$options": "i"}})
    
    if busqueda_directa:
        return f"{busqueda_directa['respuesta']}", "MemoriaLocal"
    # ----------------------------------

    # Si no es una pregunta exacta, intentamos usar la IA
    instrucciones = "Eres JARVIS. Usa la memoria para responder: \n"
    prompt_final = f"{instrucciones}{historial}\nUsuario: {pregunta_actual}"
    
    try:
        # CAMBIA ESTO A 2.5-FLASH PARA TENER 1500 PETICIONES GRATIS
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt_final)
        return response.text, "Gemini"
    
    except Exception as e:
        # Si Gemini falla por saldo, JARVIS al menos intenta leer lo que recuperó de Mongo
        print(f"Error de API (Saldo): {e}")
        
        
    # INTENTO 2: GROQ (El respaldo gratuito y rápido)
        try:
            chat_completion = client_groq.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Eres JARVIS, un asistente inteligente y profesional."},
                    {"role": "user", "content": prompt_final}
                ],
                # Cambia 'llama3-8b-8192' por este:
                model="llama-3.1-8b-instant", 
            )
            return chat_completion.choices[0].message.content, "Groq"
        
        except Exception as e_groq:
            print(f"Error en Groq: {e_groq}")
            return "Señor, todos mis sistemas de inteligencia están caídos. Revise sus conexiones.", "None"
    
    
#--- BUCLE PRINCIPAL ---
while True:
    usuario = input("\nEscribe tu comando:")
    if usuario.lower() in ["salir", "exit"]: break
    
    respuesta, ia_utilizada = obtener_respuesta(usuario)
    
    # Guardar lo que paso en MongoDB
    if ia_utilizada != "None":
        guardar_en_db(usuario, respuesta, ia_utilizada)
        
    
    hablar(respuesta)
