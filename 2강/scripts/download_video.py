#!/usr/bin/env python3
"""영상이 첨부된 글에서 실제 재생 가능한 영상 파일을 받아오는 유틸리티.

download_media.py로 커버할 수 없는 경우가 있습니다: 어떤 사이트(대표적으로
Threads/Instagram 계열)는 일반 브라우저로 페이지를 열면 자바스크립트가 그려주기
전의 빈 껍데기 HTML만 오고, 실제 영상 URL은 그 자바스크립트가 실행돼야 채워지는
데이터 안에 있습니다. 이럴 때 페이지에서 곧바로 <img>/<video> src를 읽어봐야
소용이 없습니다 — 애초에 그 값이 HTML에 없기 때문입니다.

그런데 이런 사이트들 상당수가 검색엔진 최적화(SEO)를 위해 **잘 알려진 검색엔진
크롤러(Googlebot 등)에게는 서버 쪽에서 미리 다 렌더링한 완전한 HTML**을 내려주는
경우가 있습니다. 요청 헤더의 User-Agent만 그 크롤러 이름으로 바꾸면, 사람이
브라우저로 보는 것과는 다른(하지만 더 완전한) 응답을 받을 수 있는 겁니다. 이
스크립트는 그 성질을 이용해서, 페이지 안에 파묻힌 JSON에서 실제 영상 URL을
추출합니다.

⚠️ 이건 "공식적으로 보장된 API"가 아니라 사이트가 검색엔진에게만 다르게
응답하는 부수적인 동작(흔히 cloaking이라고 부릅니다)에 기대는 방법입니다.
지금은 작동하더라도 사이트 쪽 로직이 바뀌면 언제든 안 될 수 있습니다 — 실습
때 "이게 왜 되지?"를 이해하는 게 "이 스크립트를 영구히 믿고 써도 된다"는
뜻은 아닙니다. 자주 실행하는 자동화라면(이 강의처럼 30분~1시간 주기 정도)
문제될 요청량은 아니지만, 짧은 간격으로 반복 호출하는 건 피하세요.

동작 원리(Threads 예시로 설명):
1. 게시글 permalink에 Googlebot User-Agent로 GET 요청 → 완전 렌더링된 HTML.
2. 이 HTML 한 장에는 대상 게시글뿐 아니라 답글·추천 게시글 등 여러 게시글의
   JSON이 한꺼번에 섞여 들어와 있습니다. 그래서 무작정 전체 HTML에서 영상
   URL 패턴을 찾으면 엉뚱한 게시글의 영상을 가져올 위험이 있습니다.
3. 대상 게시글의 고유 식별자("code":"<shortcode>" 형태)가 나오는 위치부터,
   그 다음 게시글의 식별자가 나오는 위치 직전까지로 잘라내서 "이 구간 안에서만"
   영상 URL을 찾습니다 — 이렇게 범위를 좁혀야 정확한 매칭이 보장됩니다.
4. 그 구간 안에서 "video_versions":[...] 배열을 찾아 첫 번째 항목의 url을
   꺼내면 그게 실제 mp4 파일 주소입니다.

사이트마다 JSON 필드 이름(위 예시의 "code", "video_versions")은 다릅니다 —
이 스크립트를 다른 사이트에 그대로 쓰려면, 먼저 Googlebot UA로 받은 HTML을
직접 눈으로 열어보고 그 사이트가 실제로 어떤 필드명을 쓰는지부터 확인하세요.
"모르는 사이트에 무작정 돌려보기"가 아니라 "한 번 확인하고 나서 패턴을
맞춰 쓰기"가 원칙입니다.

사용법:
  python3 scripts/download_video.py <게시글 permalink URL> <저장할_파일_경로>

종료 코드: 성공 0, 실패(영상을 못 찾았거나 다운로드 실패) 1.
"""
import re
import sys
import urllib.request
from pathlib import Path

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def extract_shortcode(permalink: str) -> str:
    m = re.search(r"/post/([A-Za-z0-9_-]+)", permalink)
    if not m:
        raise ValueError(f"permalink에서 게시글 식별자를 못 찾았습니다: {permalink}")
    return m.group(1)


def fetch_video_url(permalink: str):
    shortcode = extract_shortcode(permalink)
    req = urllib.request.Request(permalink, headers={"User-Agent": GOOGLEBOT_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    idx = html.find(f'"code":"{shortcode}"')
    if idx == -1:
        return None  # Googlebot UA로도 이 게시글 데이터를 못 찾음 — 필드명이 다른 사이트일 수 있음

    next_idx = html.find('"code":"', idx + 10)
    segment = html[idx:next_idx] if next_idx > 0 else html[idx:idx + 20000]

    vv_idx = segment.find("video_versions")
    if vv_idx == -1:
        return None  # 이 게시글엔 영상이 없음(이미지 전용 글) — download_media.py를 대신 쓰세요

    snippet = segment[vv_idx:vv_idx + 2000]
    m = re.search(r'"url":"(https:\\/\\/[^"]+?\.mp4[^"]*)"', snippet)
    return m.group(1).replace("\\/", "/") if m else None


def download(permalink: str, out_path: str) -> bool:
    try:
        video_url = fetch_video_url(permalink)
    except Exception as e:
        print(f"[download_video] 페이지 조회 실패: {e}", file=sys.stderr)
        return False

    if not video_url:
        print("[download_video] 영상 URL을 못 찾았습니다 (이미지 전용 글이거나 사이트 구조가 다를 수 있습니다)", file=sys.stderr)
        return False

    req = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print(f"[download_video] 실패: HTTP {resp.status}", file=sys.stderr)
                return False
            data = resp.read()
    except Exception as e:
        print(f"[download_video] 다운로드 실패: {e}", file=sys.stderr)
        return False

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"[download_video] 저장 완료: {out} ({len(data)} bytes)")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python3 download_video.py <게시글 permalink URL> <저장할_파일_경로>", file=sys.stderr)
        sys.exit(1)
    ok = download(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
