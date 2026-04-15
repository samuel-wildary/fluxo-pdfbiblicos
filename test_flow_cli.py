from __future__ import annotations

import json
import sys
import types
from typing import Any

# O flow_engine importa session_store, que por sua vez importa redis.
# Para o teste local em terminal, nao precisamos de Redis real.
if "redis" not in sys.modules:
    fake_redis = types.ModuleType("redis")

    def _unused_from_url(*args, **kwargs):
        raise RuntimeError("Redis nao e usado no test_flow_cli.py")

    fake_redis.from_url = _unused_from_url
    sys.modules["redis"] = fake_redis

from app.flow_engine import FlowEngine, extract_phone


class InMemorySessionStore:
    def __init__(self) -> None:
        self._agent_states: dict[str, dict[str, Any]] = {}

    def get_agent_state(self, chat_id: str) -> dict[str, Any]:
        return dict(self._agent_states.get(chat_id, {}))

    def set_agent_state(self, chat_id: str, state: dict[str, Any]) -> None:
        merged = dict(self._agent_states.get(chat_id, {}))
        merged.update(state)
        self._agent_states[chat_id] = merged


class DummyWhatsAppClient:
    pass


def render_actions(actions: list[dict[str, Any]]) -> None:
    if not actions:
        print("\n[sem acoes]\n")
        return

    print()
    for index, action in enumerate(actions, start=1):
        action_type = action.get("type")
        if action_type == "text":
            print(f"[{index}] TEXTO")
            print(action.get("text", ""))
        elif action_type == "media":
            print(f"[{index}] MIDIA: {action.get('media_path', '')}")
            caption = action.get("caption")
            if caption:
                print("CAPTION:")
                print(caption)
        else:
            print(f"[{index}] ACAO: {json.dumps(action, ensure_ascii=False)}")
        print()


def main() -> None:
    chat_id = "cli_test_5585999999999"
    session_store = InMemorySessionStore()
    engine = FlowEngine(
        session_store=session_store,
        client=DummyWhatsAppClient(),
        public_base_url="http://localhost:8000",
        agent=None,
    )

    print("Teste local do fluxo")
    print("Comandos: /state, /reset, /quit")
    print("-" * 40)

    while True:
        try:
            user_message = input("\nVoce: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrado.")
            return

        if not user_message:
            continue

        lowered = user_message.lower()
        if lowered == "/quit":
            print("Encerrado.")
            return
        if lowered == "/reset":
            session_store._agent_states.pop(chat_id, None)
            print("Estado resetado.")
            continue
        if lowered == "/state":
            print(json.dumps(session_store.get_agent_state(chat_id), ensure_ascii=False, indent=2))
            continue

        reply_text, actions = engine._process_deterministic_message(
            chat_id=chat_id,
            user_message=user_message,
            message_type="text",
        )

        print(f"\nSessao: {extract_phone(chat_id)}")
        if reply_text:
            print("\n[RESPOSTA DIRETA]")
            print(reply_text)
        render_actions(actions)
        print("[ESTADO]")
        print(json.dumps(session_store.get_agent_state(chat_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
