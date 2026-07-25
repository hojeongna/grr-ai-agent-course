# 그르르AI — 나만의 AI 에이전트 만들기 · 2강

이 폴더는 그르르AI 채널 실습편 2강용 자료입니다.
1강에서 만든 에이전트에 **24시간 돌아가는 스케줄러**를 붙이고, **키워드 트리거** 훅으로
특정 상황에 자동 반응하게 만들고, **최신 소식을 스스로 불러오는** 흐름까지 완성합니다.

## 이번 강의에서 다루는 것

- **tmux 기반 스케줄러 데몬** (`scheduler_daemon.py`) — 정해진 시각/주기마다 실행 중인
  Claude Code 세션에 "새 메시지"를 흉내 내어 주입
- **키워드 트리거 훅** (`keyword_trigger.py`) — UserPromptSubmit에서 특정 키워드/패턴을
  감지해 그때그때 다른 지시문을 컨텍스트에 주입
- **최신 소식 불러오기, 두 가지 방식** (`news_poll.py` + `claude -p` 헤드리스 프리체크)
  - RSS가 있는 사이트 → 파이썬이 피드를 파싱해 새 글을 직접 판단
  - RSS가 없는 사이트 → `claude -p`로 띄운 별도 프로세스가 WebFetch로 페이지를 직접 열어
    판단 (코드가 아니라 에이전트가 도구를 써서 스스로 확인하되, **메인 세션이 아니라
    독립된 프로세스에서** 확인하는 패턴)
- **네 조각이 이어지는 흐름** — 스케줄러가 주기적으로 확인 → (RSS 없는 사이트는
  `claude -p`가 먼저 확인) → 새 글 발견 시에만 메인 tmux에 트리거 주입 → 키워드 트리거가
  받아서 "정리해서 보내라"는 지시문 주입 → 메인 세션이 텔레그램으로 전달

### 왜 메인 세션이 아니라 `claude -p`로 프리체크하는가

RSS 없는 페이지를 처음 만들 때는 "Cron : WATCH_CHECK: URL"을 메인 세션(지금 여러분과
대화 중인 세션)에 그대로 주입해서, 메인 세션이 직접 WebFetch로 열어보고 새 글인지
판단하게 만들 수도 있습니다. 동작은 합니다 — 하지만 두 가지 문제가 있습니다.

1. **세션이 길어질수록 체크 한 번의 비용이 계속 늘어납니다.** 메인 세션은 지금까지
   나눈 대화를 전부 컨텍스트로 들고 있는데, 그 상태에서 "확인해봐"가 주입되면 그
   누적된 컨텍스트를 통째로 다시 읽어가며 판단해야 합니다. 새 글이 없는 대다수의
   체크에서도 마찬가지로 비용이 듭니다.
2. **새 글이 없을 때도 매번 메인 세션의 대화 기록에 흔적이 남습니다.** 5분마다
   "확인했는데 새 글 없음"이 계속 쌓이면, 정작 중요한 대화 사이사이에 소음이 낍니다.

그래서 이 폴더의 예시는 `check_watch_url()`(`scheduler_daemon.py`)에서 직접
`claude -p "<프롬프트>" --dangerously-skip-permissions`를 실행합니다. 이건 컨텍스트
0에서 시작하는 완전히 독립된 1회성 프로세스라, 메인 세션이 몇 시간을 돌든 체크
비용이 고정됩니다. 이 프로세스가 WebFetch로 페이지를 확인하고, `memory/watch-state.json`
으로 dedup까지 판단해서, 새 글을 찾았을 때만 `NEW_POST: ...` 형식으로 결과를
출력합니다. 스케줄러는 그 출력이 있을 때만 `"Cron : WATCH_NEW: 내용"`을 메인 tmux에
주입하고, 없으면 아무 일도 하지 않습니다 — 메인 세션은 "판단"이 아니라 "정말 보여줄
새 글이 있을 때만" 깨어나는 셈입니다.

### 한 단계 더 — claude -p도 "진짜 바뀌었을 때만" 부르기

`claude -p`로 메인 세션 문제는 해결됐지만, 여전히 5분마다 한 번씩은 claude -p
프로세스 자체가 뜹니다 — 페이지에 아무 변화가 없는 대다수의 체크에서도 마찬가지로
말이죠. **WebFetch는 에이전트(클로드)의 도구라서 순수 파이썬 스크립트가 직접 부를
수는 없지만**, 평범한 HTTP GET(파이썬 표준 라이브러리 `urllib.request`)으로 원본
HTML을 받아오는 것 자체는 얼마든지 가능합니다. 그래서 `check_watch_url()`은
`claude -p`를 부르기 **전에** 한 단계를 더 거칩니다.

1. `fetch_content_hash(url)`이 `urllib.request`로 페이지 HTML을 그냥 받아옵니다
   (LLM 호출 없음, 비용 0원).
2. `<script>`/`<style>`/`<head>` 같은, 방문마다 값이 바뀌기 쉬운 영역을 정규식으로
   제거하고 남은 텍스트만 해시(`_extract_content_text` + sha256)합니다 — 페이지
   전체가 아니라 **글 목록/본문에 가까운 텍스트**만 비교 대상으로 삼는 게 핵심입니다.
   분석 스크립트나 메타 태그가 매번 바뀌어도 그건 이미 걸러졌으니 해시엔 영향을
   주지 않습니다.
3. 이 해시를 `memory/watch-hash.json`에 저장해둔 지난 값과 비교해서, **같으면
   여기서 바로 끝냅니다 — `claude -p`조차 부르지 않습니다.** 다를 때만 2단계
   (`claude -p`)로 넘어갑니다.

⚠️ 이 필터링은 완벽하지 않습니다 — 조회수나 "n분 전" 같은 표시처럼 본문 텍스트
**안에** 섞여 있는 값은 `<script>`/`<style>` 제거만으로는 걸러지지 않습니다. 실제로
써보다가 claude -p가 뭔가 계속 불필요하게 켜진다 싶으면, 그런 패턴을 정규식으로
추가로 지우거나(예: `"\d+분 전"` 제거) 대상 사이트에 맞는 더 좁은 영역만 잘라내
해시하도록 손보면 됩니다 — 사이트마다 "진짜 본문 영역"의 모양이 다르기 때문에
이 부분은 여러분이 감시하려는 페이지에 맞춰 직접 조정하는 게 정상입니다.

⚠️ `--dangerously-skip-permissions`는 이름 그대로 위험할 수 있는 플래그입니다 —
사람 확인 없이 도구를 실행하기 때문에, 이 프로세스가 손댈 수 있는 범위(작업 디렉터리,
쓸 수 있는 파일)를 좁게 유지하는 게 안전합니다. 여기서는 딱 "이 URL 확인 → 이
watch-state.json 파일에만 기록"으로 범위가 명확해서 쓴 것이고, 더 넓은 권한이
필요한 작업에는 함부로 쓰지 마세요.

### 설정만 하고 끝내지 말고, 반드시 직접 실행해서 눈으로 확인하기

