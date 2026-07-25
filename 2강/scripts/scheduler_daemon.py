#!/usr/bin/env python3
"""tmux 기반 스케줄러 데몬 — 정해진 시각/주기마다 실행 중인 Claude Code 세션(tmux)에
"Cron : 라벨: 내용" 텍스트를 주입해서, 마치 유저가 방금 타이핑한 새 메시지처럼
UserPromptSubmit 훅을 타게 만듭니다.

왜 이런 방식인가:
  Claude Code는 크론 서버가 아니라 "세션"입니다. 세션이 떠 있어야 훅도 돌고 md 파일도
  읽힙니다. 그래서 "정해진 시각에 뭔가 하기"를 구현하려면, 별도의 OS 프로세스(이 데몬)가
  시계를 보고 있다가 tmux 세션 안에 살아있는 Claude Code한테 "새 메시지"를 흉내 내서
  집어넣는 방식을 씁니다. tmux send-keys는 실제 터미널에 키 입력을 흉내 내는 명령이라,
  Claude 입장에서는 사람이 타이핑한 것과 구분이 안 됩니다.

  주입된 텍스트는 keyword_trigger.py(UserPromptSubmit 훅)가 받아서 "Cron : 라벨:" 접두사를
  보고 알맞은 지시문을 붙여줍니다 — 이 데몬 자체는 "언제 무엇을 보낼지"만 알고,
  "받으면 뭘 할지"는 전혀 모릅니다. 역할을 분리해두면 각자 단순해집니다.

  NEWS_CHECK와 WATCH_CHECK의 차이도 그 역할 분리를 보여주는 예시입니다:
    - NEWS_CHECK: 파이썬(news_poll.py)이 RSS를 직접 파싱해서 "새 글이 있는지"까지
      판단을 끝낸 뒤, 진짜 새 글이 있을 때만 "Cron : NEWS_NEW: 제목 (링크)"를 주입합니다.
    - WATCH_CHECK: RSS가 없는 페이지라 "새 글이 있는지"를 파이썬이 완벽히 판단할
      방법은 없지만, "페이지가 아예 안 바뀌었는지"는 LLM 없이도 알 수 있습니다.
      그래서 3단계로 나눕니다 — ① 파이썬이 순수 HTTP GET으로 본문 텍스트를 받아
      해시만 비교(LLM 비용 0원, 안 바뀌었으면 여기서 끝) ② 해시가 바뀌었을 때만
      `claude -p`(헤드리스 1회성 실행)를 띄워 그 프로세스가 WebFetch로 실제 확인과
      dedup 판단까지 끝내게 함 ③ 새 글을 찾았을 때만 그 결과를
      "Cron : WATCH_NEW: 내용"으로 메인 tmux에 주입 — 메인 세션(지금 여러분과 대화
      중인 세션)에는 "진짜 새 글이 있을 때만" 도달합니다. 자세한 흐름과 이렇게
      나눈 이유는 README 참고.

CRON_SCHEDULE에 항목을 추가/수정하면 스케줄이 바뀝니다. 이 파일은 교육용으로
아주 단순화했습니다 — cron 표현식 파서 없이 "시/분 비교"만으로 세 가지 패턴만 다룹니다:
  - {"minute": 0}                → 매시 정각 (분이 0일 때)
  - {"hour": 9, "minute": 0}     → 매일 특정 시각 (9시 0분일 때)
  - {"every_minutes": 10}        → N분마다 (현재 분이 N의 배수일 때)

(실제 프로덕션 봇의 scheduler_daemon.py는 회사 업무용 크론이 30개 넘게 붙어있지만,
여기서는 그건 참고하지 않고 핵심 패턴 3개짜리 예시만 새로 짰습니다.)

실행:
  python3 scripts/scheduler_daemon.py

  보통은 tmux 세션 안에서 Claude Code를 띄운 뒤, 그와는 별도의 터미널(또는 tmux의
  다른 창)에서 이 데몬을 돌립니다. macOS라면 LaunchAgent로 등록해두면 로그인할 때마다
  자동으로 시작됩니다 (README의 "자동시작 등록" 참고).

.env 필요 값:
  TMUX_SESSION=agent   # Claude Code가 떠 있는 tmux 세션 이름 (tmux new -s agent)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
NEWS_POLL = SCRIPTS_DIR / "news_poll.py"
KST = timezone(timedelta(hours=9))
TICK_SECONDS = 60  # 1분마다 시계 확인 — 분 단위 스케줄이면 이 해상도로 충분


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


# 2026-07-27 아침 실사고로 발견: WATCH_HASH_REGEX(아래)처럼 모듈을 import하는
# 시점에 바로 os.environ에서 읽는 값이 있으면, load_env()가 main() 안에서만
# 호출되는 기존 구조에서는 항상 빈 문자열로 고정되는 버그가 생긴다 — 모듈
# 최상단 코드는 main() 호출보다 먼저 실행되기 때문에, 그 시점엔 아직 .env가
# 로드되지 않은 상태다. 그래서 여기서 미리 한 번 불러와 이후의 모든
# os.environ.get() 호출이 .env 값을 정상적으로 볼 수 있게 한다.
load_env()


def check_news():
    """news_poll.py를 --quiet로 실행해서 새 글이 있으면 tmux 주입용 메시지 리스트를 반환."""
    try:
        result = subprocess.run(
            [sys.executable, str(NEWS_POLL), "--quiet"],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
    except Exception as e:
        print(f"[scheduler] news_poll 실행 실패: {e}", file=sys.stderr)
        return None

    lines = [l for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return None

    # 새 글이 여러 개 한꺼번에 발견돼도(오랫동안 안 돌았을 때 등) 한 번에 너무 많이
    # 쏟아붓지 않게 최근 3개까지만 주입한다.
    messages = []
    for line in lines[:3]:
        title, _, link = line.partition("\t")
        messages.append(f"Cron : NEWS_NEW: {title.strip()} ({link.strip()})")
    return messages


WATCH_STATE = ROOT / "memory" / "watch-state.json"
WATCH_HASH_STATE = ROOT / "memory" / "watch-hash.json"


def _extract_content_text(html: str) -> str:
    """<script>/<style>/<head> 등 사이트 방문마다 값이 바뀌기 쉬운 영역을 제거하고
    남은 텍스트만 돌려준다. "진짜 본문 영역"만 정확히 골라내려면 사이트마다 맞는
    선택자가 있어야 하지만(사이트별로 다름), 이 정도만 걸러도 분석 스크립트·메타
    태그 같은 것 때문에 매번 해시가 달라지는 오탐은 크게 줄어든다.

    ⚠️ 완벽하지는 않다 — 조회수·"n분 전" 같은 표시처럼 본문 텍스트 안에 그대로
    섞여 있는 값은 이 방식으로 걸러지지 않는다. 그런 값 때문에 claude -p가 자꾸
    불필요하게 켜진다면, 정규식으로 그 부분만 추가로 지우거나(예: "\\d+분 전" 같은
    패턴 제거) 대상 사이트에 맞는 더 좁은 영역만 골라 해시하도록 좁히면 된다."""
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<head.*?</head>", "", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


# 2026-07-27 아침 실사고로 발견: Threads처럼 React/SPA로 만들어진 사이트는 평범한
# UA로 HTML을 받아도 실제 게시글 텍스트가 전부 <script> 안 JSON에 들어있어서,
# <script>를 지우고 나면 본문이 통째로 사라진다 — 직접 재현해보니 그 결과 해시가
# 빈 문자열의 해시(`e3b0c442...`)로 영원히 고정돼서, 새 글이 100개 올라와도
# `fetch_content_hash()`가 절대 "바뀜"으로 판정하지 못한다(claude -p 자체가
# 안 불려서 조용히 계속 아무 것도 감지 못 함 — 에러조차 안 남아서 눈치채기 더
# 어렵다). 이 강의 README가 WATCH_URL 실습 대상 1순위로 Threads를 추천하는데
# 바로 그 대상에서 이 문제가 난다.
#
# 해법(실전 프로덕션 봇이 쓰는 것과 동일): ① 검색엔진 크롤러(Googlebot) User-Agent로
# 요청하면 사이트가 SEO용으로 서버에서 완전히 렌더링한 HTML을 내려주는 경우가
# 많다(대부분의 일반 사이트에도 안전하게 통하는 UA라 기본값으로 바꿔도 무해하다).
# ② 그래도 Threads처럼 진짜 콘텐츠가 여전히 <script> 안 JSON에 있는 사이트는,
# 텍스트를 통째로 해시하는 대신 그 JSON 안의 특정 마커(Threads는 각 게시글마다
# `"code":"<shortcode>"`)만 정규식으로 뽑아서 해시한다 — "지금 보이는 게시글
# 목록 자체가 바뀌었는지"만 정확히 잡아내고, 무관한 토큰 변화엔 영향받지 않는다.
#
# WATCH_HASH_REGEX를 .env에 설정하면(비우면 기존 방식) 이 정규식 매치 결과들을
# 정렬해서 해시한다 — Threads라면 `WATCH_HASH_REGEX="code":"([A-Za-z0-9_-]{6,})"`.
WATCH_HASH_REGEX = os.environ.get("WATCH_HASH_REGEX", "").strip()


def fetch_content_hash(url: str):
    """WebFetch(에이전트 전용 도구)를 쓰지 않고, HTTP GET으로 원본 HTML을 받아와
    해시한다 — 이 단계는 LLM을 한 번도 부르지 않으므로 비용이 0원이다.

    Googlebot UA를 기본으로 쓴다(대부분 사이트에 무해하고, SPA 사이트에서 더
    완전한 HTML을 받을 확률이 높다). WATCH_HASH_REGEX가 설정돼 있으면 그 정규식
    매치 목록을 해시하고(SPA 대응), 없으면 기존처럼 태그 제거 후 본문 텍스트를
    해시한다."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[scheduler] 페이지 요청 실패: {e}", file=sys.stderr)
        return None

    if WATCH_HASH_REGEX:
        matches = sorted(set(re.findall(WATCH_HASH_REGEX, html)))
        if not matches:
            print(
                "[scheduler] WATCH_HASH_REGEX가 설정돼 있는데 매치가 0개입니다 — "
                "정규식이 이 사이트 구조와 안 맞을 수 있습니다(이번 주기는 건너뜀, "
                "오탐으로 영구 고착 방지).",
                file=sys.stderr,
            )
            return None
        return hashlib.sha256(",".join(matches).encode("utf-8")).hexdigest()

    content = _extract_content_text(html)
    if not content:
        print(
            "[scheduler] ⚠️ 태그를 걷어내고 남은 본문이 비어있습니다 — 이 사이트가 "
            "React/SPA라 실제 콘텐츠가 <script> 안 JSON에 있을 가능성이 높습니다. "
            "이대로면 해시가 영원히 고정돼 새 글을 절대 못 잡습니다. .env에 "
            "WATCH_HASH_REGEX를 설정하세요(Threads 예시는 README 참고).",
            file=sys.stderr,
        )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_watch_hash():
    if not WATCH_HASH_STATE.exists():
        return None
    try:
        return json.loads(WATCH_HASH_STATE.read_text(encoding="utf-8")).get("hash")
    except Exception:
        return None


