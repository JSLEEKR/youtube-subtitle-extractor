# youtube-subtitle-extractor

> YouTube 영상·채널을 **한국어 지식 번들**로 변환하는 파이프라인.
> 원본 영상부터 영어 전사, 자연스러운 한국어 번역, 리서치 기반 블로그 문서, 3라운드 찬반 토론까지 한 번에 만들어 냅니다.

**Claude Code 스킬 + 4개의 작은 파이썬 스크립트**로 구성돼 있습니다. 결정론적 작업(영상/자막 다운로드, Whisper 전사)은 스크립트가 처리하고, 언어 작업(번역, 리서치, 토론)은 Claude Code 스킬이 세션 안에서 직접 수행합니다.

---

## ✨ 무엇을 만들어 주나

단일 영상 하나당 다음 6개 파일이 `output/<채널_핸들>/<업로드날짜>_<비디오ID>/`에 생성됩니다.

| 파일 | 내용 |
|---|---|
| `video.mp4` | 원본 YouTube 영상 (yt-dlp로 최고 품질 다운로드) |
| `transcript_en.txt` | 공식 영어 자막 또는 Whisper 전사 |
| `transcript_ko.md` | 자연스러운 한국어 번역 (직역이 아닌 의역, 고유명사 병기) |
| `document.md` | 블로그 아티클 스타일 리서치 문서 (WebSearch로 출처 검증) |
| `debate.md` | 3라운드 찬반 토론 + 종합 (각 라운드가 이전 라운드를 명시 반박) |
| `meta.json` | 메타데이터 (제목, 업로드일, 길이, 자막 출처 등) |

채널 모드에서는 위 번들을 기간 내 모든 영상에 대해 생성하고, 루트 `README.md`를 대시보드로 자동 업데이트합니다.

---

## 🏗️ 아키텍처

```
┌──────────────────────────────────────────┐
│  Claude Code Skills (.claude/skills/)    │
│  ┌────────────────┐  ┌────────────────┐  │
│  │ extract-video  │  │extract-channel │  │
│  └───────┬────────┘  └───────┬────────┘  │
└──────────┼───────────────────┼───────────┘
           │                   │
           ▼                   ▼
┌──────────────────────────────────────────┐
│  Python scripts (scripts/)               │
│  ┌──────────────┐  ┌──────────────────┐  │
│  │ list_videos  │  │ fetch_video      │  │
│  │ fetch_subs   │  │ transcribe       │  │
│  └──────────────┘  └──────────────────┘  │
└──────────────────────────────────────────┘
```

- **스크립트 레이어**: 결정론적·멱등(idempotent). 각 스크립트가 JSON 한 줄을 stdout으로 출력하고 비영(非零) 종료 코드로 실패를 보고합니다. 동일한 파일이 이미 있으면 건너뜁니다.
- **스킬 레이어**: 번역·리서치·토론 같은 언어 작업을 Claude Code 세션 안에서 직접 수행합니다. `WebSearch`로 출처를 검증하고 인용합니다. 스킬 자체가 구현이 아니라 오케스트레이션이라 로직 변경이 쉽습니다.

---

## 🚀 빠른 시작

### 준비

```bash
# 의존성 설치
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements-dev.txt
```

시스템 요구사항:

- **Python 3.10+**
- **ffmpeg** — PATH에 있어야 합니다 (yt-dlp의 오디오/비디오 추출에 필요)
- **yt-dlp** — `pip install`로 설치됨
- **faster-whisper** — GPU(CUDA)가 있으면 자동으로 large-v3, 없으면 CPU int8로 폴백

### 사용 (Claude Code 세션에서)

단일 영상 처리:
```
/extract-video https://www.youtube.com/watch?v=<id>
```

채널 모드 (최근 30일 모든 영상):
```
/extract-channel https://www.youtube.com/@<handle> --days 30
```

옵션:
- `--days N` — 최근 N일 이내 영상만 (기본 30)
- `--limit N` — 최대 N개로 제한 (테스트용)
- `--skip-debate` — 토론 생성 건너뛰기