스케줄러에 등록만 해두고 "몇 분/몇 시간 뒤에 결과가 오겠지" 하고 기다리지
마세요. 코드를 바꾸거나 새로 설정할 때마다, 스케줄러에 맡기기 **전에** 각 단계를
손으로 한 번씩 직접 실행해서 실제로 기대한 대로 동작하는지 눈으로 확인하는 습관을
들이세요 — 이 강의 전체에서 일관되게 지키는 원칙입니다. WATCH_URL을 새로 설정했다면
최소한 아래 순서로 확인하세요.

1. **해시 함수부터 단독으로.** `python3 -c "import sys; sys.path.insert(0,'scripts'); import scheduler_daemon as sd; print(sd.fetch_content_hash('여기에_WATCH_URL'))"`을 실행해서 진짜
   해시값(64자 16진수 문자열)이 나오는지 확인하세요. `None`이 나오면 요청 자체가
   실패한 것이니(URL 오타, 접근 차단 등) 다음 단계로 넘어가기 전에 먼저 고치세요.
2. **claude -p도 커맨드라인에서 먼저 단독 실행.** `scheduler_daemon.py`를 통하지
   말고, `WATCH_CHECK_PROMPT_TEMPLATE`에 실제 URL을 채운 프롬프트로
   `claude -p "<프롬프트>" --dangerously-skip-permissions`를 터미널에서 직접
   돌려보세요. `NEW_POST: ...`가 나오거나(새 글 있음) 아무 출력 없이 끝나는지(새
   글 없음, 정상) 확인하고, 에러가 나면 스케줄러에 넣기 전에 여기서 원인을
   잡으세요.
3. **처음 한 번은 "기준점만 저장"되는지 확인.** `memory/watch-state.json`과
   `memory/watch-hash.json`이 실제로 생성됐는지, 그리고 이 첫 실행에서는 알림이
   오지 않는 게 맞는지(첫 실행은 오탐 방지를 위해 기준점만 저장) 확인하세요.
4. **강제로 "새 글이 생긴 상황"을 재현해서 실제로 알림까지 오는지 확인.**
   `memory/watch-hash.json`을 지우거나 값을 바꿔서 다음 주기에 해시 비교가
   "달라짐"으로 뜨게 만들고, 그 뒤로 claude -p 호출 → (실제 새 글이 있다면)
   `Cron : WATCH_NEW:`가 메인 tmux에 주입 → 텔레그램 전송까지 전체 흐름이
   한 번은 실제로 눈으로 확인되게 하세요. 스케줄러가 알아서 잘 돌겠거니 하고
   넘어가지 마세요 — 실제로 될 때까지 확인하고 나서야 "설정 완료"입니다.

### RSS를 지원하지 않는 대표적인 사이트

WATCH_URL 실습 대상으로 뭘 골라야 할지 막막하다면, 아래처럼 RSS가 없는 게
일반적인 곳들을 시도해보세요.

- **Threads**(`threads.com/@계정`) — 이 강의 실제 프로덕션 봇도 이 방식으로
  Threads를 모니터링합니다. 가장 추천하는 실습 대상입니다. ⚠️ **단 React/SPA
  사이트라 `.env`에 `WATCH_HASH_REGEX`를 반드시 설정해야 합니다** — 안 하면
  1단계 해시 프리체크가 영원히 "안 바뀜"으로만 판정해서 새 글을 절대 못
  잡습니다(바로 아래 섹션 참고). `.env.example`에 Threads용 값이 이미
  채워져 있으니 그대로 복사하면 됩니다.
- **X(트위터)** — 예전엔 RSS를 제공했지만 지금은 없습니다.
- **Instagram** — 공개 프로필이라도 RSS가 없습니다.
- 대부분의 **회사 공지사항/채용공고 게시판** — 사내 시스템으로 만든 페이지는
  RSS를 안 붙이는 경우가 흔합니다.

반대로 **블로그·뉴스 플랫폼은 대부분 RSS를 이미 제공**합니다(워드프레스, 미디엄,
서브스택, 네이버 블로그 등) — 그런 곳은 `news_poll.py`(NEWS_CHECK)로 처리하는 게
더 간단하니, WATCH_URL은 진짜 RSS가 없는 곳에만 쓰세요.

### ⚠️ WATCH_URL이 React/SPA 사이트면 해시가 영원히 안 바뀔 수 있습니다

Threads로 실습하다가 "새 글을 계속 올려도 `Cron : WATCH_NEW:`가 절대 안 온다"는
상황을 만나면, cwd 격리나 claude -p 문제가 아니라 **1단계(파이썬 해시 프리체크)
자체가 고장난 것**일 가능성이 높습니다. 실제로 이 강의 원본 프로덕션 봇에서
겪은 사고입니다.

**원인:** `fetch_content_hash()`는 `<script>`/`<style>`/`<head>`를 지우고 남은
텍스트를 해시합니다. 그런데 Threads처럼 React로 만든 SPA(Single Page App)는
실제 게시글 텍스트가 **전부 `<script>` 안의 JSON 안에** 들어있습니다 —
`<script>`를 지우면 본문이 통째로 사라지고, 남는 건 CSS 변수 몇 줄뿐입니다.
직접 재현해보면 매번 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
(정확히 **빈 문자열의 SHA256**)가 나옵니다 — 새 글이 백 개가 올라와도 이 값은
절대 안 바뀝니다. `claude -p`(2단계)조차 안 불리므로 에러도 안 남아서, 겉으로는
"조용히 잘 도는 것처럼" 보이는 게 더 위험합니다.

**해법:** 본문 텍스트를 통째로 해시하는 대신, JSON 안에 반복되는 **고유 마커만
정규식으로 뽑아서** 해시합니다. Threads는 게시글마다 `"code":"<shortcode>"`
형태의 고유 ID가 박혀있으므로, 이 마커 목록이 바뀌었는지만 보면 "지금 보이는
게시글 목록 자체가 바뀌었는지"를 정확히 잡아낼 수 있습니다. `.env`에
`WATCH_HASH_REGEX`를 설정하면 `fetch_content_hash()`가 자동으로 이 방식으로
전환됩니다:

```bash
# .env
WATCH_HASH_REGEX="code":"([A-Za-z0-9_-]{6,})"
```

