from __future__ import annotations

import json
import logging
import secrets
import shutil
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from app.config import get_settings
from app.flow_engine import FlowEngine
from app.session_store import SessionStore
from app.whatsapp_api import WhatsAppApiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
session_store = SessionStore(settings.redis_url)
api_client = WhatsAppApiClient(
    base_url=settings.whatsapp_api_base_url,
    instance_token=settings.whatsapp_instance_token,
    timeout_seconds=settings.request_timeout_seconds,
)
flow_engine = FlowEngine(
    session_store=session_store,
    client=api_client,
    public_base_url=settings.public_base_url,
)

MIME_MAP = {
    ".ogg": "audio/ogg; codecs=opus",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
}

ASSETS_DIR = Path("assets")
STATIC_DIR = Path("app/static")
DATA_DIR = Path("app/data")
ASSETS_CONFIG_FILE = DATA_DIR / "assets_config.json"
FLOW_CONFIG_FILE = DATA_DIR / "flow_config.json"

app = FastAPI(title="Agente de Atendimento WhatsApp")
security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    correct_username = secrets.compare_digest(credentials.username, settings.admin_user)
    correct_password = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Autenticacao incorreta",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


class AssetConfigPayload(BaseModel):
    config: dict


class FlowConfigPayload(BaseModel):
    config: dict


class TestCapiPayload(BaseModel):
    test_event_code: str = ""


def normalize_agent_config(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"system_directive": "", "cards": [], "connections": []}

    cards = data.get("cards", [])
    if not isinstance(cards, list):
        cards = []

    normalized_cards: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        tools = card.get("tools", [])
        if not isinstance(tools, list):
            tools = []

        normalized_tools: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            normalized_tools.append(tool)

        normalized_cards.append(
            {
                "id": str(card.get("id") or secrets.token_hex(4)),
                "title": str(card.get("title") or "Novo card"),
                "trigger": str(card.get("trigger") or ""),
                "instruction": str(card.get("instruction") or ""),
                "output_guidance": str(card.get("output_guidance") or ""),
                "tools": normalized_tools,
                "ui": card.get("ui") or {"x": 100, "y": 100},
            }
        )

    return {
        "system_directive": str(data.get("system_directive") or ""),
        "cards": normalized_cards,
        "connections": data.get("connections", []),
    }


def _default_agent_dashboard_config() -> dict[str, Any]:
    return normalize_agent_config(
        {
            "system_directive": (
                "Voce e uma atendente comercial no WhatsApp. "
                "Converse de forma humana, descubra a necessidade do cliente, "
                "use os arquivos do painel quando fizer sentido e conduza para a venda."
            ),
            "cards": [
                {
                    "id": "abertura",
                    "title": "Abertura",
                    "trigger": "Quando o cliente fizer o primeiro contato ou pedir informacoes",
                    "instruction": "Cumprimente, gere conforto e mostre que vai orientar com clareza.",
                    "output_guidance": "Me conta: o que voce quer resolver hoje?",
                    "tools": [
                        {
                            "kind": "text",
                            "label": "Texto de abertura",
                            "content": "Oi. Eu vou te explicar certinho e te orientar da melhor forma.",
                        }
                    ],
                    "ui": {"x": 150, "y": 150},
                }
            ],
            "connections": [],
        }
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(verify_credentials)):
    html_file = STATIC_DIR / "admin.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="Painel nao encontrado. Crie app/static/admin.html")
    return html_file.read_text(encoding="utf-8")


@app.get("/api/flow-config", dependencies=[Depends(verify_credentials)])
def get_flow_config():
    if not FLOW_CONFIG_FILE.exists():
        return {"config": _default_agent_dashboard_config()}

    with FLOW_CONFIG_FILE.open("r", encoding="utf-8") as file:
        return {"config": normalize_agent_config(json.load(file))}


@app.post("/api/flow-config", dependencies=[Depends(verify_credentials)])
def update_flow_config(payload: FlowConfigPayload):
    try:
        FLOW_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        normalized_config = normalize_agent_config(payload.config)
        with FLOW_CONFIG_FILE.open("w", encoding="utf-8") as file:
            json.dump(normalized_config, file, ensure_ascii=False, indent=2)
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/assets", dependencies=[Depends(verify_credentials)])
def list_assets():
    if not ASSETS_DIR.exists():
        return {"files": [], "global_initial_delay": 0}

    config = {}
    if ASSETS_CONFIG_FILE.exists():
        with ASSETS_CONFIG_FILE.open("r", encoding="utf-8") as file:
            config = json.load(file)

    files = []
    for file in ASSETS_DIR.iterdir():
        if not file.is_file():
            continue
        file_meta = config.get("files", {}).get(file.name, {})
        files.append(
            {
                "name": file.name,
                "size": file.stat().st_size,
                "delay_seconds": file_meta.get("delay_seconds", 0),
                "presence": file_meta.get("presence", ""),
            }
        )

    return {
        "files": files,
        "global_initial_delay": config.get("global_initial_delay", 0),
    }


