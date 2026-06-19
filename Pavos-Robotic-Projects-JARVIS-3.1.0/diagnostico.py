from pathlib import Path
import json,compileall
print('=== PRP Assistant diagnóstico ===')
root=Path(__file__).parent
print('Compilación:',compileall.compile_dir(root,quiet=1))
try:
 import sounddevice as sd
 print('Audio default:',sd.default.device)
 for i,d in enumerate(sd.query_devices()):print(i,d['name'],'IN',d['max_input_channels'],'OUT',d['max_output_channels'],int(d['default_samplerate']))
except Exception as e:print('Audio ERROR:',e)
try:
 from google import genai
 print('google-genai OK')
except Exception as e:print('Gemini SDK ERROR:',e)
