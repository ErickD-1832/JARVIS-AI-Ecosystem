import os
import google.generativeai as genai
from openai import OpenAI
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
client_openai = OpenAI(api_key="")

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
    
    
def obtener_contexto():
    # Buscar las ultimos 5 mensajes en la base de datos
    ultimos_mensajes = memoria.find().sort("fecha", -1).limit(5)
    
    contexto = "Contexto de la conversacion anterior:\n"
    
    # Los invertimos para que este en orden cronologico (del mas voejo al mas nuevo)
    for msg in reversed(list(ultimos_mensajes)):
        contexto += f"Usuario: {msg['pregunta']}\nJARVIS: {msg['respuesta']}\n"
        
    return contexto

def obtener_respuesta(pregunta_actual):
    # 1. Recuperamos la memoria en mongoBD
    historial = obtener_contexto()
    
    # 2. Creamos el "Prompt"completo (contexto + pregunta nueva)
    prompt_final = f"{historial}\nUsuario ahora dice: {pregunta_actual}\nJARVIS:"
    
    # Intento 1: Geminis
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        # Le enviamos todo al paquete de memoria
        response = model.generate_content(prompt_final)
        return response.text, "Geminis"
    except Exception as e:
        print(f"Error en Geminis. Activando respaldo...")
        
    # Intento 2: CHATGPT    
    try:
        response = client_openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres JARVIS, un asistente inteligente."},
                {"role": "user", "content": prompt_final}
            ]
        )
        return response.choices[0].message.content, "ChatGPT"
    except Exception:
        return "Lo siento señor, no puedo acceder a mis núcleos de memoria ahora.", "None"
    
    
#--- BUCLE PRINCIPAL ---
while True:
    usuario = input("\nEscribe tu comando:")
    if usuario.lower() in ["salir", "exit"]: break
    
    respuesta, ia_utilizada = obtener_respuesta(usuario)
    
    # Guardar lo que paso en MongoDB
    if ia_utilizada != "None":
        guardar_en_db(usuario, respuesta, ia_utilizada)
        
    
    hablar(respuesta)