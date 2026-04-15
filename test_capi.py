import os
import requests
import time
from dotenv import load_dotenv

# Carrega as chaves do seu arquivo .env
load_dotenv()

PIXEL_ID = os.getenv("FB_PIXEL_ID")
ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")

# Se voce pegou um codigo de teste no Gerenciador de Eventos (aquela aba "Eventos de Teste")
# Coloque o codigo abaixo (exemplo: "TEST54321"). Se deixar "", vai mandar como evento real.
TEST_EVENT_CODE = "" 

if not PIXEL_ID or not ACCESS_TOKEN:
    print("ERRO: FB_PIXEL_ID ou FB_ACCESS_TOKEN faltando no .env")
    exit(1)

url = f"https://graph.facebook.com/v19.0/{PIXEL_ID}/events"

payload = {
    "data": [
        {
            "event_name": "Purchase",
            "event_time": int(time.time()),
            "action_source": "system_generated",
            "user_data": {
                "client_userAgent": "WhatsApp/teste_manual"
            },
            "custom_data": {
                "currency": "BRL",
                "value": 24.90
            }
        }
    ],
    "access_token": ACCESS_TOKEN
}

if TEST_EVENT_CODE:
    payload["test_event_code"] = TEST_EVENT_CODE

print(f"Enviando evento de Compra (Purchase) para o Pixel {PIXEL_ID}...")

try:
    resposta = requests.post(url, json=payload)
    if resposta.status_code == 200:
        print("✅ SUCESSO! A Meta aceitou o evento.")
        print(resposta.json())
        print("\nVerifique la no seu Gerenciador de Eventos do Facebook se ja apareceu a Compra (as vezes leva 1 ou 2 minutos).")
    else:
        print("❌ ERRO DA META:")
        print(f"Status Code: {resposta.status_code}")
        print(resposta.text)
except Exception as e:
    print(f"❌ Falha de Conexão: {e}")
