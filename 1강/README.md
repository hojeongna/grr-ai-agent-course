# 그르르AI — 나만의 AI 에이전트 만들기 · 1강

이 폴더는 그르르AI 채널 실습편 1강용 자료입니다.
Claude Code에 정체성(md 파일)을 부여하고, 텔레그램과 두 방향(알림 + 대화)으로 연결하고,
6가지 훅(hook)으로 "기억하고, 다시 불러오고, 행동을 알리고, 응답을 놓치지 않는" 에이전트를 만들어봅니다.

## 이번 강의에서 다루는 것

- **BOOTSTRAP.md 온보딩** — 텔레그램 봇 생성부터 `.env` 설정, Channels 연동, 훅 동작 검증, 정체성(SOUL/IDENTITY/USER) 설정까지 첫 대화 하나로 안내 (다 끝나면 자기 자신을 삭제)
- **md 파일 세팅** — SOUL/IDENTITY/USER/CONTEXT/MEMORY로 에이전트의 정체성 만들기
- **CLAUDE.md 규칙** — 어떤 상황에 어떤 파일을 업데이트할지 정해두어, 대화 중 에이전트가 알아서 파일을 채워나가게 하기
- **텔레그램 연결 (두 갈래)**
  - 봇 토큰으로 한 방향 알림 보내기 (`notify_telegram.py`)
  - Claude Code 공식 **Channels** 기능으로 실시간 양방향 대화하기
- **6가지 훅**
  - `SessionStart` — 세션이 시작될 때(또는 압축 후 재개될 때) 설정 파일 + 최근 텔레그램 대화를 읽고 "깨어났다"고 알림
  - `PreCompact` — 대화가 길어져 기억을 압축하기 직전에 알림
  - `PostCompact` — 압축이 끝난 직후 "정리 완료" 알림 (PreCompact와 짝을 이룸)
  - `PostToolUse` — 도구를 실행할 때마다 텔레그램 메시지 하나를 실시간으로 고쳐 쓰며 진행 상황을 보여주고, 응답이 끝나면 완료로 바꿈
  - `Stop` — 한 턴이 끝날 때, 진행 메시지를 완료 처리하고 텔레그램 메시지에 답장을 안 보냈으면 재촉
  - `UserPromptSubmit` — 메시지가 들어올 때마다 reply 필요 표시를 남기고, 대화를 로그에 기록하고, 이모지 리액션을 상기시킴

여섯 개 훅이 합쳐지면 "기억하고 → 다시 불러오고 → 행동을 실시간으로 알려주고 → 응답을 놓치지 않는" 에이전트가 완성됩니다.

> 💡 **왜 `PostCompact`는 알림 한 줄뿐인가:** Claude Code 훅 중 stdout이 실제로 클로드의 컨텍스트에 주입되는 건 `SessionStart`와 `UserPromptSubmit`뿐입니다. `PostCompact`의 stdout은 주입되지 않으므로, 여기서 정체성 파일을 다시 읽거나 최근 대화를 불러오는 건 의미가 없습니다 — 그 역할은 이미 `SessionStart`(matcher에 `compact` 포함)가 맡고 있습니다. 그래서 `PostCompact`는 딱 하나, 압축이 끝났다는 텔레그램 알림만 보냅니다.

## 사전 준비