def _save_watch_hash(value: str):
    WATCH_HASH_STATE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_HASH_STATE.write_text(json.dumps({"hash": value}), encoding="utf-8")


# claude -p를 이 프로젝트 폴더(ROOT)에서 그대로 띄우면, Claude Code가 세션 시작
# 시 CLAUDE.md를 자동으로 읽고 .claude/settings.json에 등록된 훅(SessionStart·
# UserPromptSubmit 등)도 그대로 실행해버립니다 — 헤드리스(-p)라고 예외가 아닙니다.
# 그래서 좁게 "URL 하나 확인해줘" 정도의 지시만 줘도, 프로세스는 1강에서 설정한
# 정체성/규칙을 전부 이어받아 그 규칙대로 "알아서" 움직일 수 있습니다. README
# "claude -p를 헤드리스로 띄울 때 반드시 알아야 할 것" 섹션 참고 — 그래서 이
# 감지용 claude -p는 CLAUDE.md가 없는 별도 디렉토리(ISOLATED_CWD)에서 띄웁니다.
ISOLATED_CWD = Path.home() / ".claude-isolated-cwd"

# 2026-07-27 새벽 실사고로 발견한 별도 문제 — cwd 격리와는 무관합니다. LaunchAgent나
# systemd 같은 백그라운드 서비스로 이 데몬을 돌리면, 같은 claude -p 명령이 터미널에서
# 직접 실행할 땐 매번 성공하면서 서비스로 띄우면 거의 매번 "OAuth session expired and
# could not be refreshed"로 실패하는 걸 실전 프로덕션 봇에서 겪었습니다. 원인은 claude
# CLI가 OAuth 토큰을 macOS 로그인 키체인(Keychain)에서 읽어오는데, 백그라운드
# 서비스로 뜬 프로세스는 이 키체인 접근이 막히기 때문입니다(대화형 세션에서 실행한
# 프로세스는 이미 열려있는 로그인 키체인에 접근할 수 있어 문제가 없습니다) — 실제로
# 이 정확한 명령을 임시 LaunchAgent 하나로 다시 띄워봐서 100% 재현되는 것까지
# 확인했습니다. 해법은 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수로 토큰을 직접 넘기는
# 것입니다 — 이러면 claude CLI가 키체인 조회 자체를 건너뜁니다.
CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude/.credentials.json"


