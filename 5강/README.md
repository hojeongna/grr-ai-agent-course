# 그르르AI — 나만의 AI 에이전트 만들기 · 5강

이 폴더는 그르르AI 채널 실습편 5강용 자료입니다. **이번이 실습편의 마지막 강의입니다** —
6강부터는 실습을 벗어나 철학·인사이트 중심 콘텐츠로 전환됩니다.

⚠️ **아직 촬영 전입니다.** 3·4강과 마찬가지로, 실제 코드는 촬영 중에 만들어가는 것이
이 시리즈의 콘텐츠입니다. 다만 2단계(커스텀 대시보드)에서 참고할 두 가지 범용 패턴은
아래에 원리와 코드 구조까지 미리 정리해뒀습니다 — 이 부분은 헤매는 걸 보여주는 게
목적이 아니라 명확한 참고 자료가 필요한 구간이기 때문입니다.

## 이번 강의에서 다루는 것 — 옵시디언 지식관리

지금까지 1~4강에서 에이전트에게 정체성·스케줄러·자동화·원격접속·미니앱을 붙여왔다면,
5강은 그 에이전트가 **쌓아온 정보를 어떻게 저장·보여주는지**를 다룹니다. 옵시디언
하나만 다루고(다른 노트앱 비교 없음), **옵시디언 설명 + 커스텀 대시보드 제작** 2단계로
구성됩니다.

### 1단계 — 저장

옵시디언 자체 세팅(설치·기본 사용법)은 다루지 않습니다 — 이미 그 주제 강의가 시중에
충분히 많습니다. 시청자가 옵시디언은 이미 쓰고 있다고 가정하고, **"왜 파일 기반 저장이
에이전트한테 편한가"**만 짧게 설명합니다. (1강부터 이 시리즈가 정체성·기억·투두를 전부
평문 md 파일로 유지해온 것과 같은 맥락 — 4강 `todos.md` 설계 참고.)

### 2단계 — 커스텀 대시보드

이번 강의의 핵심 산출물입니다. **완성된 플러그인을 설치해서 쓰는 게 아니라, 에이전트가
시청자 본인의 옵시디언 폴더 구조를 스캔해서 그 자리에서 맞춤 대시보드를 만들어주는 흐름**을
보여줍니다 — 사람마다 볼트 구조가 다 다르기 때문에 "설치형"이 아니라 "그 자리에서 생성형"
접근을 택했습니다. Claude Code의 Artifact 기능으로 결과물(HTML 데일리 페이지)을 완성합니다.

**대시보드는 실시간 양방향 동기화가 아니라, 에이전트가 폴더를 스캔한 시점의 실제 데이터를
그대로 반영한 스냅샷입니다.** 시청자의 진짜 폴더명·파일명·최근 프로젝트가 목업 텍스트
대신 그대로 화면에 박혀서 나오고, 다시 만들어달라고 하면 그 시점 최신 데이터로 다시
생성됩니다 — Claude Artifact를 같은 경로로 재발행(republish)하면 같은 링크가 최신
내용으로 갱신되는 방식 그대로입니다.

**참고할 두 가지 범용 패턴**은 저자가 실제로 매일 쓰는 옵시디언 플러그인
(`Cube Command Center`)에서 가져옵니다. 시청자가 그 플러그인을 설치하는 게 아니라, 그
안의 두 구현 패턴만 뽑아서 시청자 본인 볼트 구조에 맞게 다시 만드는 예시로 씁니다.

#### 패턴 1 — 체크박스 리스트 → 라이브 칸반 렌더링

**원리**: 마크다운의 `- [ ]` / `- [x]` 체크박스 리스트는 사람도 옵시디언에서 그대로 읽고
고칠 수 있는 평문이면서, 동시에 파싱하기도 아주 쉬운 구조입니다. 이 둘을 겸하게 만들면
"진실의 원천은 항상 md 파일"이라는 이 시리즈의 원칙을 대시보드에도 그대로 적용할 수
있습니다. 세 함수로 나뉩니다:

1. **파싱** — `## 섹션명` 헤더로 컬럼을 나누고, 그 아래 체크박스 줄들을 컬럼별 배열로 모음.
2. **렌더링** — 그 배열로 드래그앤드롭 가능한 칸반 컬럼 DOM을 그림.
3. **쓰기백** — 카드를 드래그해서 컬럼을 옮기면, 화면 상태가 아니라 **원본 md 파일의 그
   줄 자체**를 다른 섹션 헤더 밑으로 옮겨 씀 (다른 줄은 건드리지 않음).

```javascript
// 1. 파싱 — 섹션 헤더 ↔ id 매핑은 볼트 구조에 맞게 자유롭게 정의
const SECTION_NAMES = { todo: 'To Do', doing: 'Doing', done: 'Done' };
const HEADER_TO_ID = Object.fromEntries(
  Object.entries(SECTION_NAMES).map(([id, name]) => [name, id])
);

function parseKanban(content) {
  const sections = { todo: [], doing: [], done: [] };
  let cur = null;
  for (const line of content.split('\n')) {
    if (line.startsWith('## ')) { cur = HEADER_TO_ID[line.slice(3).trim()] || null; continue; }
    if (!cur) continue;
    if (line.startsWith('- [ ]') || line.startsWith('- [x]')) {
      sections[cur].push({ text: line.slice(6).trim(), done: line.startsWith('- [x]') });
    }
  }
  return sections;
}

// 2. 렌더링 — 컬럼마다 카드 DOM 생성, 드래그 이벤트 연결
function renderKanban(sections, containerEl, onDrop) {
  containerEl.empty();
  for (const [id, items] of Object.entries(sections)) {
    const col = containerEl.createDiv({ cls: 'kanban-col' });
    col.createEl('h3', { text: SECTION_NAMES[id] });
    items.forEach(item => {
      const card = col.createDiv({ cls: 'kanban-card', text: item.text });
      card.draggable = true;
      card.ondragstart = e => e.dataTransfer.setData('text', item.text);
    });
    col.ondragover = e => e.preventDefault();
    col.ondrop = e => onDrop(e.dataTransfer.getData('text'), id); // ← 3번 쓰기백 호출
  }
}

// 3. 쓰기백 — 화면 조작을 원본 md 파일의 실제 텍스트 변경으로 반영
async function moveTaskInKanban(filePath, taskText, toSectionId, app) {
  const file = app.vault.getAbstractFileByPath(filePath);
  let content = await app.vault.read(file);
  const line = `- [ ] ${taskText}`;
  content = content.replace(line + '\n', ''); // 기존 위치에서 제거
  const header = `## ${SECTION_NAMES[toSectionId]}`;
  content = content.replace(header, `${header}\n${line}`); // 새 섹션 맨 위에 삽입
  await app.vault.modify(file, content);
}
```

이 세 함수만 있으면 어떤 볼트든 "체크박스 리스트가 있는 md 파일 하나"를 라이브 칸반으로
바꿀 수 있습니다. 시청자 볼트에 맞춰 `SECTION_NAMES`만 바꾸면 되는 구조라 시연에
적합합니다.

#### 패턴 2 — 블록형 커스텀 패널

**원리**: 버튼 하나하나를 화면에 하드코딩하지 않고, "타입이 있는 객체 배열"로 데이터화한
뒤 그 배열을 렌더링합니다. 배열 순서를 바꾸거나 항목을 추가/삭제하면 화면도 그대로
바뀝니다 — 시청자가 "내 볼트에는 이런 바로가기가 필요해"라고 말하면 에이전트가 이 배열을
그 사람 폴더 구조에 맞게 채워주는 방식으로 이어집니다.

```javascript
// 블록 하나 = {id, label, type, target} — type에 따라 클릭 동작이 갈림
const QUICK_LINKS = [
  { id: 'daily',    label: '오늘 노트',   type: 'file',   target: 'Daily/2026-09-10.md' },
  { id: 'projects', label: 'Projects',   type: 'folder', target: 'Projects' },
  { id: 'wiki',     label: '외부 위키',   type: 'url',    target: 'https://example.com' },
];