@app.post("/api/asset-config", dependencies=[Depends(verify_credentials)])
def update_asset_config(payload: AssetConfigPayload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with ASSETS_CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(payload.config, file, ensure_ascii=False, indent=2)
    return {"status": "success"}


@app.post("/api/assets/upload", dependencies=[Depends(verify_credentials)])
def upload_asset(file: UploadFile = File(...)):
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = ASSETS_DIR / file.filename
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "filename": file.filename}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/assets/{filename}", dependencies=[Depends(verify_credentials)])
def delete_asset(filename: str):
    file_path = ASSETS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    file_path.unlink()
    return {"status": "deleted"}


@app.get("/assets/{filename}")
def serve_asset(filename: str) -> FileResponse:
    file_path = ASSETS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    media_type = MIME_MAP.get(file_path.suffix.lower(), "application/octet-stream")
    logger.info("Servindo %s com Content-Type: %s", filename, media_type)
    return FileResponse(path=file_path, media_type=media_type, filename=filename)


@app.on_event("startup")
def startup_event() -> None:
    session_store.initialize()
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Robo inicializado em modo agente de atendimento")
    logger.info("Admin area disponivel em /admin")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/test-capi", dependencies=[Depends(verify_credentials)])
def test_capi(payload: TestCapiPayload):
    if not settings.fb_pixel_id or not settings.fb_access_token:
        raise HTTPException(status_code=400, detail="Pixel/Token nao configurados no .env")
    import time
    import requests
    url = f"https://graph.facebook.com/v19.0/{settings.fb_pixel_id}/events"
    data = {
        "data": [{
            "event_name": "Purchase",
            "event_time": int(time.time()),
            "action_source": "system_generated",
            "user_data": {"client_user_agent": "WhatsApp/admin_tester"},
            "custom_data": {"currency": "BRL", "value": 24.90}
        }],
        "access_token": settings.fb_access_token
    }
    if payload.test_event_code:
        data["test_event_code"] = payload.test_event_code
    try:
        res = requests.post(url, json=data, timeout=10)
        res.raise_for_status()
        return {"status": "success", "meta": res.json()}
    except requests.exceptions.RequestException as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=500, detail=detail)


@app.post("/webhook")
def webhook(payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    logger.info("=== WEBHOOK PAYLOAD COMPLETO === %s", payload)
    event_name = payload.get("event")
    data = payload.get("data") or {}

    if event_name != "message":
        return {"status": "ignored", "reason": f"evento {event_name!r} nao tratado"}

    if data.get("isGroup"):
        return {"status": "ignored", "reason": "mensagem de grupo"}

    if data.get("from", "").endswith("@g.us"):
        return {"status": "ignored", "reason": "mensagem de grupo"}

    if data.get("fromMe"):
        return {"status": "ignored", "reason": "mensagem propria (fromMe)"}

    message_type = data.get("type", "text")
    if message_type not in {
        "chat", "conversation", "text", "extendedTextMessage", 
        "image", "video", "audio", "ptt", "document"
    }:
        return {"status": "ignored", "reason": f"tipo {message_type!r} nao tratado"}

    phone = data.get("resolvedPhone") or data.get("from", "")
    session_id = data.get("from", "")
    message_text = data.get("body", "")
    media_base64 = data.get("mediaBase64", "")
    media_mimetype = data.get("mimetype", "")

    ctwa_clid = data.get("ctwaClid", "")
    if ctwa_clid:
        logger.info("CTWA Click ID detectado: %s | Telefone: %s", ctwa_clid, phone)
        logger.info(
            "Origem: %s | App: %s | Anuncio: %s",
            data.get("entryPointConversionSource", ""),
            data.get("entryPointConversionApp", ""),
            data.get("adTitle", ""),
        )

    if not phone:
        raise HTTPException(status_code=400, detail="Payload sem telefone do remetente.")

    logger.info("Telefone real: %s | Sessao: %s | Mensagem: %s", phone, session_id, message_text)

    try:
        # Extract message ID
        # Many gateways send message id as "id" or "key.id"
        msg_id: str = ""
        key_data = data.get("key")
        if isinstance(key_data, dict):
            msg_id = key_data.get("id", "")
        if not msg_id:
            msg_id = data.get("id", "")
            
        background_tasks.add_task(
            flow_engine.handle_incoming_message,
            chat_id=session_id,
            phone=phone,
            message_text=message_text,
            ctwa_clid=ctwa_clid,
            message_id=msg_id,
            message_type=message_type,
            media_base64=media_base64,
            media_mimetype=media_mimetype,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Erro ao colocar o processamento do webhook em background")
        return {"status": "error", "detail": str(exc)}

    return {"status": "processed"}