### 1. Claude Code 설치
[claude.com/code](https://claude.com/code) 안내에 따라 설치합니다.

### 2. (Windows 사용자) WSL 필요 없음
1강에서 다루는 훅은 전부 순수 파이썬 스크립트라 셸 문법에 의존하지 않고, 텔레그램 Channels 기능도 Claude Code CLI 명령이라 Windows/macOS에서 동일하게 동작합니다. **WSL(Windows Subsystem for Linux)은 1강에서는 필요 없습니다.**

> WSL은 2강(tmux 기반 24시간 스케줄러)부터 필요해집니다 — tmux가 유닉스 계열 도구라 윈도우 네이티브 지원이 약하기 때문입니다. 지금은 신경 쓰지 않아도 됩니다.

macOS는 터미널에서 바로 진행하면 됩니다.

### 3~5단계는 이제 대화로 진행됩니다

예전엔 여기서 BotFather 봇 만들기, `.env` 채우기, Channels 연동, 페어링을 전부 직접 손으로 해야 했습니다. 지금은 `BOOTSTRAP.md`가 이 과정을 첫 대화로 안내합니다 — 아래 [설치 단계](#설치-단계)대로 `claude`만 실행하면 에이전트가 한 단계씩 물어보며 진행합니다. 토큰을 받으면 에이전트가 직접 `.env`에 써넣고, 마지막엔 정체성(SOUL/IDENTITY/USER)도 대화로 채운 뒤 `BOOTSTRAP.md` 스스로 삭제합니다.

아래는 그 안에서 실제로 실행되는 명령어들입니다(문제가 생겼을 때 참고용):

```
# Claude Code 세션 안에서 (BOOTSTRAP.md STEP 2)
/plugin marketplace add anthropics/claude-plugins-official
/plugin install telegram@claude-plugins-official
/reload-plugins
/telegram:configure <BotFather가 준 토큰>
```
```bash
# 재시작 (사람이 터미널에서 직접)
claude --channels plugin:telegram@claude-plugins-official
```
```
# 페어링 (BOOTSTRAP.md STEP 3)
/telegram:access pair <코드>
/telegram:access policy allowlist
```

**왜 알림(봇 토큰)과 대화(Channels) 두 메커니즘이 같이 필요한가?**
훅 스크립트는 Claude Code의 도구 호출 루프 밖에서 OS 서브프로세스로 실행되기 때문에, MCP 도구(`mcp__plugin_telegram_telegram__reply` 등)를 직접 부를 수 없습니다. 그래서 세션 시작·작업 진행·reply 누락 재촉처럼 훅이 주도하는 알림은 전부 봇 토큰으로 텔레그램 API를 직접 호출하고(`notify_telegram.py` 방식), 실제 대화(Claude가 텍스트로 답장하는 것)만 Channels의 MCP reply 도구를 씁니다.

## 설치 단계

```bash
# 1. 이 폴더를 내 프로젝트로 복사
cp -r 1강 my-agent
cd my-agent

# 2. 템플릿 파일(md + BOOTSTRAP.md)을 프로젝트 루트로 복사
cp templates/*.md .

# 3. Claude Code 실행 — 여기서부터는 BOOTSTRAP.md가 대화로 안내합니다
claude
```

`BOOTSTRAP.md`가 있으면 `CLAUDE.md`의 "처음 실행할 때" 규칙에 따라 자동으로 그 순서를 따라갑니다: 텔레그램 봇 만들기 → `.env` 채우기(에이전트가 직접) → Channels 연동 → 페어링 → **훅이 실제로 작동하는지 검증** → 이름/성격/유저 정보를 대화로 채우기 → 다 끝나면 `BOOTSTRAP.md` 자체 삭제.

그 이후로 텔레그램으로 에이전트와 대화하면:
- 세션이 시작될 때 🟢 알림이 오고 (최근 텔레그램 대화도 함께 불러옵니다)
- 도구를 쓸 때마다 🔄 진행 메시지 하나가 그 자리에서 계속 갱신되다가, 턴이 끝나면 ✅ 완료로 바뀌고
- 대화가 길어져 압축될 때 🧠 알림이 오고, 압축이 끝나면 🧠 완료 알림이 한 번 더 오고
- 텔레그램으로 메시지를 보내면 Claude가 실시간으로 답장합니다 — 혹시 깜빡하고 답장을 안 보내면 다음 턴에 알아서 재촉하는 리마인더가 뜹니다.

## 폴더 구조

```
1강/
├── README.md                     ← 지금 보고 있는 파일
├── .env.example                   ← 복사해서 .env로 사용
├── .gitignore
├── .claude/
│   └── settings.json               ← 6가지 훅 설정
├── templates/
│   ├── BOOTSTRAP.md                 ← 첫 대화 온보딩 스크립트 (사용 후 삭제됨)
│   ├── CLAUDE.md                    ← 파일 소유권 + 업데이트 규칙
│   ├── SOUL.md                     ← 성격
│   ├── IDENTITY.md                 ← 이름/정체성
│   ├── USER.md                     ← 유저 정보 (커밋 금지!)
│   ├── CONTEXT.md                  ← 환경 정보
│   └── MEMORY.md                   ← 장기기억 인덱스 (처음엔 비어있음)
└── scripts/
    ├── notify_telegram.py          ← 공용 텔레그램 알림 함수 (raw 봇 토큰)
    ├── hook_session_start.py       ← SessionStart
    ├── hook_pre_compact.py         ← PreCompact
    ├── hook_post_compact.py        ← PostCompact
    ├── hook_post_tool_use.py       ← PostToolUse + Stop(--done)
    ├── telegram_reply_guard.py     ← UserPromptSubmit(--mark) / PostToolUse(--clear) / Stop(--check)
    ├── telegram_log.py             ← UserPromptSubmit(--inbound) / PostToolUse(--outbound)
    └── hook_emoji_reminder.py      ← UserPromptSubmit
```

## 다음 강의 (2강 예고)

- 24시간 자동으로 돌아가는 스케줄러(tmux 기반, 이때부터 Windows는 WSL 필요)
- 키워드 감지 훅으로 특정 상황에 자동 반응하기

---
> ⚠️ `USER.md`, `.env`는 개인정보/토큰이 들어가는 파일입니다. 절대 공개 저장소에 커밋하지 마세요 (`.gitignore`에 이미 등록돼 있습니다).