다른 SPA 사이트에 이 패턴을 그대로 쓸 수는 없습니다 — 사이트마다 JSON 필드
이름이 다릅니다. Googlebot UA로 받은 HTML을 직접 눈으로 열어보고(`curl -A
"Googlebot/2.1 (+http://www.google.com/bot.html)" <url>`), 게시글마다 반복되는
고유 필드를 찾아서 정규식을 맞추세요 — "모르는 사이트에 무작정 돌려보기"가
아니라 "한 번 확인하고 나서 패턴을 맞춰 쓰기"가 원칙입니다(아래 "영상이 첨부된
글은 어떻게?" 섹션과 같은 원칙).

`fetch_content_hash()`는 `WATCH_HASH_REGEX`가 비어있으면 기존처럼 본문 텍스트
전체를 해시하고, 그 결과가 빈 문자열이면(=본문이 통째로 사라졌으면) 이 문제를
의심하라는 경고를 stderr에 출력합니다 — 조용히 실패하는 대신 눈에 띄게 알려주는
것도 이 강의 전체가 반복하는 원칙입니다.

## 왜 WSL/tmux가 필요한가

1강까지는 훅이 전부 순수 파이썬 스크립트였고, 텔레그램 연결도 Claude Code 자체 기능
(Channels)이라 macOS든 Windows든 그냥 됐습니다.

2강부터는 다릅니다. 스케줄러가 "Claude Code가 살아있는 세션"에 텍스트를 주입해야
하는데, 이걸 하려면 그 세션이 **tmux**(터미널 멀티플렉서) 안에서 돌고 있어야 합니다.
tmux가 유닉스 계열 도구라서:

- **macOS / Linux** — 기본적으로 잘 지원됩니다. 설치해서 바로 쓰면 됩니다.
- **Windows** — tmux 네이티브 지원이 없습니다. **WSL(Windows Subsystem for Linux)**을
  설치해서 그 안에서 tmux와 Claude Code를 돌려야 합니다.

### tmux 설치

```bash
# macOS (Homebrew)
brew install tmux

# Linux (Debian/Ubuntu 계열)
sudo apt update && sudo apt install tmux

# Windows
# 1. PowerShell(관리자)에서 `wsl --install` 실행 후 재부팅
# 2. WSL 안(Ubuntu 등)에서 위 Linux 명령으로 tmux 설치
# 3. Claude Code도 WSL 안에서 실행 (Windows 네이티브 대신)
```

설치 확인: `tmux -V`

## 실습 흐름

### 1. 2강 파일을 1강 프로젝트에 합치기

2강은 1강에서 만든 프로젝트(`my-agent`)에 이어서 진행합니다. 새 프로젝트가 아닙니다.

```bash
mkdir -p my-agent/scripts my-agent/templates   # 폴더가 이미 있어도 안전한 명령이니 먼저 실행해둡니다
cp 2강/scripts/*.py my-agent/scripts/
cp 2강/templates/* my-agent/templates/
```

`.env.example`을 참고해서 기존 `.env`(1강에서 만든 것)에 아래 값을 추가합니다.

```
TMUX_SESSION=agent
RSS_FEED_URL=관심있는_RSS_피드_URL
WATCH_URL=
```

RSS가 있는 사이트인지 잘 모르겠으면 `/rss`, `/feed` 경로부터 확인해보세요. 유튜브
채널도 RSS를 제공합니다(`https://www.youtube.com/feeds/videos.xml?channel_id=채널ID`) —
단 이 유튜브 피드는 RSS 2.0이 아니라 **Atom** 포맷입니다. `news_poll.py`는 둘 다
파싱하도록 만들어뒀으니 어느 쪽이든 그대로 쓰면 됩니다.
`WATCH_URL`은 선택 항목이라 비워두면 해당 스케줄만 건너뜁니다.

먼저 RSS 폴링이 잘 되는지 단독으로 테스트해보세요.

```bash
python3 scripts/news_poll.py
# 첫 실행은 "기준점 저장" 문구만 뜨고 알림은 없습니다
# (전체 피드를 새 글로 오인하지 않기 위한 안전장치) — 정상입니다.
# 이후 실행부터 새 글이 있으면 표시됩니다.
```

### 2. tmux 세션 시작 + Claude Code 실행

아래 명령을 터미널에 직접 입력하세요.

```bash
tmux new -s agent          # "agent"라는 이름의 세션 생성 (.env의 TMUX_SESSION과 이름 맞추기)
cd my-agent
claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions
```

`--dangerously-skip-permissions`가 필요한 이유: 스케줄러가 주입하는 메시지는 사람이 그
자리에서 승인 버튼을 눌러줄 수 없는 백그라운드 상황이기 때문입니다. (당연히 위험을
이해하고 켜는 옵션입니다 — 이 세션에서 어디까지 허용할지는 CLAUDE.md의 Red Lines 같은
규칙으로 미리 선을 그어두세요.)

세션에서 빠져나와도(디태치, `Ctrl+b d`) Claude Code는 계속 돌아갑니다. 다시 붙으려면
`tmux attach -t agent`.

#### 나중에 다시 시작할 때 (복사·붙여넣기 한 번으로)

컴퓨터를 재부팅했거나, 오늘 설정 세션이 끝난 뒤 나중에 다시 켤 때는 아래
블록을 그대로 복사해서 터미널에 붙여넣기만 하면 됩니다 — `my-agent` 절대경로만
자신의 환경에 맞게 한 번 바꿔두면(`MY_AGENT_DIR` 값), 나머지는 그대로 씁니다.

```bash
MY_AGENT_DIR="$HOME/my-agent"   # 실제 my-agent 폴더 절대경로로 바꾸세요

tmux has-session -t agent 2>/dev/null && echo "이미 떠있습니다 — tmux attach -t agent 로 들어가세요" || \
  tmux new -s agent -d "cd \"$MY_AGENT_DIR\" && claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions"

tmux attach -t agent
```

이 블록은 세션이 이미 떠있으면 새로 만들지 않고 그냥 붙기만 합니다(중복 실행
방지). 스케줄러 데몬도 같이 자동시작(LaunchAgent/systemd)으로 등록해뒀다면
이 명령 하나로 다시 완전한 상태로 돌아옵니다 — 스케줄러는 이미 백그라운드에서
따로 돌고 있으니 신경 쓸 필요 없습니다.

### 3. keyword_trigger.py를 UserPromptSubmit 훅에 연결

`.claude/settings.json`의 `UserPromptSubmit` 훅 목록에 한 줄만 추가하면 됩니다(1강 것을
그대로 확장):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/telegram_reply_guard.py\" --mark 2>/dev/null || true" },
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/telegram_log.py\" --inbound 2>/dev/null || true" },
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/hook_emoji_reminder.py\" 2>/dev/null || true" },
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/keyword_trigger.py\" 2>/dev/null || true" }
        ]
      }
    ]
  }
}
```

(다른 훅들 — SessionStart/PreCompact/PostCompact/PostToolUse/Stop — 은 1강 그대로 둡니다.)

**연결 전에 keyword_trigger.py 혼자서도 확인해볼 수 있습니다** — 훅·tmux 없이 표준입력만
흉내 내면 됩니다:

```bash
echo '{"prompt": "Cron : HEARTBEAT:"}' | python3 scripts/keyword_trigger.py
echo '{"prompt": "출발!"}' | python3 scripts/keyword_trigger.py
```

각 줄이 어떤 지시문을 출력하는지 눈으로 먼저 확인해두면, 나중에 실제 tmux 세션에서
안 될 때 "훅 연결 문제"인지 "스크립트 로직 문제"인지 바로 구분할 수 있습니다.

### 4. scheduler_daemon.py를 백그라운드로 실행

Claude Code가 떠 있는 `agent` tmux 세션과는 **별도로** 데몬을 돌립니다. 새 터미널(또는
tmux의 새 창, `Ctrl+b c`)에서:

```bash
cd my-agent
python3 scripts/scheduler_daemon.py
```

시작하면 등록된 스케줄 목록(`CRON_SCHEDULE`)이 출력됩니다.

### 5. 몇 분 기다려서 실제로 트리거되는지 확인

- 정각까지 기다리면(`HEARTBEAT`) `agent` tmux 세션에 `Cron : HEARTBEAT:`가 입력되고
  Enter까지 눌리는 게 보입니다. `keyword_trigger.py`가 "조용히 넘어가라"는 지시문을
  주입하므로, 텔레그램에는 알림이 안 오는 게 정상입니다(silent 모드 시연).
  ⚠️ `HEARTBEAT`는 매시 **정각**에만 도니, 실행 시점에 따라 최대 59분을 기다려야 할 수
  있습니다 — 라이브로 바로 보고 싶으면 아래 팁처럼 `every_minutes`로 잠깐 바꿔서
  확인하세요.
- 10분 기다리면(`NEWS_CHECK`) `news_poll.py`가 실행되고, 새 글이 있으면
  `Cron : NEWS_NEW: 제목 (링크)`가 주입됩니다. 이번엔 클로드가 WebFetch로 실제 내용을
  확인하고 텔레그램으로 요약을 보내는 것까지 확인할 수 있습니다.
- `WATCH_URL`을 설정했다면 5분 후(`WATCH_CHECK`) 먼저 파이썬이 순수 HTTP GET으로
  본문 해시부터 비교합니다(`memory/watch-hash.json`) — 지난번과 같으면 여기서
  끝입니다. 해시가 달라졌을 때만 `claude -p`가 별도 프로세스로 그 URL을 WebFetch로
  확인하고 `memory/watch-state.json`과 대조합니다. 새 글이 있으면 그 즉시 파이썬이
  `_download_watch_media()`로 영상/이미지까지 자동 다운로드를 끝내고
  `Cron : WATCH_NEW: 텍스트|MEDIA:경로|LINK:permalink` 형태로 메인 tmux에 주입합니다
  — 메인 세션은 다운로드를 다시 하지 않고 이미 받아진 파일을 그대로 첨부해서 텔레그램에
  전달합니다. 새 글이 없으면 메인 세션엔 아무것도 주입되지 않습니다.
- 급하게 확인하고 싶으면 `CRON_SCHEDULE`에서 `HEARTBEAT`의 `"when"` 값을
  `{"minute": 0}` 대신 잠깐 `{"every_minutes": 1}`로 바꿔서(다른 항목도 같은 방식) 1분
  안에 바로 확인하고, 확인 후 원래 값으로 되돌리세요.

### 6. (선택) 자동시작 등록

터미널을 계속 열어두지 않아도 데몬이 로그인할 때마다 자동으로 뜨게 등록해둡니다.

#### Windows(WSL) — systemd 유저 서비스

최근 WSL2(Ubuntu)는 `systemd`가 기본 지원됩니다. `wsl.conf`에 `[boot] systemd=true`가
없다면 먼저 추가하고 WSL을 재시작하세요(`wsl --shutdown` 후 다시 열기).

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/agent-scheduler.service <<'EOF'
[Unit]
Description=grr-ai-agent scheduler

[Service]
ExecStart=/usr/bin/python3 /home/사용자명/my-agent/scripts/scheduler_daemon.py
WorkingDirectory=/home/사용자명/my-agent
Restart=on-failure

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now agent-scheduler.service

# 확인
systemctl --user status agent-scheduler.service
journalctl --user -u agent-scheduler.service -f   # 로그 실시간 확인
```

