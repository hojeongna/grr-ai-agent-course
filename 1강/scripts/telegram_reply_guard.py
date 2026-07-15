#!/usr/bin/env python3
"""텔레그램 reply 누락 가드.

흐름:
  - UserPromptSubmit(--mark): 들어온 프롬프트에 텔레그램 <channel> 태그가 있으면
    "이번 턴엔 reply가 필요하다"는 표시(플래그 파일)를 남긴다.
  - PostToolUse(--clear, matcher mcp__plugin_telegram_telegram__reply): reply 도구가
    실제로 호출되면 플래그를 지운다.
  - Stop(--check): 턴이 끝나는 시점에 플래그가 아직 남아있으면(= 텔레그램 메시지가
    왔는데 reply를 안 보냄) block 결정을 내려 Claude가 reply를 마저 보내도록 재촉한다.

플래그 내용 = 지금까지 재촉한 횟수(정수 문자열). --mark는 "0"으로 새로 만든다.
MAX_RETRY를 넘도록 재촉해도 안 고쳐지면 무한 루프 방지를 위해 포기하고 정리한다.

(실제 프로덕션 봇의 telegram_reply_guard.py를 1강 수준으로 단순화한 버전입니다.
텍스트로 새어나온 malformed tool-call을 감지해 자동으로 대신 전송해주는 leak-detection/
autosend 로직은 뺐습니다 — 이건 실제 운영 중 생긴 특수 케이스라 1강 범위 밖입니다.)
"""
import sys
import os
import json
import tempfile

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FLAG = os.path.join(tempfile.gettempdir(), "grr-agent-telegram-pending-reply.flag")
TELEGRAM_TAG = 'source="plugin:telegram:telegram"'
MAX_RETRY = 3  # 이 횟수까지만 재촉, 넘으면 포기(무한 루프 방지)


def _read_stdin_json() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def mode_mark():
    data = _read_stdin_json()
    prompt = data.get("prompt", "") or ""
    if TELEGRAM_TAG in prompt:
        try:
            with open(FLAG, "w") as f:
                f.write("0")  # 재촉 횟수 0으로 시작
        except Exception:
            pass


def mode_clear():
    try:
        if os.path.exists(FLAG):
            os.remove(FLAG)
    except Exception:
        pass


def mode_check():
    try:
        if not os.path.exists(FLAG):
            return
        n = int(open(FLAG).read().strip() or "0")
    except Exception:
        return

    if n >= MAX_RETRY:
        mode_clear()
        return

    try:
        with open(FLAG, "w") as f:
            f.write(str(n + 1))
    except Exception:
        pass

    reason = (
        "이번 턴에 들어온 텔레그램 메시지에 아직 reply를 보내지 않았어요. "
        "화면(transcript)에만 답을 쓰면 유저에게는 전달되지 않습니다 — "
        "mcp__plugin_telegram_telegram__reply 도구로 반드시 답장을 보내세요."
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--mark":
        mode_mark()
    elif arg == "--clear":
        mode_clear()
    elif arg == "--check":
        mode_check()