def _claude_oauth_env():
    """~/.claude/.credentials.json에서 accessToken을 읽어 CLAUDE_CODE_OAUTH_TOKEN으로
    넘길 환경변수 dict를 만듭니다. 매 호출마다 파일에서 새로 읽으므로, 클로드 코드가
    내부적으로 토큰을 주기적으로 갱신해도 항상 최신 값을 씁니다.

    ⚠️ Windows(WSL)에서도 이 정확한 실패가 재현되는지는 아직 확인 못 했습니다 —
    WSL은 macOS 키체인이 아니라 자체 자격증명 저장 방식(또는 파일)을 쓸 수 있어서
    양상이 다를 수 있습니다. 다만 이 fallback 자체(토큰을 env var로 직접 넘기기)는
    플랫폼과 무관하게 안전한 예방책이라 그대로 유지하는 걸 권장합니다 — 백그라운드
    서비스로 자동화를 돌릴 때 흔히 마주치는 "OS 자격증명 저장소는 대화형 세션에만
    열려있다"는 클래스의 문제이기 때문입니다."""
    try:
        import json as _json
        creds = _json.loads(CLAUDE_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        token = creds.get("claudeAiOauth", {}).get("accessToken")
        if token:
            return {"CLAUDE_CODE_OAUTH_TOKEN": token}
    except Exception:
        pass
    return {}


WATCH_CHECK_PROMPT_TEMPLATE = """다음 URL에 새 게시물이 있는지 확인하세요: {url}

1. WebFetch로 이 URL을 열어 최신 게시물들의 본문 텍스트(원문 그대로, 요약 금지)와
   개별 permalink를 뽑으세요. 이미지가 첨부된 것으로 보이면 "이 페이지의 모든
   img 태그 src 속성값을 쿼리스트링까지 정확히 나열해줘" 형태로 다시 WebFetch해서
   후보 URL도 같이 뽑으세요(다운로드는 하지 마세요 — URL만 보고).
2. {watch_state}를 Read해서 이미 처리한 permalink 목록과 대조해 새 글만 골라내세요
   (파일이 없으면 {{"seen": []}}로 새로 생성). 처음 확인하는 경우엔 지금 보이는
   글들의 permalink를 기준점으로만 저장하고 4번은 건너뛰세요(오탐 방지).
3. 새 글이 없으면 아무것도 출력하지 말고 조용히 종료하세요.
4. 새 글이 있으면, 그 permalink들을 {watch_state}의 seen 목록에 추가해서
   저장(Write/Edit)한 뒤, 새 글마다 아래 블록을 반복해서 출력하세요(다른 말은
   덧붙이지 마세요, 블록 사이는 빈 줄 하나):
   PERMALINK: <permalink>
   TEXT: <원문 텍스트, 한 줄로>
   IMG_URLS: <쉼표로 구분한 img src 목록, 없으면 NONE>
"""


def check_watch_url():
    """RSS가 없는 페이지는 3단계로 확인한다.

    ① 파이썬이 순수 HTTP GET(fetch_content_hash)으로 본문 텍스트 해시만 비교한다
       — LLM을 전혀 부르지 않으므로 비용이 0원이다. 지난번과 해시가 같으면(=페이지
       내용이 그대로면) 여기서 바로 끝낸다.
    ② 해시가 달라졌을 때만(=뭔가 바뀌었을 때만) claude -p로 띄운 별도 헤드리스
       프로세스가 WebFetch로 실제 확인과 dedup 판단까지 한다.
    ③ 그 프로세스가 진짜 새 글을 찾았을 때만 결과를 메인 tmux에 주입한다.

    왜 이렇게 나눴는가: 메인 세션(지금 여러분과 대화 중인 세션)에 매번 "확인해봐"를
    주입하면, 세션이 길어질수록 그 누적된 대화 컨텍스트를 통째로 다시 읽어가며
    판단해야 해서 체크 한 번의 비용이 계속 늘어난다 — 새 글이 없는 대다수의
    체크에서도 마찬가지다. claude -p만 썼다면 적어도 메인 세션 비용 문제는
    해결되지만, 그래도 "페이지에 아무 변화가 없는" 대다수의 체크마다 여전히 LLM
    프로세스를 하나씩 띄우는 비용이 남는다. ①의 순수 파이썬 해시 비교를 맨 앞에
    두면 그 비용마저 없앨 수 있다 — claude -p는 "정말 뭔가 바뀌었을 때만" 켜지고,
    메인 세션은 "정말 보여줄 새 글이 있을 때만" 깨어난다.

    .env에 WATCH_URL이 없으면(선택 항목) 이 스케줄은 조용히 건너뛴다."""
    url = os.environ.get("WATCH_URL", "").strip()
    if not url:
        return None

    # 1단계 — 순수 파이썬 해시 비교. 안 바뀌었으면 claude -p조차 부르지 않는다.
    new_hash = fetch_content_hash(url)
    if new_hash is None:
        return None  # 페이지 요청 자체가 실패 — 이번 주기는 건너뛴다
    if new_hash == _load_watch_hash():
        return None  # 본문 영역이 지난번과 동일 — 여기서 끝
    _save_watch_hash(new_hash)

    # 2단계 — 뭔가 바뀌었을 때만 claude -p로 실제 확인·판단.
    # cwd를 ROOT(이 프로젝트 폴더)가 아니라 ISOLATED_CWD로 지정합니다 — CLAUDE.md가
    # 없는 위치라야 페르소나/훅이 안 붙습니다. 필요한 파일 경로(watch_state 등)는
    # 위에서 이미 절대경로로 넘기고 있어서 cwd를 바꿔도 그대로 잘 동작합니다.
    ISOLATED_CWD.mkdir(parents=True, exist_ok=True)
    prompt = WATCH_CHECK_PROMPT_TEMPLATE.format(url=url, watch_state=WATCH_STATE)
    env = os.environ.copy()
    env.update(_claude_oauth_env())  # 백그라운드 서비스의 키체인 접근 문제 회피
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--dangerously-skip-permissions"],
            capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(ISOLATED_CWD), env=env,
        )
    except Exception as e:
        print(f"[scheduler] claude -p 실행 실패: {e}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"[scheduler] claude -p 종료코드 {result.returncode}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return None

    blocks = _parse_watch_blocks(result.stdout)
    if not blocks:
        return None
    messages = []
    for b in blocks:
        media_path = _download_watch_media(b["permalink"], b["img_urls"])
        media_note = media_path if media_path else "NONE"
        messages.append(
            f"Cron : WATCH_NEW: {b['text']}|MEDIA:{media_note}|LINK:{b['permalink']}"
        )
    return messages


def _parse_watch_blocks(stdout: str):
    """claude -p 출력(PERMALINK/TEXT/IMG_URLS 블록 반복)을 파싱한다."""
    blocks = []
    for chunk in re.split(r"\n\s*\n", stdout.strip()):
        m_perm = re.search(r"PERMALINK:\s*(.+)", chunk)
        if not m_perm:
            continue
        m_text = re.search(r"TEXT:\s*(.+?)(?=\nIMG_URLS:|\Z)", chunk, re.S)
        m_img = re.search(r"IMG_URLS:\s*(.+)", chunk)
        blocks.append({
            "permalink": m_perm.group(1).strip(),
            "text": (m_text.group(1).strip() if m_text else ""),
            "img_urls": (m_img.group(1).strip() if m_img else "NONE"),
        })
    return blocks


WATCH_DOWNLOADS_DIR = ROOT / "memory" / "downloads"


def _download_watch_media(permalink: str, img_urls_csv: str):
    """새 글 하나를 받아 미디어까지 자동으로 받아둔다 — 메인 세션은 다운로드를
    직접 하지 않고, 이미 받아진 로컬 경로만 넘겨받는다(2강 심화: 감지 직후
    파이썬이 미디어까지 끝내는 패턴, 실전 봇도 같은 이유로 이렇게 바꿨다 —
    README "감지와 처리를 분리하기" 참고).

    영상부터 시도하고(download_video.py — 대부분 사이트에서 이미지 URL만으로는
    영상 여부를 구분하기 어려워, 영상 없는 글이면 그냥 실패로 끝나고 다음
    단계로 넘어간다), 실패하면 IMG_URLS의 첫 번째 URL을 이미지로 받는다."""
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS_DIR))
    from download_video import download as _download_video
    from download_media import download as _download_image

    WATCH_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", permalink.rstrip("/").split("/")[-1])[:60]

    video_path = WATCH_DOWNLOADS_DIR / f"{slug}.mp4"
    try:
        if _download_video(permalink, str(video_path)):
            return str(video_path)
    except Exception as e:
        print(f"[scheduler] 영상 다운로드 시도 실패(정상 — 영상 없는 글일 수 있음): {e}", file=sys.stderr)

    if img_urls_csv and img_urls_csv.strip().upper() != "NONE":
        first_url = img_urls_csv.split(",")[0].strip()
        if first_url:
            img_path = WATCH_DOWNLOADS_DIR / f"{slug}.jpg"
            try:
                if _download_image(first_url, str(img_path)):
                    return str(img_path)
            except Exception as e:
                print(f"[scheduler] 이미지 다운로드 실패: {e}", file=sys.stderr)

    return None


