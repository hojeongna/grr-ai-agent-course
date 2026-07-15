#!/usr/bin/env python3
"""PostToolUse 훅 — 도구가 실행될 때마다 텔레그램 메시지 하나를 실시간으로 고쳐 쓰며
"지금 뭘 하고 있는지"를 보여줍니다.

동작 방식:
  1. 이번 턴 첫 도구 호출 → 새 메시지 전송, message_id를 임시 파일에 저장
  2. 이후 도구 호출마다 → 저장해둔 message_id로 editMessageText(같은 메시지가 그 자리에서 갱신됨)
  3. Stop 훅에서 --done 플래그로 호출하면 → "작업 완료"로 마지막 수정 + 임시 파일 정리

실제로 돌아가는 프로덕션 봇의 task_progress.py를 1강 수준으로 단순화한 버전입니다.
(디스코드 분기, 크론 턴 스킵 등은 뺐습니다 — 이 강의는 텔레그램 하나만 다루고,
스케줄러도 2강 이후에 나옵니다. 단, 병렬 도구 호출 시 진행 메시지가 두 개로
쪼개지는 문제는 프로덕션과 동일한 파일 락으로 막아둡니다 — 아래 PROGRESS_LOCK 참고.)
"""
import json
import os
import sys
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify_telegram import load_env  # .env 로드 로직 재사용

PROGRESS_MSG_FILE = os.path.join(tempfile.gettempdir(), "grr-agent-progress-msg-id.txt")
PROGRESS_LOCK = os.path.join(tempfile.gettempdir(), "grr-agent-progress.lock")
PROGRESS_COUNT_FILE = os.path.join(tempfile.gettempdir(), "grr-agent-progress-count.txt")

TOOL_LABELS = {
    "Bash": "🖥️ 터미널",
    "Read": "📖 파일 읽기",
    "Write": "📝 파일 저장",
    "Edit": "✏️ 파일 수정",
    "Glob": "🔍 파일 검색",
    "Grep": "🔎 내용 검색",
    "WebFetch": "🌐 웹 요청",
    "WebSearch": "🔍 웹 검색",
}


def get_token_and_chat():
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return token, chat_id


def get_msg_id():
    try:
        if os.path.exists(PROGRESS_MSG_FILE):
            return open(PROGRESS_MSG_FILE, encoding="utf-8").read().strip()
    except Exception:
        pass
    return None


def set_msg_id(msg_id):
    try:
        open(PROGRESS_MSG_FILE, "w", encoding="utf-8").write(str(msg_id))
    except Exception:
        pass


def bump_count() -> int:
    """이번 턴의 작업 단계 카운트 +1 (메시지에 붙여 진행감을 주고, 텍스트가 매번
    달라지게 만들어서 텔레그램의 '동일 텍스트 편집' 케이스를 줄인다)."""
    n = 0
    try:
        if os.path.exists(PROGRESS_COUNT_FILE):
            n = int(open(PROGRESS_COUNT_FILE, encoding="utf-8").read().strip() or "0")
    except Exception:
        n = 0
    n += 1
    try:
        open(PROGRESS_COUNT_FILE, "w", encoding="utf-8").write(str(n))
    except Exception:
        pass
    return n


def clear_state():
    for f in (PROGRESS_MSG_FILE, PROGRESS_LOCK, PROGRESS_COUNT_FILE):
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass


def _post(url: str, payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def send_message(token: str, chat_id: str, text: str):
    result = _post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": text},
    )
    if result.get("ok"):
        return result.get("result", {}).get("message_id")
    return None


def edit_message(token: str, chat_id: str, msg_id: str, text: str) -> bool:
    result = _post(
        f"https://api.telegram.org/bot{token}/editMessageText",
        {"chat_id": chat_id, "message_id": msg_id, "text": text},
    )
    if result.get("ok"):
        return True
    # 직전과 완전히 같은 텍스트로 edit하면 텔레그램이 400 "message is not modified"를
    # 주는데, 이건 '실패'가 아니라 '바뀐 게 없다'는 뜻 → 성공 취급(중복 새 메시지 방지)
    desc = str(result.get("description", "")).lower()
    return "not modified" in desc


def format_status(tool_name: str, tool_input: dict) -> str:
    label = TOOL_LABELS.get(tool_name, f"⚙️ {tool_name}")

    detail = ""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        detail = f"`{cmd[:80]}...`" if len(cmd) > 80 else f"`{cmd}`"
    elif tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path", "")
        parts = path.replace("\\", "/").split("/")
        detail = "/".join(parts[-2:]) if len(parts) >= 2 else path
    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")
        detail = url[:60] + "..." if len(url) > 60 else url
    elif tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", tool_input.get("query", ""))
        detail = f"`{pattern}`"

    return f"🔄 작업 중 — {label}" + (f": {detail}" if detail else "")


def done():
    """Stop 훅에서 --done 으로 호출 — 진행 메시지를 완료로 수정하고 상태 파일을 정리한다."""
    token, chat_id = get_token_and_chat()
    if not token or not chat_id:
        return
    msg_id = get_msg_id()
    if msg_id:
        edit_message(token, chat_id, msg_id, "✅ 작업 완료")
    clear_state()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--done":
        done()
        return

    token, chat_id = get_token_and_chat()
    if not token or not chat_id:
        return

    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    status_text = format_status(tool_name, tool_input) + f"  ({bump_count()}단계)"

    msg_id = get_msg_id()
    if msg_id:
        # 이미 진행 메시지가 있으면 그 자리에서 편집
        if not edit_message(token, chat_id, msg_id, status_text):
            new_id = send_message(token, chat_id, status_text)
            if new_id:
                set_msg_id(new_id)
    else:
        # 이번 턴 첫 도구 호출 → 새 메시지 전송.
        # 단, Claude가 여러 도구를 병렬로 호출하면 이 훅도 거의 동시에 여러 번
        # 실행되는데, 그러면 다 여기(msg_id 없음)로 들어와 메시지가 여러 개
        # 생겨버린다(진행 메시지 도배). 그래서 락 파일(O_EXCL, 원자적 생성)을
        # 먼저 잡은 단 하나의 호출만 새 메시지를 보내고, 나머지는 그 호출이
        # msg_id를 저장할 때까지 잠깐 기다렸다가 같은 메시지를 편집한다.
        import time
        try:
            fd = os.open(PROGRESS_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            new_id = send_message(token, chat_id, status_text)
            if new_id:
                set_msg_id(new_id)
        except FileExistsError:
            for _ in range(20):
                time.sleep(0.1)
                mid = get_msg_id()
                if mid:
                    edit_message(token, chat_id, mid, status_text)
                    break


if __name__ == "__main__":
    main()