`ExecStart`/`WorkingDirectory`의 경로는 실제 `my-agent` 절대경로로 바꾸세요(`pwd`로 확인).
`/usr/bin/python3`도 `which python3` 결과와 다르면 그 경로로 바꿉니다 — systemd 유저
서비스는 로그인 셸의 PATH를 그대로 물려받지 않으므로 **파이썬·tmux 모두 절대경로로
지정하는 게 안전**합니다(아래 macOS 항목의 PATH 문제와 같은 이유).

#### macOS — LaunchAgent

```bash
cp templates/com.example.agent-scheduler.plist ~/Library/LaunchAgents/
# plist 안의 ProgramArguments 경로를 실제 scheduler_daemon.py 절대경로로 수정
launchctl load ~/Library/LaunchAgents/com.example.agent-scheduler.plist

# 확인
launchctl list | grep agent-scheduler

# 수정 후 반영(재시작)
launchctl unload ~/Library/LaunchAgents/com.example.agent-scheduler.plist
launchctl load ~/Library/LaunchAgents/com.example.agent-scheduler.plist
```

⚠️ **launchd는 로그인 셸의 PATH를 물려받지 않습니다.** Apple Silicon Homebrew로 설치한
tmux(`/opt/homebrew/bin/tmux`)는 launchd 기본 PATH(`/usr/bin:/bin:/usr/sbin:/sbin`)에
없어서, 터미널에서 수동 실행할 땐 잘 되던 게 LaunchAgent로 등록하면 조용히 안 될 수
있습니다. 안 될 때는 `which tmux`로 실제 경로를 확인해서 `scheduler_daemon.py`의
`inject_tmux()` 안 `"tmux"` 문자열을 그 절대경로로 바꾸거나, plist에
`EnvironmentVariables` 키로 `PATH`를 명시해주세요.

Windows(WSL)에서 systemd를 못 쓰는 구버전이라면 `nohup python3 scripts/scheduler_daemon.py &`
나 WSL 안의 일반 `cron`(`crontab -e`에 `@reboot`)으로 대신할 수 있습니다.

## RSS 없는 사이트는 어떻게? (WebFetch 패턴)

블로그나 뉴스 사이트는 대부분 RSS가 있지만, 일부 SNS 프로필 페이지처럼 RSS가 없는
곳도 있습니다. 이럴 때 흔히 떠올리는 방법은 헤드리스 브라우저로 로그인 세션을 만들어
페이지를 통째로 긁어오는 스크래핑인데, 이 강의에서는 그 방향으로 가지 않습니다.

대신 훨씬 단순한 방법을 씁니다: **에이전트(클로드) 자신의 WebFetch 도구로 그 공개
페이지를 주기적으로 열어보게** 합니다. 다만 이 "열어보기"를 메인 세션이 아니라
`claude -p`로 띄운 별도 헤드리스 프로세스가 하게 해서, 메인 세션 컨텍스트를 전혀
쓰지 않습니다(왜 그런지는 위 "왜 메인 세션이 아니라 claude -p로 프리체크하는가"
참고). 흐름은 이렇습니다.

1. `scheduler_daemon.py`의 `check_watch_url()`이 주기마다 `claude -p`를 실행해서,
   "이 URL을 WebFetch로 열어 게시글들의 본문 텍스트를 원문 그대로(요약 금지)
   가져오고, `memory/watch-state.json`에 저장된 permalink 목록과 대조해서 새
   글만 골라내라"는 프롬프트를 그 헤드리스 프로세스에 직접 넘깁니다. 이미지가
   있어 보이면 img src 목록도 같이 뽑아오게 합니다.
2. dedup 상태 관리(처리한 permalink 저장/조회)까지 그 프로세스가 Read/Write로
   직접 처리합니다 — 별도 파이썬 로직이 필요 없습니다.
