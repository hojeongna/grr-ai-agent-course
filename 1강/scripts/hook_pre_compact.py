#!/usr/bin/env python3
"""PreCompact 훅 — 대화가 너무 길어져서 컨텍스트를 압축(요약)하기 직전에 실행됩니다.

역할: "곧 기억을 정리한다"는 걸 텔레그램으로 알림.
      (실제 대화 내용 보존은 SessionStart 훅이 이어받아 처리합니다.)
"""
import subprocess
import sys
from pathlib import Path

NOTIFY = Path(__file__).resolve().parent / "notify_telegram.py"

subprocess.run(
    [sys.executable, str(NOTIFY), "🧠 대화가 길어져서 기억을 정리하는 중... (압축 직전)"],
    check=False,
)