# 교육용 예시 3개 — 필요하면 자유롭게 추가/수정하세요.
CRON_SCHEDULE = [
    {
        "id": "HEARTBEAT",
        "desc": "매시 정각 하트비트 (살아있는지 확인용 — keyword_trigger.py가 조용히 처리)",
        "when": {"minute": 0},
        "message": "Cron : HEARTBEAT:",
    },
    {
        "id": "NEWS_CHECK",
        "desc": "10분마다 RSS 새 글 확인 (news_poll.py가 파이썬으로 직접 판단)",
        "when": {"every_minutes": 10},
        "handler": check_news,
    },
    {
        "id": "WATCH_CHECK",
        "desc": "5분마다 RSS 없는 페이지 확인 (① 파이썬 해시 프리체크 → ② 바뀌었을 때만 claude -p 헤드리스가 확인·판단 → ③ 새 글이면 파이썬이 미디어까지 자동 다운로드해서 메인에 주입, WATCH_URL 설정 시에만)",
        "when": {"every_minutes": 5},
        "handler": check_watch_url,
    },
]


def matches(when: dict, now: datetime) -> bool:
    if "hour" in when and now.hour != when["hour"]:
        return False
    if "minute" in when and now.minute != when["minute"]:
        return False
    if "every_minutes" in when and now.minute % when["every_minutes"] != 0:
        return False
    return True