3. 새 글이 있으면 프로세스가 `PERMALINK:`/`TEXT:`/`IMG_URLS:` 블록으로 결과를
   출력하고, `scheduler_daemon.py`가 그 출력을 파싱해 각 블록마다 바로 4번
   (미디어 다운로드)까지 끝낸 뒤 `Cron : WATCH_NEW: 텍스트|MEDIA:경로|LINK:permalink`
   를 메인 tmux에 주입합니다. 새 글이 없으면 아무 것도 주입되지 않습니다.
4. 새 글에 이미지/영상이 있으면, **메인 세션까지 가기 전에 파이썬이 먼저**
   `_download_watch_media()`로 처리합니다 — 영상부터 `scripts/download_video.py`로
   시도하고, 실패하면 방금 받은 IMG_URLS 첫 URL을 `scripts/download_media.py`로
   받습니다. 메인 세션은 이미 로컬에 저장된 파일 경로만 받아서 텔레그램에
   첨부하면 되고, 다운로드를 다시 하지 않습니다(왜 "받은 URL을 그 즉시" 써야
   하는지는 바로 아래 참고 — 파이썬이 자동으로 즉시 처리하므로 이 원칙이
   자연히 지켜집니다).

**왜 헤드리스 브라우저/로그인 세션이 필요 없는가:**
소셜/CDN 이미지 URL은 보통 쿼리스트링에 만료 시간이 걸린 서명 토큰(`?oh=...&oe=...`
같은 파라미터)이 붙어있는 형태로 접근을 제어합니다 — 세션·쿠키로 막는 게 아니라,
"이 URL 자체가 한동안만 유효한 발급된 티켓"인 방식입니다. WebFetch로 페이지를 읽을
때 이미 그 서명 URL이 통째로 보이기 때문에, 그 URL을 쿼리스트링까지 그대로 살려서
평범한 익명 GET 한 번(`download_media.py`) 보내면 됩니다 — 브라우저가 그 페이지를
렌더링할 때 이미지를 불러오는 것과 신호상 동일한 요청입니다. 로그인 세션을
만들거나 재사용할 필요가 아예 없습니다.

⚠️ **자주 하는 실수 1 — 쿼리스트링을 잘라먹기:** URL을 복사하다가 `?` 뒤
쿼리스트링을 잘라먹으면(예: 링크를 "깔끔하게" 다듬으려다가) 서명이 통째로 사라져서
요청이 실패합니다. 페이지에서 본 URL을 문자 그대로, 전체를 복사하세요.

⚠️ **자주 하는 실수 2 — 서명 URL을 저장해뒀다가 나중에 쓰기:** 이 서명 토큰은
**WebFetch를 호출할 때마다 새로 발급됩니다.** 실습해보면 처음엔 "목록 조회
WebFetch에서 이미지 URL을 봤으니 그걸 변수에 저장해뒀다가, 다른 글들 처리 끝나고
나중에 한꺼번에 다운로드해야지"라고 생각하기 쉬운데, 그 사이에 시간이 지나거나
WebFetch를 한 번이라도 더 호출하면 저장해둔 URL의 서명이 이미 무효화되어
`403`(URL signature mismatch)으로 실패합니다. 원칙은 **"받은 그 순간 바로
쓴다"**입니다:

1. 목록 조회 WebFetch에서 이미지 URL이 같이 보였다면 일단 그걸로 바로
   다운로드를 시도합니다.
2. 실패하면 그 게시글 하나만 다시 WebFetch로 요청해서, 방금 막 받은 새 URL로 즉시
   재시도합니다(재시도도 실패하면 텍스트 요약만 보내고 넘어갑니다 — 우회 시도는
   하지 않습니다). 이때 **"이 게시글의 이미지 URL을 알려줘" 같은 모호한 문구보다
   "이 페이지의 모든 img 태그 src 속성값을 쿼리스트링까지 정확히 나열해줘"처럼
   구체적으로 요청하는 게 더 안정적입니다** — 전자는 서명 파라미터가 잘리거나 값이
   미묘하게 바뀐 URL을 돌려주는 경우가 있었던 반면, 후자는 페이지의 실제 HTML을
   그대로 인용하라는 지시라 완전한 URL을 훨씬 안정적으로 반환합니다.

여러 게시글을 순서대로 처리한다면, 한 게시글의 이미지를 받아서 저장하기 전에
다음 게시글로 먼저 넘어가지 마세요 — "글 A의 URL 확보 → 글 B의 URL 확보 → A, B
한꺼번에 다운로드" 순서로 하면 A의 URL이 그 사이에 낡아버립니다. "글 A 확보 →
A 즉시 다운로드 → 글 B 확보 → B 즉시 다운로드"처럼 게시글 단위로 바로바로
끝내는 게 안전합니다.

이 방식에도 한계는 있습니다: 애초에 로그인해야만 보이는 콘텐츠는 이 방법으로
가져올 수 없고(그건 이 강의 범위 밖입니다), 텍스트/이미지가 공개적으로 로드되는
페이지까지만 다룹니다. 그리고 어떤 사이트든 자동으로 반복 조회하는 것이므로 너무
잦은 요청은 피하고, 공식 API가 있다면 그쪽이 더 안전한 선택입니다. 받은 이미지는
개인적으로 확인하는 용도로 쓰세요.

## 영상이 첨부된 글은 어떻게? (Googlebot 패턴)

위 `download_media.py`는 이미지에는 잘 통하는데, 영상이 첨부된 글에서는 그대로
안 통합니다. 이유는 단순합니다 — WebFetch는 페이지를 사람이 읽을 수 있는 텍스트로
바꿔서 보여주는데, 이 과정에서 `<video>` 태그 자체가 통째로 사라집니다. img
태그를 나열해달라고 아무리 구체적으로 요청해도, 영상 URL은 애초에 그 변환 결과물
안에 존재하지 않으니 나올 수가 없습니다. `download_media.py <URL>`에 넘길 URL 자체를
못 구하는 상황인 겁니다.

여기서 한 가지 성질을 이용합니다: 사이트들은 검색엔진에 잘 노출되기 위해,
**Googlebot 같은 잘 알려진 검색엔진 크롤러가 요청할 때는 서버 쪽에서 완전히
렌더링한 HTML**을 내려주는 경우가 많습니다. 사람이 브라우저로 보는 것과 크롤러가
받는 응답이 다를 수 있다는 뜻입니다. 요청 헤더의 User-Agent만 그 크롤러 이름으로
바꿔서 curl/urllib로 직접 요청하면, 이 완전히 렌더링된 HTML을 받을 수 있고 그
안에는 실제 영상 파일 URL이 JSON 형태로 파묻혀 있습니다.

```bash
# WATCH_CHECK 흐름에서, 첨부가 영상으로 확인되면 download_media.py 대신:
python3 scripts/download_video.py <게시글 permalink> memory/downloads/영상.mp4
```

동작 원리와 자세한 주의사항(⚠️ 한 페이지 HTML에 여러 게시글 데이터가 섞여있어
반드시 대상 게시글 구간만 잘라내서 찾아야 하는 이유 등)은 `scripts/download_video.py`
docstring에 정리해뒀습니다 — 실행하기 전에 한 번 읽어보세요.

