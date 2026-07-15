#!/usr/bin/env python3
"""텔레그램으로 메시지 보내기 — 모든 훅 스크립트가 공용으로 쓰는 알림 함수.

사용법: python3 notify_telegram.py "보낼 메시지"

.env 파일에 아래 두 값이 필요합니다:
  TELEGRAM_BOT_TOKEN=...   (BotFather에서 발급받은 토큰)
  TELEGRAM_CHAT_ID=...     (내 텔레그램 챗 ID)
"""
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def send(message: str) -> bool:
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[notify_telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID가 .env에 없습니다", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
        return True
    except Exception as e:
        print(f"[notify_telegram] 전송 실패: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "(빈 메시지)"
    send(text)
