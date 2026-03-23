# import speech_recognition as sr
# for index, name in enumerate(sr.Microphone.list_microphone_names()):
#     print(f'Microphone with name "{name}" found for `Microphone(device_index={index})`')

# test_completo.py
import speech_recognition as sr
import pyaudio
import sys

print("=" * 50)
print("🔍 DIAGNÓSTICO COMPLETO DE AUDIO")
print("=" * 50)

# 1. Verificar versiones
print(f"\n📦 Versión de speech_recognition: {sr.__version__}")

# 2. Listar TODOS los dispositivos de audio con PyAudio (más detallado)
print("\n🎤 DISPOSITIVOS DE AUDIO (PyAudio):")
try:
    p = pyaudio.PyAudio()
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev['maxInputChannels'] > 0:  # Solo dispositivos de entrada
            print(f"   [{i}] {dev['name']}")
            print(f"       Canales entrada: {dev['maxInputChannels']}")
            print(f"       Tasa muestreo: {dev['defaultSampleRate']}")
    p.terminate()
except Exception as e:
    print(f"❌ Error con PyAudio: {e}")

# 3. Listar micrófonos de speech_recognition
print("\n🎤 MICRÓFONOS (speech_recognition):")
try:
    mics = sr.Microphone.list_microphone_names()
    for i, name in enumerate(mics):
        print(f"   [{i}] {name}")
except Exception as e:
    print(f"❌ Error listando micrófonos: {e}")

# 4. Probar CADA micrófono individualmente
print("\n🎯 PROBANDO CADA MICRÓFONO:")
print("(Habla algo cuando veas 'Escuchando...' y espera 3 segundos)")

r = sr.Recognizer()
r.energy_threshold = 300
r.dynamic_energy_threshold = True
r.pause_threshold = 0.8

for i in range(len(mics)):
    print(f"\n--- Probando micrófono [{i}] ---")
    try:
        with sr.Microphone(device_index=i) as source:
            print(f"   Ajustando ruido ambiente...")
            r.adjust_for_ambient_noise(source, duration=1)
            print(f"   🎤 Escuchando (di algo)...")
            audio = r.listen(source, timeout=3, phrase_time_limit=3)
            print(f"   ✅ Audio capturado! Intentando reconocer...")
            
            try:
                texto = r.recognize_google(audio, language="es-ES")
                print(f"   ✨ ¡FUNCIONA! Dijiste: '{texto}'")
                print(f"   👉 Este es el micrófono que DEBES USAR")
                break
            except sr.UnknownValueError:
                print(f"   ⚠️  Se capturó audio pero no se entendió (ruido o voz baja)")
            except sr.RequestError as e:
                print(f"   ❌ Error de conexión con Google: {e}")
                
    except Exception as e:
        print(f"   ❌ Error con micrófono {i}: {e}")

print("\n" + "=" * 50)
print("🔧 SIGUIENTE PASO:")
print("1. Ejecuta este script y dime qué muestra")
print("2. Si algún micrófono funciona, anota su número")
print("3. Si TODOS fallan, necesitamos instalar dependencias")
print("=" * 50)