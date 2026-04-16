from __future__ import annotations

import json
import logging
import random
import re
import time
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.session_store import SessionStore
from app.whatsapp_api import WhatsAppApiClient

logger = logging.getLogger(__name__)

ASSETS_CONFIG_FILE = Path("app/data/assets_config.json")
FLOW_CONFIG_FILE = Path("app/data/flow_config.json")
AGENT_FLOW_ID = "__AGENT__"
AGENT_STEP_ID = "attending"
DEFAULT_HUMAN_DELAY_MIN_SECONDS = 1
DEFAULT_HUMAN_DELAY_MAX_SECONDS = 8


def extract_phone(chat_id: str) -> str:
    return re.sub(r"\D", "", chat_id or "")


def load_assets_config() -> dict[str, Any]:
    if not ASSETS_CONFIG_FILE.exists():
        return {}

    try:
        with ASSETS_CONFIG_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:  # pragma: no cover
        logger.error("Erro ao carregar assets_config.json: %s", exc)
        return {}


def load_flow_config() -> dict[str, Any]:
    if not FLOW_CONFIG_FILE.exists():
        return {}

    try:
        with FLOW_CONFIG_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:  # pragma: no cover
        logger.error("Erro ao carregar flow_config.json: %s", exc)
        return {}


def card_to_actions(card: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for tool in card.get("tools", []):
        kind = tool.get("kind")
        if kind == "text":
            actions.append({"type": "text", "text": str(tool.get("content") or "")})
        elif kind == "media":
            action = {"type": "media", "media_path": str(tool.get("asset") or "")}
            caption = str(tool.get("caption") or "").strip()
            if caption:
                action["caption"] = caption
            actions.append(action)
    return actions


def normalize_message_text(user_message: Any) -> str:
    return str(user_message or "").strip().lower()


def contains_number(text: str) -> bool:
    return bool(re.search(r"\b\d{1,3}\b", text))


def is_acceptance(text: str, message_type: str = "text") -> bool:
    if message_type == "audio":
        return True
    
    acceptance_terms = [
        "sim",
        "pode",
        "quero",
        "manda",
        "pode enviar",
        "pode sim",
        "fechado",
        "ok",
        "ta bom",
        "tá bom",
        "certo",
        "certinho",
        "blz",
        "prosseguir",
        "proseguir",
        "continuar",
        "seguir",
    ]
    return any(term in text for term in acceptance_terms)


def is_negative_response(text: str) -> bool:
    negative_terms = [
        "nao",
        "não",
        "nao quero",
        "não quero",
        "prefiro o simples",
        "prefiro o basico",
        "prefiro o básico",
        "so o comum",
        "só o comum",
    ]
    return any(term in text for term in negative_terms)


def is_price_objection(text: str) -> bool:
    keywords = [
        "sem dinheiro",
        "não tenho dinheiro",
        "nao tenho dinheiro",
        "não tenho pix",
        "nao tenho pix",
        "sem pix",
        "caro",
        "depois",
        "mais pra frente",
        "mais para frente",
        "sem grana",
        "vou fazer depois",
    ]
    return any(keyword in text for keyword in keywords)


def is_payment_commitment(text: str, message_type: str = "text") -> bool:
    commitment_terms = [
        "vou fazer",
        "vou pagar",
        "vou mandar",
        "ja te mando",
        "já te mando",
        "amanha",
        "amanhã",
        "depois eu faço",
        "depois eu mando",
        "entendi",
    ]
    return is_acceptance(text, message_type) or any(term in text for term in commitment_terms)


def is_hard_refusal(text: str) -> bool:
    refusal_terms = [
        "não vou fazer",
        "nao vou fazer",
        "não vou pagar",
        "nao vou pagar",
        "não quero",
        "nao quero",
        "não vou mais",
        "nao vou mais",
        "desisti",
        "parei",
    ]
    return any(term in text for term in refusal_terms)


def is_recipe_question(text: str) -> bool:
    keywords = [
        "jogo",
        "jogos",
        "joguinho",
        "joguinhos",
        "arquivo",
        "arquivos",
        "pdf",
        "imprimir",
        "impressao",
        "impressão",
        "regra",
        "regras",
        "como usa",
        "como usar",
        "instrução",
        "instrucao",
        "material",
        "materiais",
    ]
    return any(keyword in text for keyword in keywords)


def is_payment_completion_signal(text: str, message_type: str) -> bool:
    if message_type in {"image", "document"}:
        return True
    keywords = ["comprovante", "paguei", "pix feito", "pix realizado", "ja paguei", "já paguei"]
    return any(keyword in text for keyword in keywords)


class FlowEngine:
    def __init__(
        self,
        session_store: SessionStore,
        client: WhatsAppApiClient,
        public_base_url: str,
        agent=None,
    ) -> None:
        self.session_store = session_store
        self.client = client
        self.public_base_url = public_base_url.rstrip("/")
        self.agent = agent

    def handle_incoming_message(
        self,
        chat_id: str,
        message_text: str,
        phone: str | None = None,
        ctwa_clid: str = "",
        message_id: str = "",
        message_type: str = "text",
        media_base64: str = "",
        media_mimetype: str = "",
    ) -> None:
        had_existing_session = self.session_store.get_session(chat_id) is not None
        queue_size = self.session_store.enqueue_incoming_message(
            chat_id=chat_id,
            message_text=message_text,
            phone=phone,
            ctwa_clid=ctwa_clid,
            message_id=message_id,
            message_type=message_type,
            media_base64=media_base64,
            media_mimetype=media_mimetype,
        )

        if not self.session_store.try_acquire_execution_lock(chat_id):
            logger.info(
                "Atendimento em andamento para %s. Mensagem adicionada ao buffer. Itens pendentes: %s",
                chat_id,
                queue_size,
            )
            return

        self.session_store.set_session(chat_id, AGENT_FLOW_ID, AGENT_STEP_ID, is_executing=True)

        try:
            should_apply_initial_delay = not had_existing_session
            while True:
                pending_message = self.session_store.pop_next_incoming_message(chat_id)
                if not pending_message:
                    break

                resolved_phone = pending_message.get("phone") or phone or chat_id
                buffered_ctwa_clid = pending_message.get("ctwa_clid", "")
                if buffered_ctwa_clid:
                    self.session_store.set_ctwa_clid(chat_id, buffered_ctwa_clid)

                if should_apply_initial_delay:
                    self._apply_initial_delay(chat_id, resolved_phone)
                    should_apply_initial_delay = False

                self._process_buffered_message(
                    chat_id=chat_id,
                    resolved_phone=resolved_phone,
                    message_text=pending_message.get("message_text", ""),
                    message_id=pending_message.get("message_id", ""),
                    message_type=pending_message.get("message_type", "text"),
                    media_base64=pending_message.get("media_base64", ""),
                    media_mimetype=pending_message.get("media_mimetype", ""),
                )
        finally:
            self.session_store.set_session(chat_id, AGENT_FLOW_ID, AGENT_STEP_ID, is_executing=False)
            self.session_store.release_execution_lock(chat_id)

    def _apply_initial_delay(self, chat_id: str, resolved_phone: str) -> None:
        delay_seconds = self._pick_human_delay_seconds(max_override=5)
        self.client.send_presence(to=resolved_phone, presence="composing")
        logger.info(
            "Aplicando delay inicial humano de %.1f segundos para %s",
            delay_seconds,
            chat_id,
        )
        time.sleep(delay_seconds)

    def _process_buffered_message(
        self,
        chat_id: str,
        resolved_phone: str,
        message_text: str,
        message_id: str,
        message_type: str,
        media_base64: str,
        media_mimetype: str,
    ) -> None:
        reply_text = ""
        whatsapp_actions: list[dict[str, Any]] = []
        if self.agent:
            reply_text, whatsapp_actions = self.agent.process_message(
                chat_id, 
                message_text,
                message_id,
                message_type,
                self.client,
                media_base64,
                media_mimetype,
            )
        else:
            reply_text, whatsapp_actions = self._process_deterministic_message(
                chat_id=chat_id,
                user_message=message_text,
                message_type=message_type,
            )

        if reply_text:
            self._apply_human_delay_before_send(
                to=resolved_phone,
                presence="composing",
                reason="resposta em texto",
                max_override=6,
            )
            self.client.send_text(to=resolved_phone, text=reply_text)

        if whatsapp_actions:
            self._execute_actions(whatsapp_actions, chat_id, resolved_phone)

    def _process_deterministic_message(
        self,
        chat_id: str,
        user_message: str,
        message_type: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        flow_config = load_flow_config()
        cards = flow_config.get("cards", [])
        if not cards:
            return "", []

        state = self.session_store.get_agent_state(chat_id)
        if state.get("finished"):
            return "", []

        current_card_index = int(state.get("current_card_index", 0) or 0)
        current_card_index = max(0, min(current_card_index, len(cards) - 1))
        first_card_sent = bool(state.get("first_card_sent", False))
        awaiting_payment = bool(state.get("awaiting_payment", False))
        user_text = normalize_message_text(user_message)

        if not first_card_sent:
            self.session_store.set_agent_state(
                chat_id,
                {
                    "current_card_index": 0,
                    "first_card_sent": True,
                    "awaiting_payment": False,
                },
            )
            return "", card_to_actions(cards[0])

        if awaiting_payment or current_card_index >= 2:
            if is_payment_completion_signal(user_text, message_type):
                self.session_store.set_agent_state(chat_id, {"awaiting_payment": False, "finished": True})
                return "Perfeito, meu bem 💛 assim que eu confirmar aqui, continuo com voce.", []

            if is_hard_refusal(user_text):
                self.session_store.set_agent_state(chat_id, {"awaiting_payment": False, "finished": True})
                return "Tudo bem, meu bem. Se mudar de ideia ou quiser tirar alguma duvida sobre os joguinhos, eu estou por aqui.", []

            if is_price_objection(user_text) and len(cards) > 4:
                return "", card_to_actions(cards[4])

            if is_recipe_question(user_text):
                self.session_store.set_agent_state(chat_id, {"awaiting_payment": False, "finished": True})
                return (
                    "Pode seguir os arquivos e as instrucoes que te enviei 💛 se travar em alguma parte dos joguinhos ou da impressao, me fala qual que eu te explico melhor.",
                    [],
                )

            if is_payment_commitment(user_text, message_type):
                self.session_store.set_agent_state(chat_id, {"awaiting_payment": False, "finished": True})
                return (
                    "Fica tranquila, meu bem 💛 quando conseguir fazer a contribuicao, me manda o comprovante por aqui. Se tiver qualquer duvida sobre os joguinhos, pode me chamar.",
                    [],
                )

            return "", []

        if current_card_index == 0:
            if is_acceptance(user_text, message_type):
                self.session_store.set_agent_state(chat_id, {"current_card_index": 1})
                return "", card_to_actions(cards[1])
            return "", []

        if current_card_index == 1:
            if is_acceptance(user_text, message_type):
                target_index = 2
                while target_index < len(cards) - 1 and not card_to_actions(cards[target_index]):
                    target_index += 1
                self.session_store.set_agent_state(
                    chat_id,
                    {
                        "current_card_index": target_index,
                        "awaiting_payment": target_index >= 2,
                    },
                )
                if target_index >= 2:
                    self._schedule_followup(chat_id, 30 * 60, "30m")
                    self._schedule_followup(chat_id, 10 * 3600, "10h")
                return "", card_to_actions(cards[target_index])
            if is_negative_response(user_text):
                target_index = 3
                while target_index < len(cards) - 1 and not card_to_actions(cards[target_index]):
                    target_index += 1
                self.session_store.set_agent_state(
                    chat_id,
                    {
                        "current_card_index": target_index,
                        "awaiting_payment": target_index >= 2,
                    },
                )
                if target_index >= 2:
                    self._schedule_followup(chat_id, 30 * 60, "30m")
                    self._schedule_followup(chat_id, 10 * 3600, "10h")
                return "", card_to_actions(cards[target_index])
            return "", []

        if current_card_index == 2:
            if is_acceptance(user_text, message_type):
                target_index = 3
                while target_index < len(cards) - 1 and not card_to_actions(cards[target_index]):
                    target_index += 1
                self.session_store.set_agent_state(chat_id, {"current_card_index": target_index, "awaiting_payment": True})
                return "", card_to_actions(cards[target_index])
            if is_price_objection(user_text) and len(cards) > 4:
                self.session_store.set_agent_state(chat_id, {"current_card_index": 4, "awaiting_payment": True})
                return "", card_to_actions(cards[4])
            return "", []

        return "", []

    def _schedule_followup(self, chat_id: str, delay_seconds: int, followup_type: str) -> None:
        def task():
            time.sleep(delay_seconds)
            state = self.session_store.get_agent_state(chat_id)
            if not state.get("awaiting_payment") or state.get("finished"):
                return
            
            if state.get(f"followup_{followup_type}_sent"):
                return
            
            flow_config = load_flow_config()
            cards = flow_config.get("cards", [])
            if len(cards) < 5:
                return
            
            followup_card = cards[4]
            tools = followup_card.get("tools", [])
            action = None
            if followup_type == "30m" and len(tools) > 0:
                action = tools[0]
            elif followup_type == "10h" and len(tools) > 1:
                action = tools[1]
                
            if action:
                self.session_store.set_agent_state(chat_id, {f"followup_{followup_type}_sent": True})
                # Evita problemas com o chat_id no phone
                self._execute_actions(card_to_actions({"tools": [action]}), chat_id, chat_id)
                
        thread = threading.Thread(target=task, daemon=True)
        thread.start()

    def _execute_actions(self, actions: list[dict[str, Any]], chat_id: str, phone: str) -> None:
        to = extract_phone(phone or chat_id)
        logger.info("Executando acoes do agente para telefone: %s", to)

        for action in actions:
            action_type = action.get("type")

            if action_type == "wait":
                time.sleep(float(action.get("seconds", 1)))
                continue

            if action_type == "presence":
                self.client.send_presence(to=to, presence=action.get("presence", "composing"))
                continue

            if action_type == "text":
                text_val = action.get("text", "")
                if isinstance(text_val, list) and text_val:
                    text_val = random.choice(text_val)
                self._apply_human_delay_before_send(
                    to=to,
                    presence="composing",
                    reason="acao de texto",
                    max_override=6,
                )
                self.client.send_text(to=to, text=text_val)
                continue

            if action_type == "media":
                action_to_resolve = action.copy()
                media_path_raw = action.get("media_path", "")
                media_path_val = media_path_raw

                if isinstance(media_path_raw, list) and media_path_raw:
                    media_path_val = random.choice(media_path_raw)
                    action_to_resolve["media_path"] = media_path_val

                assets_config = load_assets_config()
                configured_presence = None
                configured_delay_seconds = 0.0
                if media_path_val:
                    file_meta = assets_config.get("files", {}).get(media_path_val, {})
                    configured_presence = file_meta.get("presence")
                    configured_delay_seconds = float(file_meta.get("delay_seconds", 0) or 0)

                media_type = self._detect_media_type(action_to_resolve)
                default_presence = "recording" if media_type == "audio" else "composing"
                chosen_presence = configured_presence or default_presence
                self._apply_human_delay_before_send(
                    to=to,
                    presence=chosen_presence,
                    min_override=configured_delay_seconds if configured_delay_seconds > 0 else None,
                    max_override=9 if media_type == "audio" else 7,
                    reason=f"acao de midia ({media_path_val or media_type})",
                )

                media_url = self._resolve_media_url(action_to_resolve)
                self.client.send_media(
                    to=to,
                    media_url=media_url,
                    caption=action_to_resolve.get("caption"),
                    media_type=media_type,
                )
                continue

            if action_type == "read":
                self.client.mark_read(chat_id=chat_id)
                continue

            logger.warning("Tipo de acao nao suportado: %s", action_type)

    def _resolve_media_url(self, action: dict[str, Any]) -> str:
        if action.get("media_url"):
            return action["media_url"]

        if action.get("media_path"):
            media_path = quote(action["media_path"].lstrip("/"))
            return f"{self.public_base_url}/assets/{media_path}"

        raise ValueError("Acao de media precisa de 'media_url' ou 'media_path'.")

    @staticmethod
    def _detect_media_type(action: dict[str, Any]) -> str:
        path = action.get("media_path", "") or action.get("media_url", "")
        path_lower = path.lower()

        if path_lower.endswith((".ogg", ".mp3", ".wav", ".aac", ".m4a", ".opus")):
            return "audio"
        if path_lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return "image"
        if path_lower.endswith((".mp4", ".avi", ".mov", ".mkv")):
            return "video"
        return "document"

    def _pick_human_delay_seconds(
        self,
        min_override: float | None = None,
        max_override: float | None = None,
    ) -> float:
        assets_config = load_assets_config()
        min_delay = float(assets_config.get("human_delay_min_seconds", DEFAULT_HUMAN_DELAY_MIN_SECONDS) or DEFAULT_HUMAN_DELAY_MIN_SECONDS)
        max_delay = float(assets_config.get("human_delay_max_seconds", DEFAULT_HUMAN_DELAY_MAX_SECONDS) or DEFAULT_HUMAN_DELAY_MAX_SECONDS)

        if min_delay < 0:
            min_delay = 0
        if max_delay < min_delay:
            max_delay = min_delay
        if min_override is not None:
            min_delay = max(min_delay, float(min_override))
            if max_delay < min_delay:
                max_delay = min_delay
        if max_override is not None:
            max_delay = min(max_delay, float(max_override))
            if max_delay < min_delay:
                max_delay = min_delay

        return random.uniform(min_delay, max_delay)

    def _apply_human_delay_before_send(
        self,
        to: str,
        presence: str,
        reason: str,
        min_override: float | None = None,
        max_override: float | None = None,
    ) -> None:
        delay_seconds = self._pick_human_delay_seconds(min_override=min_override, max_override=max_override)
        self.client.send_presence(to=to, presence=presence)
        logger.info("Aplicando delay humano de %.1f segundos antes de %s", delay_seconds, reason)
        time.sleep(delay_seconds)