⚠️ **이 방법의 성격을 정확히 알고 쓰세요.** 이건 "공식 API"가 아니라, 사이트가
검색엔진 크롤러에게만 다르게 응답하는 부수적인 동작(cloaking)에 기대는 방법입니다.
지금 특정 사이트에서 작동을 확인했다고 해서 모든 사이트에서 통한다는 뜻도 아니고,
그 사이트가 언젠가 로직을 바꾸면 더 이상 안 통할 수도 있습니다. "왜 이게 되는지"
원리를 이해하는 것과 "이게 영구히 보장된 방법이다"라고 믿는 건 다른 이야기입니다.
저빈도(이 강의 기준 최소 10분 이상 주기)로 개인적으로 확인하는 용도로만 쓰세요.

## 폴더 구조

```
2강/
├── README.md                              ← 지금 보고 있는 파일
├── .env.example                            ← 1강의 .env에 이어서 추가
├── .gitignore
├── templates/
│   └── com.example.agent-scheduler.plist    ← macOS 자동시작(LaunchAgent) 등록 예시
└── scripts/
    ├── scheduler_daemon.py                  ← tmux 기반 스케줄러 데몬 (CRON_SCHEDULE)
    ├── keyword_trigger.py                   ← UserPromptSubmit 키워드 트리거 훅
    ├── news_poll.py                         ← RSS 폴링으로 새 글 감지
    ├── download_media.py                    ← 이미지 URL 그대로 다운로드 (로그인/세션 불필요)
    └── download_video.py                    ← 영상 URL 추출·다운로드 (Googlebot UA 패턴)
```

## CRON_SCHEDULE 커스터마이징

`scheduler_daemon.py` 상단의 `CRON_SCHEDULE` 리스트에 항목을 추가/수정하면 바로
스케줄이 바뀝니다. `when`은 세 가지 패턴만 지원합니다.

| 패턴 | 의미 |
|---|---|
| `{"minute": 0}` | 매시 정각 (분이 0일 때) |
| `{"hour": 9, "minute": 0}` | 매일 특정 시각 (9시 0분) |
| `{"every_minutes": 10}` | N분마다 (현재 분이 N의 배수일 때) |

항목은 고정된 `"message"` 문자열을 주입하거나, 매번 계산이 필요하면 `"handler"`
함수(메시지 리스트 또는 `None` 반환)를 대신 넣을 수 있습니다. `check_news()`,
`check_watch_url()`이 그 예시입니다.

## 알림 포맷이 자꾸 달라진다면 (출력 템플릿 못박기)

트리거를 몇 개만 굴릴 땐 못 느끼다가, 개수가 늘어나면 반드시 겪는 문제가 있습니다 —
**같은 트리거인데 보낼 때마다 메시지 모양이 조금씩 달라지는 것**입니다. 어떤 날은
헤더 이모지가 있고 어떤 날은 없고, 필드 순서가 바뀌고, 링크 표기 방식이 오락가락하는
식입니다. 실제로 이 저장소의 원본이 된 프로덕션 봇에서 30개 넘는 트리거를 전수조사해보니,
포맷이 가장 심하게 흔들리던 트리거들은 하필 **`KEYWORD_TRIGGERS`(또는 `TRIGGERS` 딕셔너리)
자체에 항목이 없던 것들**이었습니다. 항목이 없으면 그 트리거가 들어와도 훅이 아무 포맷도
강제하지 않고, 에이전트는 세션 시작 때 읽은 문서 기억에만 의존해 그때그때 즉흥적으로
문장을 만듭니다 — 세션이 길어질수록 그 기억은 흐려지고, 드리프트는 커집니다.

**원인이 명확하니 해법도 명확합니다: instruction에 "무엇을 하라"뿐 아니라 "정확히
어떤 모양으로 보내라"까지 못박는 것.** 위 `웹페이지_새글_알림`(WATCH_NEW) 트리거를
예로 들면:

```python
# Before — 자유 지시 (매번 다르게 나갈 위험)
"instruction": lambda p: (
    "[지시] ... 아래 내용을 정리해서 텔레그램으로 전달하세요(원문 그대로, 요약하지 마세요):\n"
    f"  {p.strip().split('Cron : WATCH_NEW:', 1)[1].strip()}\n"
),

# After — 출력 템플릿까지 고정
"instruction": lambda p: (
    "[지시] ... 아래 형식으로 정확히 조립해서 전달하세요(구조를 임의로 바꾸지 마세요):\n"
    "  '📡 <소스 이름>' 제목줄\n"
    "  (빈 줄)\n"
    "  <원문 그대로>\n"
    "  (빈 줄)\n"
    "  <한 줄 코멘트>\n"
    "  (빈 줄)\n"
    "  <링크>\n"
    f"내용: {p.strip().split('Cron : WATCH_NEW:', 1)[1].strip()}"
),
```

트리거가 많아지면 매번 이렇게 통째로 쓰는 대신, **역할이 비슷한 트리거를 몇 개
카테고리로 묶어서 카테고리당 이모지/구조를 하나만 정해두는 게** 유지보수에 훨씬
낫습니다(예: "즉시 확인이 필요한 것"엔 🔴, "그냥 읽으면 되는 소식"엔 📡 하는 식).
카테고리 규칙은 `KEYWORD_TRIGGERS` 리스트 위에 주석으로 한 번만 적어두고, 각
트리거의 instruction은 "이건 🔴 카테고리 형식을 따르세요"처럼 짧게 참조만 하면
됩니다 — 실전 봇도 이 방식으로 정리했습니다.

## claude -p를 헤드리스로 띄울 때 반드시 알아야 할 것 (컨텍스트 격리)

`check_watch_url()`이 새 글 감지를 위해 `claude -p`로 별도 프로세스를 띄우는 걸
앞에서 봤습니다. 이때 **어느 디렉토리에서 띄우는지**가 생각보다 중요합니다.

**무슨 일이 생기는가:** `claude -p`를 이 프로젝트 폴더(`ROOT`, CLAUDE.md가 있는
곳)에서 그대로 실행하면, Claude Code는 헤드리스/프린트 모드라도 세션이 시작될 때
그 폴더의 `CLAUDE.md`를 자동으로 읽고, `.claude/settings.json`에 등록된 훅
(`SessionStart`, `UserPromptSubmit` 등)도 그대로 실행합니다. 즉 "URL 하나 확인해줘"
같은 좁은 지시만 줘도, 그 프로세스는 1강에서 세팅한 정체성·규칙·도구 사용 습관을
전부 이어받습니다. 문제는 여기서 시작됩니다 — 이어받은 정체성이 "능동적으로
움직여라, 필요하면 알아서 확인하고 알려라" 같은 성격이라면, 헤드리스 프로세스가
지시받은 범위를 넘어서 **스스로 판단해 다른 파일을 조사하거나, 심지어 사용자에게
직접 메시지를 보내는** 일까지 벌어질 수 있습니다.

