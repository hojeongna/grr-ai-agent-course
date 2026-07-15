#!/usr/bin/env python3
"""UserPromptSubmit 훅 — 들어온 프롬프트가 텔레그램 채널 메시지면, 이모지 리액션을
달아달라고 짧게 리마인드하는 문구를 stdout으로 찍어 컨텍스트에 주입합니다.

"매 메시지마다 규칙을 리마인드 주입하는 UserPromptSubmit 패턴"의 가장 단순한 예시입니다.
실전에서는 이런 식으로 매 턴마다 지켜야 할 규칙(말투, 응답 형식 등)을 짧게 상기시키는
훅을 여러 개 둘 수 있습니다.
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TELEGRAM_TAG = 'source="plugin:telegram:telegram"'

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

prompt = data.get("prompt", "") or ""

if TELEGRAM_TAG in prompt:
    print(
        "[지시] 방금 들어온 텔레그램 메시지에 "
        "mcp__plugin_telegram_telegram__react 도구로 어울리는 이모지 리액션을 하나 달아주세요."
    )
