#!/usr/bin/env python3
"""공개 페이지에서 찾은 이미지 URL을 그대로 다운로드하는 아주 단순한 유틸리티.

WATCH_CHECK 흐름에서 에이전트가 WebFetch로 새 글을 확인하다가 이미지 URL을
발견하면, 그 URL을 이 스크립트로 그대로 받아옵니다. 로그인/쿠키/세션은 전혀 쓰지
않는 순수 익명 GET 한 번입니다 — 페이지에 이미 공개적으로 박혀있는 URL을 그대로
요청하는 것뿐이라, 브라우저가 그 페이지를 렌더링할 때 이미지를 불러오는 것과
신호상 동일합니다.

⚠️ 영상은 이 스크립트로 안 됩니다 — WebFetch가 애초에 <video> 태그를 읽어오지
못해서 넘길 URL 자체가 없기 때문입니다. 영상은 download_video.py(Googlebot UA
패턴)를 대신 쓰세요, 자세한 이유는 README의 "영상이 첨부된 글은 어떻게?" 참고.

⚠️ 쿼리스트링을 꼭 그대로 유지하세요. 소셜/CDN 이미지 URL은 만료 시간이 걸린
서명 토큰(`?oh=...&oe=...` 같은 파라미터)이 쿼리스트링에 포함된 경우가 많습니다.
URL을 자르거나 재구성하면(예: `?` 뒤를 지우고 붙여넣기) 서명이 깨져서 요청이
실패합니다 — 페이지에서 본 URL을 문자 그대로 복사해서 넘기세요.

이 스크립트는 "성공하면 저장, 실패하면(403 등) 그냥 건너뛰기"만 합니다. 재시도,
헤더 위조, 우회 시도는 하지 않습니다 — 접근이 막힌 리소스라면 그건 그런 뜻입니다.

사용법:
  python3 scripts/download_media.py <URL> <저장할_파일_경로>

종료 코드: 성공 0, 실패 1.
"""
import sys
import urllib.request
from pathlib import Path

UA = "grr-ai-agent-course-lecture2/download_media (+educational course example)"


def download(url: str, out_path: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                print(f"[download_media] 실패: HTTP {resp.status}", file=sys.stderr)
                return False
            data = resp.read()
    except Exception as e:
        print(f"[download_media] 실패(접근이 막혀있을 수 있습니다 — 우회하지 않고 건너뜁니다): {e}", file=sys.stderr)
        return False

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"[download_media] 저장 완료: {out} ({len(data)} bytes)")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python3 download_media.py <URL> <저장할_파일_경로>", file=sys.stderr)
        sys.exit(1)
    ok = download(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