결과는 `output/<channel_handle>/`에 쌓입니다.

---

## 🔁 파이프라인 단계 (per video)

`.claude/skills/extract-video/SKILL.md`가 오케스트레이션하는 9단계:

1. **메타데이터 해석** — `yt-dlp`로 video_id, title, upload_date, channel_handle 파싱
2. **`meta.json` 작성** — 존재하면 스킵 (멱등성)
3. **영상 다운로드** — `fetch_video.py` → `video.mp4` (실패해도 파이프라인은 계속)
4. **영어 전사 확보** — `fetch_subs.py`로 공식 자막 시도, 없으면(`exit 2`) `transcribe.py`로 Whisper 폴백
5. **한국어 번역** — `transcript_ko.md`, 자연 의역, 고유명사/기술 용어 병기
6. **리서치 문서** — `document.md`, WebSearch로 출처 검증 및 인용
7. **찬반 토론** — `debate.md`, 3라운드 + 종합, 각 라운드가 이전을 명시 반박
8. **채널 README 갱신** — 대시보드 재생성
9. **최종 리포트** — 생성/스킵된 파일과 출력 경로 출력

실패 처리:
- Step 3 (영상 다운로드) 실패는 **비치명** — 에러만 로그하고 계속
- Step 4 (전사) 실패는 치명 — 중단하고 보고
- Step 5~7 실패는 `meta.json`에 기록하고 부분 결과 유지
- 전 단계 **멱등** — 재실행 시 빠진 곳만 이어서 작업

---

## 🧪 테스트

```bash
pytest -v
```

유닛 테스트는 `scripts/_common.py`의 순수 함수만 커버합니다 (날짜 윈도우 필터, VTT 파서, 디렉터리명 포매터). 스크립트 본체는 통합 스모크 테스트로 검증합니다.

---

## 📁 프로젝트 구조

```
youtube-subtitle-extractor/
├── scripts/
│   ├── _common.py         # 순수 헬퍼 (날짜 필터, VTT 파서, 디렉터리명)
│   ├── list_videos.py     # 채널 → 필터링된 영상 리스트 JSON
│   ├── fetch_video.py     # 원본 영상 다운로드 → video.mp4
│   ├── fetch_subs.py      # 공식 영어 자막 → transcript_en.txt
│   └── transcribe.py      # 오디오 다운로드 + Whisper → transcript_en.txt
├── tests/
│   ├── test_common.py     # 순수 헬퍼 유닛 테스트
│   └── fixtures/sample.vtt
├── .claude/skills/
│   ├── extract-video/SKILL.md
│   └── extract-channel/SKILL.md
├── docs/superpowers/      # 플랜/스펙 문서
├── requirements.txt       # 런타임: yt-dlp, faster-whisper
├── requirements-dev.txt   # 개발: pytest
└── README.md
```

`output/`은 gitignore 처리되어 있어 저장소에 올라가지 않습니다.

---

## 🧠 설계 원칙

1. **각 스크립트는 한 가지 일만 한다.** 성공하면 JSON 한 줄을 stdout에, 실패하면 stderr + 비영 종료 코드.
2. **부수 효과는 `main()` 안에만.** 분기 로직은 `_common.py`의 순수 함수로 분리해 테스트 가능하게.
3. **스킬은 오케스트레이션, 스크립트는 결정론.** 스크립트는 절대 Claude를 호출하지 않는다.
4. **모든 단계는 멱등.** 출력 파일이 존재하면 건너뛴다. 재실행은 이어서 작업.
5. **실패는 부분 진행을 망가뜨리지 않는다.** 영상 다운로드 실패가 전사를 막지 않고, 한 영상의 실패가 다음 영상을 막지 않는다.

---

## 📝 라이선스

MIT

---

## 🙏 크레딧

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube 다운로드
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 기반 Whisper 추론
- [Claude Code](https://claude.com/claude-code) — 오케스트레이션 런타임
