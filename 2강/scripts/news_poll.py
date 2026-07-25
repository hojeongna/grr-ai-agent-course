#!/usr/bin/env python3
"""RSS 피드 새 글 감지 — 외부 라이브러리 없이 표준 urllib + xml.etree로 구현한 예제.

이 강의에서 "최신 소식 불러오기"는 소스 종류에 따라 두 갈래로 나눠 가르칩니다.

  (a) RSS가 있는 사이트(블로그, 뉴스레터, 유튜브 채널 등) → 이 파일(news_poll.py)이
      담당합니다. 파이썬이 피드를 직접 파싱하고 dedup까지 끝낸 뒤, 새 글이 있을 때만
      스케줄러가 트리거를 주입합니다.
  (b) RSS가 없는 사이트(개인 블로그, 일부 SNS 프로필 페이지 등) → 별도 파이썬 스크립트
      없이, **에이전트(클로드) 자신이 WebFetch 도구로 그 페이지를 직접 훑도록** 지시문만
      주입합니다. "폴링"과 "새 글 판단"을 코드가 아니라 에이전트가 직접 하는 것 —
      이 강의 시리즈 전체의 철학(에이전트가 도구를 스스로 활용해 판단하고 행동한다)과
      맞닿아 있는 패턴입니다. 이 흐름은 scheduler_daemon.py의 WATCH_CHECK 항목 +
      keyword_trigger.py에 구현돼 있고, README의 "RSS 없는 사이트는 어떻게?" 절에서
      자세히 설명합니다. (파이썬 스크립트가 필요 없으므로 이 파일엔 관련 코드가 없습니다.)

여기서는 (a) RSS 기반 방식만 다룹니다. '최신 소식 불러오기'라고 하면 특정 SNS를 로그인
세션까지 만들어서 긁어오는 방식을 떠올리기 쉬운데, 그건 계정이 잠기거나 페이지 구조가
바뀌면 바로 깨지는 fragile한 방법이고 대부분의 SNS 이용약관도 그런 자동 수집을 금지합니다.
RSS가 있는 소스라면 훨씬 튼튼합니다 — 로그인도 필요 없고, 표준 라이브러리만으로 충분히
읽을 수 있고, 서비스 제공자가 공식적으로 열어둔 채널이라 이용약관 문제에서도 자유롭습니다.
  (유튜브 채널도 RSS가 있습니다: https://www.youtube.com/feeds/videos.xml?channel_id=채널ID)

동작:
  1. .env의 RSS_FEED_URL을 GET
  2. <item> 목록에서 title/link/guid를 뽑는다
  3. memory/news-poll-state.json에 저장해둔 "마지막으로 본 글 guid 목록"과 비교해서
     아직 못 본 글만 골라낸다 (dedup)
  4. 새 글이 있으면 상태 파일을 갱신하고, 새 글 목록을 반환/출력한다

⚠️ 첫 실행 특수 케이스: 상태 파일이 아직 없으면(정말 처음 실행) 지금 피드에 있는
글을 전부 "새 글"로 오인해서 우르르 알려버릴 수 있습니다. 그래서 첫 실행은 현재
피드 상태를 "기준점"으로만 저장하고 새 글로는 취급하지 않습니다 — 실제로 자주
겪는 실수라 여기서 미리 막아둡니다.

사용법:
  python3 scripts/news_poll.py            # 사람이 읽기 좋은 형태로 결과 출력 (테스트용)
  python3 scripts/news_poll.py --quiet    # "제목<TAB>링크" 한 줄씩만 출력, 새 글 없으면
                                            # 아무것도 안 찍음 (scheduler_daemon.py가 이 모드로
                                            # 호출해서 파싱)

.env 필요 값:
  RSS_FEED_URL=아무 RSS 피드 URL

새 글이 발견되면 scheduler_daemon.py가 tmux에 `Cron : NEWS_NEW: <제목> (<링크>)`를
주입하고, keyword_trigger.py가 그 프롬프트를 받아 "링크를 열어서 요약해 텔레그램으로
보내라"는 지시문을 클로드 컨텍스트에 붙여줍니다. 폴링(발견) → 트리거(주입) → 반응(요약),
세 스크립트가 역할을 나눠 맡는 구조입니다.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "memory" / "news-poll-state.json"
MAX_SEEN = 200  # 상태 파일에 보관할 최근 guid 개수 (무한정 늘어나지 않게 캡)


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


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"seen_ids": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"seen_ids": []}


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["seen_ids"] = state.get("seen_ids", [])[-MAX_SEEN:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


ATOM_NS = "{http://www.w3.org/2005/Atom}"


def fetch_feed(url: str) -> list:
    """RSS 2.0 <item> 과 Atom <entry> 둘 다 파싱해서 [{"title", "link", "id"}] 형태로 반환.
    유튜브 채널 피드(README 예시)가 Atom이라 둘 다 지원해야 실습이 막히지 않습니다."""
    # HTTP 헤더는 latin-1로 인코딩되므로 User-Agent엔 한글 등 비ASCII 문자를 넣으면 안 됨
    req = urllib.request.Request(url, headers={"User-Agent": "grr-ai-agent-course-lecture2/news_poll"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    items = []

    # RSS 2.0: <item><title>/<link>/<guid>
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        if not guid:
            continue
        items.append({"title": title, "link": link, "id": guid})

    # Atom: <entry><title>/<link href=.../>/<id> (유튜브 채널 피드가 이 형식)
    for entry in root.iter(f"{ATOM_NS}entry"):
        title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
        link_el = entry.find(f"{ATOM_NS}link")
        link = (link_el.get("href") if link_el is not None else "") or ""
        entry_id = (entry.findtext(f"{ATOM_NS}id") or link or title).strip()
        if not entry_id:
            continue
        items.append({"title": title, "link": link, "id": entry_id})

    return items


def check_new_entries() -> list:
    """새 글만 골라 반환하고, 상태 파일을 갱신한다."""
    load_env()
    feed_url = os.environ.get("RSS_FEED_URL")
    if not feed_url:
        print("[news_poll] .env에 RSS_FEED_URL이 없습니다", file=sys.stderr)
        return []

    try:
        items = fetch_feed(feed_url)
    except Exception as e:
        print(f"[news_poll] 피드 가져오기 실패: {e}", file=sys.stderr)
        return []

    first_run = not STATE_PATH.exists()
    state = load_state()

    if first_run:
        state["seen_ids"] = [it["id"] for it in items]
        save_state(state)
        print("[news_poll] 첫 실행 — 현재 피드를 기준점으로 저장했습니다 (알림 없음)", file=sys.stderr)
        return []

    seen = set(state.get("seen_ids", []))
    new_items = [it for it in items if it["id"] not in seen]

    if new_items:
        state["seen_ids"] = state.get("seen_ids", []) + [it["id"] for it in new_items]
        save_state(state)

    return new_items


def main():
    quiet = "--quiet" in sys.argv
    new_items = check_new_entries()

    if quiet:
        for it in new_items:
            print(f"{it['title']}\t{it['link']}")
        return

    if not new_items:
        print("새 글 없음")
        return
    print(f"새 글 {len(new_items)}개 발견:")
    for it in new_items:
        print(f"  - {it['title']}\n    {it['link']}")


if __name__ == "__main__":
    main()
