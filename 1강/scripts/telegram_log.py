#!/usr/bin/env python3
"""텔레그램 대화 자동 로거 — 인바운드(유저)/아웃바운드(에이전트) 메시지를 jsonl로 적재.

텔레그램 봇 API엔 대화 history 조회 기능이 없어서, 메시지가 오갈 때마다 훅으로
직접 기록해두고 SessionStart 훅의 "최근 대화 불러오기"가 이 파일을 읽습니다.

훅 연결 (.claude/settings.json):
  - UserPromptSubmit:  python3 scripts/telegram_log.py --inbound
      stdin(JSON)의 prompt 안 <channel source="plugin:telegram:telegram" ...>...</channel> 파싱
  - PostToolUse(matcher mcp__plugin_telegram_telegram__reply):
      python3 scripts/telegram_log.py --outbound
      stdin(JSON)의 tool_input.text 를 기록

레코드 형태: {"ts", "dir": "in"/"out", "chat_id", "message_id", "user", "text"}
로그 파일: memory/telegram-transcript.jsonl (append-only, 1강 폴더 기준)
"""
import sys
import os
import re
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KST = timezone(timedelta(hours=9))
# notify_telegram.py의 경로 계산 방식(Path(__file__).resolve().parent.parent)과
# 동일한 패턴을 따라 1강 폴더 루트를 기준으로 memory/ 밑에 로그를 쌓는다.
LOG_PATH = Path(__file__).resolve().parent.parent / "memory" / "telegram-transcript.jsonl"
SEEN_FILE = os.path.join(tempfile.gettempdir(), "grr-agent-telegram-seen-ids.txt")

CHANNEL_RE = re.compile(
    r'<channel\s+source="plugin:telegram:telegram"([^>]*)>(.*?)</channel>',
    re.DOTALL,
)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _to_kst(ts: str) -> str:
    """텔레그램이 주는 UTC ts(...Z)를 한국시간(+09:00) ISO로 변환. 실패하면 현재 KST."""
    if not ts:
        return _now()
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(KST).isoformat(timespec="seconds")
    except Exception:
        return _now()


def _append(rec: dict):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _seen(mid: str) -> bool:
    """인바운드 message_id 중복 방지(같은 프롬프트가 두 번 훅을 타도 1회만 기록)."""
    if not mid:
        return False
    try:
        ids = set()
        if os.path.exists(SEEN_FILE):
            ids = set(open(SEEN_FILE, encoding="utf-8").read().split())
        if mid in ids:
            return True
        ids.add(mid)
        open(SEEN_FILE, "w", encoding="utf-8").write("\n".join(list(ids)[-500:]))  # 최근 500개만 유지
    except Exception:
        pass
    return False


def _read_stdin_json() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def mode_inbound():
    data = _read_stdin_json()
    prompt = data.get("prompt", "") or ""
    for attrs_raw, body in CHANNEL_RE.findall(prompt):
        attrs = dict(ATTR_RE.findall(attrs_raw))
        mid = attrs.get("message_id", "")
        if _seen(mid):
            continue
        _append({
            "ts": _to_kst(attrs.get("ts", "")),
            "dir": "in",
            "chat_id": attrs.get("chat_id", ""),
            "message_id": mid,
            "user": attrs.get("user", ""),
            "text": body.strip(),
        })


def mode_outbound():
    data = _read_stdin_json()
    tool_input = data.get("tool_input", {}) or {}
    text = (tool_input.get("text") or "").strip()
    if not text:
        return
    # tool_response에서 전송된 message_id 추출 시도(있으면)
    mid = ""
    resp = data.get("tool_response", "")
    if isinstance(resp, dict):
        resp = json.dumps(resp, ensure_ascii=False)
    m = re.search(r"id[:\s]+(\d+)", str(resp))
    if m:
        mid = m.group(1)
    _append({
        "ts": _now(),
        "dir": "out",
        "chat_id": str(tool_input.get("chat_id", "")),
        "message_id": mid,
        "user": "에이전트",
        "text": text,
    })


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--inbound":
        mode_inbound()
    elif arg == "--outbound":
        mode_outbound()