// 타입별 분기 — 새 타입이 필요하면 여기 한 줄만 추가
function runQuickLink(item, app) {
  if (item.type === 'url')    window.open(item.target);
  if (item.type === 'file')   app.workspace.openLinkText(item.target, '', false);
  if (item.type === 'folder') app.workspace.openLinkText(item.target, '', false);
}

// 렌더링 — 배열이 곧 화면. 배열 순서를 바꾸면 버튼 순서도 그대로 바뀜
function renderQuickGrid(links, containerEl, app) {
  containerEl.empty();
  containerEl.style.gridTemplateColumns = `repeat(${Math.min(links.length, 5)}, 1fr)`;
  links.forEach(item => {
    const btn = containerEl.createEl('button', { text: item.label });
    btn.onclick = () => runQuickLink(item, app);
  });
}
```

편집 UI(항목 추가/삭제/순서 변경)를 붙이면 시청자가 직접 나중에도 조정할 수 있는
패널이 되지만, 5강 시연에서는 **에이전트가 폴더 구조를 보고 이 배열 자체를 채워주는
과정**을 보여주는 게 핵심이라 편집 UI까지는 필요 없습니다.

## 사전 준비물

1~4강에서 만든 에이전트를 그대로 이어서 씁니다 — 새 프로젝트가 아닙니다.

- 1~4강에서 만든 `my-agent` 프로젝트 (정체성 + 텔레그램 + 스케줄러 + 원격접속/미니앱)
- 옵시디언(이미 설치·사용 중이라고 가정)
- 최소 스타터 볼트 구조 4개 폴더 (빈 볼트인 시청자 대상, PARA 풀버전 대신 자동화에 맞춘 축소판):

```
Vault/
├── Daily/       — 하루 단위 로그. 에이전트가 매일 YYYY-MM-DD.md 자동 생성
├── Projects/    — 진행 중인 프로젝트별 폴더 (프로젝트 하나당 폴더 하나)
├── Reference/   — 회의록 등 참고자료를 모아두는 곳
└── Inbox/       — 아직 분류 안 된 것 임시로 던져두는 곳 (나중에 위 3개로 정리)
```

이 구조는 이 시리즈의 저자·에이전트가 실제로 쓰는 볼트 구조(`Ops/Logs/Daily`,
`Ops/Meetings`, 프로젝트 폴더들)를 단순화한 버전입니다 — 2단계 데모(폴더 구조 스캔 →
대시보드 프롬프트 추출)의 입력값으로도 이 구조가 그대로 예시가 됩니다.

## 촬영 포맷

3강과 동일하게 **README 기반 라이브 시연**으로 진행합니다. 4강처럼 계정·방화벽 설정 같은
사전 검증이 필요한 취약한 구간이 없어서, 별도 리허설 없이 이 README를 그대로 따라가며
촬영합니다.

## 실습 vs 시연

- **직접 따라할 수 있는 부분**: 스타터 볼트 구조 만들기, 1단계(파일 기반 저장 원칙) 적용,
  위 두 패턴(체크박스→칸반, 블록형 패널) 코드를 자기 볼트 구조에 맞게 그대로 붙여넣기.
- **함께 만들어가는 부분**: 2단계 폴더 스캔 → 대시보드 프롬프트 추출 → Artifact 완성까지
  — 촬영 중 라이브로 진행합니다.

---

촬영 완료 후 이 README는 1~4강과 동일한 형식으로 교체되고, 실제 스크립트도 함께 올라옵니다.

> ⚠️ 개인정보(회사 시스템 이름·지점명·실제 파일 경로 등)는 공개 저장소 특성상 촬영 전
> 마스킹/익명화를 거칩니다.
