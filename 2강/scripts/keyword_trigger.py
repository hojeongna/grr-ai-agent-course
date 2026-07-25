#!/usr/bin/env python3
"""UserPromptSubmit 훅 — 키워드 트리거 패턴.

들어온 프롬프트 텍스트를 스캔해서, 미리 정의한 키워드/패턴이 매치되면 그에 연결된
"지시문"을 stdout으로 찍어(=클로드 컨텍스트에 주입) 특정 상황에 자동으로 반응하게
만듭니다. 1강의 hook_emoji_reminder.py("텔레그램 메시지엔 항상 리액션 달기")도 사실
이 패턴의 아주 좁은 예시였습니다 — 여기서는 좀 더 일반화해서 여러 키워드를 한 파일에서
관리합니다.

스케줄러(scheduler_daemon.py)가 tmux에 주입하는 "Cron : 라벨: 내용" 형태의 텍스트도
결국 UserPromptSubmit으로 들어오는 새 프롬프트이기 때문에, 이 훅에서 "Cron :"로
시작하는 프롬프트를 특별 취급해서 라벨별로 다른 지시문을 붙일 수 있습니다 — 이게
"크론이 트리거를 던지면 클로드가 알아서 후속 행동을 한다"는 흐름의 핵심입니다.

(실제 프로덕션 봇의 keyword_trigger.py에는 회사 업무용 트리거가 수십 개 있지만,
여기서는 누구나 감 잡을 수 있는 일반적인 예시 몇 개만 새로 짰습니다. KEYWORD_TRIGGERS
목록에 항목을 추가/수정하면 바로 새로운 자동 반응이 생깁니다 — 실전에서는 이 목록을
TRIGGERS.md 같은 문서로 따로 정리해두고, 스크립트는 그 목록을 순회하며 매치만 하는
식으로 뼈대만 유지하는 게 좋습니다.)
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# 키워드 → 지시문. "match"는 프롬프트 전체 텍스트를 받아 True/False를 돌려주는 함수.
KEYWORD_TRIGGERS = [
    {
        "id": "출발_인사",
        "match": lambda p: "출발" in p,
        "instruction": (
            "[지시] 방금 유저가 '출발'이라는 키워드를 말했어요. "
            "오늘 하루 잘 다녀오라는 인사를 짧고 자연스럽게 건네주세요."
        ),
    },
    {
        "id": "고마움_리액션",
        "match": lambda p: "고마워" in p or "고맙" in p,
        "instruction": (
            "[지시] 유저가 고마움을 표현했어요. 어울리는 이모지로 리액션을 달고, "
            "너무 겸손 떨지 말고 자연스럽게 받아주세요."
        ),
    },
    {
        # 스케줄러(scheduler_daemon.py)의 NEWS_CHECK 항목이 새 글을 발견하면
        # "Cron : NEWS_NEW: 제목 (링크)" 형태로 주입합니다.
        "id": "뉴스_요약_지시",
        "match": lambda p: p.strip().startswith("Cron : NEWS_NEW:"),
        "instruction": (
            "[지시] 스케줄러가 새 글을 발견해서 이 프롬프트를 주입했습니다. "
            "프롬프트에 담긴 링크를 WebFetch로 열어보고, 2~3문장으로 요약해서 "
            "notify_telegram.py(또는 텔레그램 reply 도구)로 알려주세요."
        ),
    },
    {
        # 매시 정각 하트비트는 "살아있다"는 확인용일 뿐이라, 매번 알림을 보내면
        # 오히려 소음이 됩니다 — 크론 트리거를 무조건 알림으로 연결하지 않는
        # "silent 모드" 예시입니다.
        "id": "하트비트_조용히",
        "match": lambda p: p.strip().startswith("Cron : HEARTBEAT:"),
        "instruction": (
            "[지시] 정시 하트비트 크론입니다. 이건 '살아있음'을 확인하는 용도라 "
            "특별히 알릴 내용이 없으면 텔레그램에 아무것도 보내지 말고 조용히 넘어가세요."
        ),
    },
    {
        # RSS가 없는 페이지는 scheduler_daemon.py의 check_watch_url()이 직접
        # claude -p(헤드리스 프로세스)를 실행해서 확인·dedup 판단까지 끝내고, 새 글이
        # 있으면 그 즉시 파이썬이 download_video.py/download_media.py로 미디어
        # 다운로드까지 자동으로 마친 뒤 "Cron : WATCH_NEW: <텍스트>|MEDIA:<로컬경로
        # 또는 NONE>|LINK:<permalink>"를 메인 tmux에 주입합니다 — 여기 메인 세션에
        # 도달했다는 것 자체가 "진짜 새 글이고, 미디어도 이미 로컬에 준비됐다"는
        # 뜻입니다. 그래서 이 트리거는 WebFetch·dedup·다운로드를 다시 하지 않고,
        # 순수 판단이 필요한 부분(인사이트 작성)과 전달·아카이빙만 담당합니다 —
        # "감지·다운로드는 파이썬, 판단·전달은 메인 세션"으로 역할을 나눈 예시입니다.
        "id": "웹페이지_새글_알림",
        "match": lambda p: p.strip().startswith("Cron : WATCH_NEW:"),
        # 출력 형식을 여기서 못박아 둡니다("정리해서 전달하세요" 같은 자유 지시만
        # 주면 세션마다 헤더가 있다/없다, 필드 순서가 바뀌는 식으로 드리프트가
        # 생깁니다 — README "알림 포맷이 자꾸 달라진다면" 참고).
        "instruction": lambda p: (
            "[지시] claude -p로 띄운 별도 프로세스가 이미 새 글을 확인했고, 파이썬이 "
            "미디어 다운로드까지 끝냈습니다(MEDIA가 NONE이 아니면 그 경로에 파일이 이미 "
            "있습니다 — 다시 다운로드하지 마세요). 아래 형식으로 정확히 조립해서 텔레그램으로 "
            "전달하세요(구조를 임의로 바꾸지 마세요, 원문은 요약하지 말고 그대로, MEDIA 경로가 "
            "있으면 reply 도구의 파일 첨부로 같이 보내세요):\n"
            "  '📡 <소스 이름>' 제목줄\n"
            "  (빈 줄)\n"
            "  <원문 그대로>\n"
            "  (빈 줄)\n"
            "  <한 줄 코멘트>\n"
            "  (빈 줄)\n"
            "  <링크>\n"
            f"원본 페이로드: {p.strip().split('Cron : WATCH_NEW:', 1)[1].strip()}\n"
            "(형식은 '<텍스트>|MEDIA:<경로 또는 NONE>|LINK:<permalink>' 입니다 — '|'로 3개 "
            "필드를 나눠서 파싱하세요.)"
        ),
    },
]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    prompt = data.get("prompt", "") or ""
    if not prompt:
        return

    for trigger in KEYWORD_TRIGGERS:
        try:
            if trigger["match"](prompt):
                instr = trigger["instruction"]
                print(instr(prompt) if callable(instr) else instr)
        except Exception:
            continue


if __name__ == "__main__":
    main()