실제로 이 저장소의 원본이 된 프로덕션 봇에서, 인증 상태를 확인하려고 짧은
진단용 프롬프트(`"정확히 이 문장만 출력해: OK"` 같은)로 `claude -p`를 테스트
삼아 돌렸는데, 그 프로세스가 프로젝트 폴더의 페르소나를 그대로 이어받아 지시받은
문장은 무시하고 스스로 로그 파일을 조사한 뒤 사용자에게 직접 메시지를 보내버린
사고가 하루에 세 번이나 반복됐습니다. 다행히 내용 자체는 매번 사실이었지만("된
것 같아서 보고했다"는 자율적 행동 자체가 문제), 헤드리스 프로세스가 지시 범위를
벗어나 무슨 일을 할지 예측할 수 없다는 게 핵심 위험입니다.

**해법 — cwd를 프로젝트 폴더 바깥으로:** Claude Code의 `CLAUDE.md` 탐색은
현재 작업 디렉토리(cwd)에서 위쪽으로 훑는 방식이라, 프로젝트 폴더 **안**에
하위 디렉토리를 새로 만들어도 결국 상위의 `CLAUDE.md`를 찾아버려 격리가 안
됩니다. 그래서 `CLAUDE.md`가 조상 디렉토리 어디에도 없는, 프로젝트 트리
**바깥**의 디렉토리에서 띄워야 합니다:

```python
ISOLATED_CWD = Path.home() / ".claude-isolated-cwd"
ISOLATED_CWD.mkdir(parents=True, exist_ok=True)

result = subprocess.run(
    ["claude", "-p", prompt, "--dangerously-skip-permissions"],
    capture_output=True, text=True, timeout=120,
    cwd=str(ISOLATED_CWD),   # ROOT가 아니라 격리된 디렉토리
)
```

cwd를 바꾸면 상대경로가 깨지므로, 프롬프트에 넘기는 파일 경로(예: 위 코드의
`watch_state`)는 항상 **절대경로**로 넘겨야 합니다 — `check_watch_url()`은
이미 `WATCH_STATE`를 절대경로(`ROOT / "memory" / "watch-state.json"`)로
정의해두고 있어서 그대로 잘 작동합니다.

**공식 옵션도 있습니다 — `--bare` 플래그:** Claude Code는 `--bare`라는 전용
플래그로 훅·플러그인·CLAUDE.md 자동로드를 한 번에 끌 수 있습니다. 다만 이
글을 쓰는 시점 기준으로, 설치된 CLI의 `--help` 원문은 "`--bare` 사용 시
OAuth/키체인을 전혀 안 읽는다"(즉 별도 API 키가 필요하다)고 명시하는 반면,
공식 문서 사이트 요약은 반대로 "OAuth 로그인 그대로 쓴다"고 설명하는 등
소스마다 말이 다른 경우가 있었습니다. **이런 애매함을 만나면 문서만 믿지
말고 `claude --help`(설치된 실제 버전 기준)나 직접 테스트로 확인하세요** —
버전에 따라 동작이 바뀌었을 수도 있고, 문서가 최신이 아닐 수도 있습니다. 이
저장소는 API 키 추가 설정 없이 지금 쓰는 로그인 그대로 격리할 수 있는 cwd
분리 방식을 기본으로 채택했습니다.

**한 걸음 더 — 감지와 처리를 분리하기:** 격리된 `claude -p`가 "새 글이
있다/없다"만 판단하고, 실제 처리(파일 다운로드·메시지 전송·기록 저장처럼
여러 단계를 거치는 작업)는 메인 세션에 `tmux_inject`로 넘기는 방법도 있습니다.
격리된 프로세스는 페르소나가 없어 스트레이 위험은 없지만, 그만큼 "이 단계는
절대 건너뛰지 마세요" 같은 세심한 지시를 매번 완벽히 따르리라는 보장도 약합니다
— 반면 메인 세션은 이미 켜져 있는 정체성으로 더 안정적으로 여러 단계를
처리합니다. 즉 **감지는 격리된 곳에서 가볍게, 실제 처리는 신뢰도가 필요한
메인 세션에서** 하는 조합이 안전과 안정성을 동시에 챙기는 방법입니다.

### 한 걸음 더 더 — 미디어 다운로드도 판단이 필요 없다면 파이썬 쪽으로

위 "감지와 처리를 분리하기"에서 실제 처리 전부(다운로드·전송·기록)를 메인
세션에 넘기는 방법을 소개했지만, 그중에서도 **다운로드**는 사실 "판단"이
전혀 필요 없는 기계적인 단계입니다 — 영상인지 이미지인지 확인하고,
`download_video.py`/`download_media.py`로 받고, 로컬에 저장하는 것뿐입니다.
이런 단계까지 메인 세션에 맡기면, 메인 세션이 매번 "영상인지 확인 →
download_video.py 실행 → 실패하면 download_media.py 실행"을 도구 호출 여러
번으로 반복해야 하고, 그사이 한 단계라도 빠뜨리면(실제로 실전 봇에서 영상
다운로드 단계를 건너뛰어 놓친 사고가 있었습니다) 미디어 없이 텍스트만 나가는
사고로 이어집니다.

그래서 이 강의의 `check_watch_url()`은 한 단계 더 나아가, **claude -p가 새
글을 보고하는 즉시 파이썬(`_download_watch_media()`)이 다운로드까지 자동으로
끝내고, 로컬 파일 경로를 포함해서만 메인 tmux에 주입**합니다. 메인 세션이
받는 메시지는 이제 `Cron : WATCH_NEW: <텍스트>|MEDIA:<로컬경로 또는
NONE>|LINK:<permalink>` 형태이고, `keyword_trigger.py`의 `웹페이지_새글_알림`
트리거는 그 경로를 그대로 첨부해서 전달하기만 하면 됩니다 — 다운로드 여부를
다시 판단하거나 스크립트를 재실행할 필요가 없습니다.

**정리하면 역할이 이렇게 나뉩니다** — 판단이 필요 없는 기계적 단계(해시 비교,
영상/이미지 다운로드, 상태파일 갱신)는 전부 파이썬이, 판단이 필요한 단계
(원문에 인사이트 한 줄 붙이기, 인박스 후보인지 분류하기)만 메인 세션이 맡습니다.
"이 단계가 항상 똑같은 절차를 그대로 반복하는가?"가 파이썬으로 뺄 수 있는지의
기준입니다 — 매번 다른 판단이 끼어드는 단계만 에이전트에게 남기세요.

### 큐(순서 보장)는 필요한가?

이 강의의 `scheduler_daemon.py`는 **단일 프로세스, 단일 스레드**로 돌아갑니다
— `tick()` 안에서 스케줄 항목을 순서대로 검사하고, `inject_tmux()`도 한 번에
하나씩만 호출합니다. 그래서 별도의 큐 없이도 tmux에는 항상 메시지가 순차적으로
들어갑니다(동시에 두 메시지가 섞여 들어갈 일이 없습니다).

