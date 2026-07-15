#!/usr/bin/env python3
"""PostCompact 훅 — 컨텍스트 압축(요약)이 끝난 직후 실행됩니다.

역할: "기억 정리가 끝났다"는 걸 텔레그램으로 알림. PreCompact와 짝을 이뤄
      "정리 시작 → 정리 끝"을 보여주는 용도입니다.

⚠️ PostCompact 훅의 stdout은 클로드의 컨텍스트로 주입되지 않습니다
   (SessionStart/UserPromptSubmit만 주입됨). 그래서 이 훅에서 정체성 파일을
   다시 읽거나 최근 대화를 불러오는 건 여기선 의미가 없습니다 —
   그 역할은 이미 SessionStart 훅(matcher에 compact 포함)이 맡고 있습니다.
"""
import subprocess
import sys
from pathlib import Path

NOTIFY = Path(__file__).resolve().parent / "notify_telegram.py"

subprocess.run(
    [sys.executable, str(NOTIFY), "🧠 기억 정리 완료! (압축 후 재개)"],
    check=False,
)
