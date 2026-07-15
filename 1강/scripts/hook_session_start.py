#!/usr/bin/env python3
"""SessionStart 훅 — 세션이 시작되거나(startup), 압축 후 재개되거나(compact),
새로 지워질 때(clear) 실행됩니다.

역할: SOUL/IDENTITY/USER/CONTEXT/MEMORY 파일 + 최근 텔레그램 대화(최근 10개)를
      읽어 stdout으로 출력(=클로드 컨텍스트에 주입) + 텔레그램으로 "에이전트가 깨어났다"는 알림.
"""
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
NOTIFY = Path(__file__).resolve().parent / "notify_telegram.py"
TRANSCRIPT = ROOT / "memory" / "telegram-transcript.jsonl"

FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "CONTEXT.md", "MEMORY.md"]

reason = sys.argv[1] if len(sys.argv) > 1 else "startup"

for name in FILES:
    path = ROOT / name
    if path.exists():
        print(f"\n--- {name} ---")
        print(path.read_text(encoding="utf-8"))

# 최근 텔레그램 대화 불러오기 — telegram_log.py(UserPromptSubmit/PostToolUse 훅)가
# 오가는 메시지를 memory/telegram-transcript.jsonl에 계속 쌓아두고, 여기서 최근
# 10개만 꺼내 컨텍스트에 얹는다. 아직 대화가 한 번도 없었으면(첫 실행) 파일 자체가
# 없을 수 있으니 조용히 건너뛴다.
if TRANSCRIPT.exists():
    try:
        lines = [l for l in TRANSCRIPT.read_text(encoding="utf-8").splitlines() if l.strip()]
        records = []
        for line in lines[-10:]:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        if records:
            print("\n--- 최근 텔레그램 대화 (최근 10개) ---")
            for rec in records:
                who = "유저" if rec.get("dir") == "in" else "에이전트"
                print(f"[{rec.get('ts', '')}] {who}: {rec.get('text', '')}")
    except Exception:
        pass

label = {"startup": "새로 시작", "compact": "기억 압축 후 재개", "clear": "대화 초기화"}.get(reason, reason)
subprocess.run(
    [sys.executable, str(NOTIFY), f"🟢 에이전트 세션 시작({label}) — 설정 파일 읽고 준비 완료!"],
    check=False,
)