def inject_tmux(text: str):
    session = os.environ.get("TMUX_SESSION", "agent")
    try:
        # -l(literal) 플래그로 보내야 메시지 안에 우연히 tmux 키 이름과 같은 문자열이
        # 있어도 안전하게 '문자 그대로' 입력됩니다. Enter는 별도 호출로 눌러줍니다.
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "-l", text],
            check=True, timeout=5, capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "Enter"],
            check=True, timeout=5, capture_output=True,
        )
        print(f"[scheduler] 주입: {text}")
    except Exception as e:
        print(f"[scheduler] tmux 주입 실패(세션 '{session}' 없나요? tmux new -s {session}로 먼저 만들어두세요): {e}", file=sys.stderr)


def tick(now: datetime, last_fired: dict):
    minute_key = (now.year, now.month, now.day, now.hour, now.minute)
    for entry in CRON_SCHEDULE:
        if not matches(entry["when"], now):
            continue
        # 같은 분 안에서 두 번 트리거되는 걸 방지 (tick 주기가 밀리거나 짧아져도 안전하게)
        if last_fired.get(entry["id"]) == minute_key:
            continue
        last_fired[entry["id"]] = minute_key

        if "handler" in entry:
            messages = entry["handler"]()
        else:
            messages = [entry["message"]]

        for msg in messages or []:
            inject_tmux(msg)


def main():
    load_env()
    session = os.environ.get("TMUX_SESSION", "agent")
    print(f"[scheduler] 시작 — tmux 세션 '{session}'에 주입합니다")
    for entry in CRON_SCHEDULE:
        print(f"  - {entry['id']}: {entry['desc']}")

    last_fired = {}
    while True:
        now = datetime.now(KST)
        try:
            tick(now, last_fired)
        except Exception as e:
            print(f"[scheduler] tick 오류: {e}", file=sys.stderr)
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()