큐가 진짜 필요해지는 시점은 **서로 다른 프로세스 여러 개가 같은 tmux 세션에
각자 주입하기 시작할 때**입니다 — 예를 들어 이 스케줄러 데몬 말고 웹훅
서버 같은 별도 프로세스를 하나 더 띄워서 그것도 같은 세션에 직접
`tmux send-keys`를 쏘게 만들면, 두 프로세스가 동시에 쏜 메시지의 문자가
섞여 들어가는 레이스가 생길 수 있습니다(실전 봇에서 실제로 겪은 사고입니다).
해법은 모든 프로세스가 tmux에 직접 쓰지 않고, 공유 큐 파일(또는 락) 하나에만
쌓고, 그 큐를 소비해서 실제로 tmux에 쓰는 건 단일 프로세스(또는 단일
스레드)로 통일하는 것입니다 — "쓰기 권한을 가진 자를 하나로 좁힌다"는
원칙입니다. 이 강의는 프로세스가 하나뿐이라 아직 그 문제를 겪지 않지만,
크론을 여러 개의 독립 프로세스로 쪼개기 시작한다면 이 패턴을 챙기세요.

## 자동시작 등록 후에도 claude -p가 자꾸 인증 실패한다면 (백그라운드 서비스 vs 대화형 세션)

이 강의를 그대로 따라와서 위 "(선택) 자동시작 등록"까지 마쳤는데, `claude -p`가
간헐적으로 `"OAuth session expired and could not be refreshed"`로 실패한다면 —
그것도 터미널에서 똑같은 명령을 직접 치면 매번 성공하는데 LaunchAgent/systemd로
띄운 뒤에는 자꾸 실패한다면, cwd 격리나 프롬프트 문제가 아니라 **다른 종류의
문제**일 가능성이 높습니다. 이 강의의 원본이 된 프로덕션 봇이 실제로 겪은
사고이고, 원인과 해법을 여기 정리합니다.

**증상:** 같은 `claude -p ... --dangerously-skip-permissions` 명령이 터미널
(대화형 세션)에서 실행하면 항상 성공하는데, macOS LaunchAgent로 띄우면 거의
매번 실패합니다. 환경변수(`env`)를 완전히 똑같이 맞춰도, `stdin`을 똑같이
`/dev/null`로 맞춰도, cwd를 똑같이 맞춰도 재현되지 않습니다 — 오직 **launchd가
실제로 그 프로세스를 띄웠는지 여부**만 결과를 가릅니다. 확인하려면 임시
LaunchAgent를 하나 만들어서 똑같은 명령을 `RunAtLoad`로 한 번 실행해보고
결과를 비교해보세요(아래는 macOS 예시).

```bash
cat > /tmp/oauth-test.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>oauth-test</string>
  <key>ProgramArguments</key>
  <array>
    <string>claude</string><string>--dangerously-skip-permissions</string>
    <string>-p</string><string>정확히 이 문장만 출력해: OK</string>
  </array>
  <key>StandardOutPath</key><string>/tmp/oauth-test.out</string>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
cp /tmp/oauth-test.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/oauth-test.plist
sleep 5 && cat /tmp/oauth-test.out
launchctl unload ~/Library/LaunchAgents/oauth-test.plist
rm ~/Library/LaunchAgents/oauth-test.plist
```

**원인:** `claude` CLI 실행 파일을 직접 까보면(`strings $(which claude) | grep -i
keychain`) `"getApiKeyFromConfigOrMacOSKeychain"`, `"No OAuth token in
keychain"`, `"Keychain access denied"` 같은 문자열이 나옵니다 — OAuth 토큰을
macOS 로그인 키체인(Keychain)에서 읽어오는 경로가 있다는 뜻입니다. 터미널에서
실행한 프로세스는 이미 로그인해서 열려있는 사용자 키체인에 접근할 수 있지만,
LaunchAgent(또는 Linux의 systemd 서비스)로 띄운 백그라운드 프로세스는 이
키체인 접근이 막힙니다 — GUI 로그인 세션에 딸린 자격증명 저장소는 원래
그 세션에 속한 프로세스만 열어볼 수 있게 설계돼 있고, 백그라운드 서비스는
그 세션 밖에 있기 때문입니다. `claude` 입장에서는 키체인을 못 열어본 것과
토큰이 진짜 만료된 것을 구분하지 않고 똑같이 "만료됨" 에러로 보고합니다.

**해법 — 토큰을 환경변수로 직접 넘겨서 키체인 조회를 건너뛰기:** `claude` CLI는
`CLAUDE_CODE_OAUTH_TOKEN` 환경변수가 설정돼 있으면 그 값을 그대로 쓰고 키체인을
조회하지 않습니다. `~/.claude/.credentials.json`에 이미 로그인 시 저장된
`accessToken`이 있으므로, 그 값을 읽어서 `claude -p`를 실행하는 `subprocess.run()`
호출에 넘기면 됩니다.

```python
CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude/.credentials.json"

def _claude_oauth_env():
    import json
    try:
        creds = json.loads(CLAUDE_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        token = creds.get("claudeAiOauth", {}).get("accessToken")
        if token:
            return {"CLAUDE_CODE_OAUTH_TOKEN": token}
    except Exception:
        pass
    return {}

env = os.environ.copy()
env.update(_claude_oauth_env())
result = subprocess.run(["claude", "-p", prompt, "--dangerously-skip-permissions"],
                         env=env, ...)
```

매 호출마다 파일에서 새로 읽으므로, 클로드 코드가 내부적으로 토큰을 주기적으로
갱신해도(보통 몇 시간 주기) 항상 최신 값을 씁니다. 파일 경로를 못 찾거나
`accessToken`이 없으면 조용히 빈 dict를 반환해서, 기존 방식(키체인 조회)으로
자연스럽게 fallback됩니다 — 이 헬퍼가 실패해도 전체 스케줄러가 죽지 않습니다.

⚠️ **Windows(WSL)에서도 이 정확한 증상이 재현되는지는 확인하지 못했습니다** —
WSL은 macOS 키체인이 아니라 다른 자격증명 저장 방식을 쓸 수 있어서 양상이
다를 수 있습니다. 다만 "OS 자격증명 저장소는 대화형(로그인) 세션에만 열려있고,
백그라운드 서비스에는 안 열려있을 수 있다"는 문제의 성격 자체는 플랫폼과
무관하게 흔한 클래스라, 위 fallback을 그대로 넣어두는 걸 예방적으로 권장합니다
— 토큰을 직접 넘기는 방식은 macOS/Linux/Windows 어디서든 안전하게 동작합니다.

## 마무리

여기까지 하면 에이전트가 사람이 말 걸기를 기다리지 않고도 정해진 시각에 스스로
움직이고, 관심 있는 소식을 알아서 확인해서 먼저 알려줍니다. 1강의 "정체성 + 대화"에
2강의 "시간 + 자동 판단"이 더해진 셈입니다.

---
> ⚠️ `USER.md`, `.env`는 개인정보/토큰이 들어가는 파일입니다. 절대 공개 저장소에
> 커밋하지 마세요 (`.gitignore`에 이미 등록돼 있습니다). `memory/watch-state.json`,
> `memory/news-poll-state.json`도 같은 이유로 `memory/`째로 무시되고 있습니다.
