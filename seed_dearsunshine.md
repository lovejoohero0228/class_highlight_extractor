# DearSunshine — English Class Highlight Clip Extractor
## Seed Specification (seed_54be8b5d5853)

---

## 1. Goal

로컬 웹 애플리케이션을 만든다.

영어 수업 MP4 영상(5~10분, 핸드폰 촬영)을 업로드하면, **아이들이 영어로 말하고·대답하고·노래하는 구간**을 자동으로 탐지하여 30초~2분짜리 하이라이트 클립으로 잘라서 다운로드할 수 있게 제공한다. 잘라낸 클립은 선생님이 학부모에게 카카오톡으로 전달하는 용도로 사용된다.

---

## 2. 배경 및 문제 정의

- 선생님이 수업 중 촬영한 5~10분짜리 영상을 카카오톡으로 편집자(사용자)에게 전송
- 편집자는 영상을 다운받아 **수작업으로 컷편집** → 클립을 다시 선생님께 카카오톡 전송
- 하루 5~10개 영상을 매일 반복하는 이 과정을 **자동화**하는 것이 목표
- 학부모에게는 "오늘 수업에서 아이가 이렇게 참여했어요"를 보여주는 하이라이트 공유

---

## 3. 제약 조건 (Constraints)

| 항목 | 내용 |
|------|------|
| 실행 환경 | localhost 전용 (클라우드 배포 없음) |
| 하드웨어 | CPU-only (NVIDIA GPU 없음) |
| 외부 API 예산 | 월 ≤ 50,000 KRW (Whisper API + GPT-4o 사용 가능) |
| 사용자 | 1인 사용자, 인증/로그인 불필요 |
| 입력 포맷 | MP4 (핸드폰 촬영, 가로/세로 혼재) |
| 개발 환경 | Python + Conda, Windows 11 |
| 처리 시간 | 당일 완료면 충분 (실시간 처리 불필요) |
| 비목표 | 아이 개인 식별 없음, 학부모 전용 페이지 없음 |

---

## 4. 인수 기준 (Acceptance Criteria)

1. **업로드**: 웹 UI에서 MP4 영상을 하루 5~10개 일괄 업로드할 수 있다
2. **자동 탐지**: 음성 분석(아이 vs. 선생님 목소리) + 수업 구조(전환 멘트) 복합 기준으로 학생 참여 구간을 자동 탐지한다
3. **클립 추출**: 영상 1개당 0~3개의 활동 블록을 클립으로 추출한다 (각 30초~2분)
4. **활동 블록 정의**: 선생님 질문 → 아이 대답 → 리액션을 하나의 단위로 인식한다
5. **경계 허용 오차**: 클립 시작/끝 지점이 ±2~3초 오차 내면 허용한다
6. **클립 리뷰**: 탐지된 클립을 목록으로 보여주고, 미리보기(preview)를 제공한다
7. **오검출 삭제**: 목록에서 불필요한 클립을 삭제할 수 있다
8. **다운로드**: 선택한 클립을 MP4 파일로 다운로드할 수 있다
9. **방향 처리**: 가로 영상과 세로 영상 모두 오류 없이 처리한다
10. **처리 속도**: 5~10개 영상이 당일 안에 처리 완료된다

---

## 5. 핵심 데이터 모델 (Ontology Schema)

```
EnglishClassClipExtractor
├── Video
│   ├── video_id: string          # 업로드된 영상의 고유 ID
│   ├── source_file: string       # 원본 MP4 파일명/경로
│   ├── duration_seconds: number  # 영상 총 길이 (초)
│   └── orientation: string       # landscape | portrait
│
├── TranscriptSegment
│   ├── start_time: number        # 발화 시작 시각 (초)
│   ├── end_time: number          # 발화 종료 시각 (초)
│   ├── text: string              # 발화 내용
│   └── speaker_label: string     # teacher | children
│
├── ActivityBlock
│   ├── start_time: number        # 활동 블록 시작 (초)
│   ├── end_time: number          # 활동 블록 종료 (초)
│   ├── activity_type: string     # answering | singing | playing | repeating
│   └── confidence_score: number  # 탐지 신뢰도 (0.0~1.0)
│
└── Clip
    ├── clip_id: string           # 클립 고유 ID
    ├── clip_start: number        # 클립 시작 (초)
    ├── clip_end: number          # 클립 종료 (초)
    ├── clip_duration: number     # 클립 길이 (초)
    ├── activity_type: string     # 활동 유형
    ├── clip_status: string       # pending | approved | deleted
    └── output_path: string       # 출력 MP4 경로
```

---

## 6. 제안 기술 스택

### Backend
- **Python (FastAPI or Flask)** — 로컬 웹 서버
- **ffmpeg-python** — 영상 자르기, 포맷 변환
- **OpenAI Whisper API** — 음성 → 텍스트 변환 + 타임스탬프
- **GPT-4o API** — 트랜스크립트 분석 → 활동 블록 탐지
- **pyannote-audio (또는 대안)** — 화자 분리 (선생님 vs. 아이)

### Frontend
- **단일 HTML/JS 페이지** or **Streamlit** — 업로드, 클립 리스트, 미리보기, 다운로드
- 별도 프레임워크 최소화 (1인 로컬 도구이므로)

### 저장소
- 로컬 파일 시스템 (DB 불필요)
- 메타데이터는 JSON 또는 SQLite

---

## 7. 처리 파이프라인 (제안)

```
[1] 영상 업로드 (MP4)
        ↓
[2] ffmpeg: 오디오 추출 (WAV/MP3)
        ↓
[3] Whisper API: STT + 타임스탬프 생성
        ↓
[4] 화자 분리: 선생님 vs. 아이 레이블링
        ↓
[5] GPT-4o: 트랜스크립트 + 화자 정보 분석
         → 활동 블록(start, end, type) 추출
        ↓
[6] ffmpeg: 활동 블록 구간 클립으로 잘라내기
        ↓
[7] 클립 리뷰 UI: 목록 표시 + 미리보기
        ↓
[8] 사용자: 오검출 삭제 → 클립 MP4 다운로드
```

---

## 8. GPT-4o 프롬프트 전략 (제안)

트랜스크립트와 화자 레이블을 입력으로 주고, 아래를 추출하도록 요청:

```
역할: 영어 수업 영상 편집 보조자
입력: 타임스탬프 + 화자 레이블이 붙은 트랜스크립트
출력: 활동 블록 목록 (start_sec, end_sec, activity_type, reason)

활동 블록 조건:
- 아이(children)가 영어로 말하거나, 노래하거나, 질문에 대답하는 구간
- 선생님 질문 → 아이 대답 → 리액션을 하나의 블록으로 묶기
- 최소 15초, 최대 120초
- 신뢰도가 낮으면 포함하지 않는 것이 나음 (오검출보다 미검출 허용)
```

---

## 9. 평가 기준 (Evaluation Principles)

| 기준 | 가중치 | 설명 |
|------|--------|------|
| 탐지 재현율 | 30% | 주요 참여 구간을 합리적으로 뽑아냄 |
| 탐지 정밀도 | 25% | 오검출이 적어 리뷰 부담이 낮음 |
| 클립 경계 품질 | 20% | 시작/끝이 ±2~3초 이내로 자연스러움 |
| 사용성 | 15% | 업로드→리뷰→다운로드 흐름이 매끄러움 |
| 처리 효율 | 10% | CPU-only에서 당일 완료 가능 |

---

## 10. 완료 조건 (Exit Conditions)

1. **파이프라인 완성**: MP4 업로드 → 클립 다운로드 end-to-end 동작
2. **탐지 기능**: 5~10분 영상에서 0~3개 클립 자동 추출 (±2~3초 허용)
3. **리뷰 워크플로우**: 클립 목록 + 삭제 + 다운로드 UI 동작
4. **API 예산**: 일 5~10개 영상 처리 시 월 5만 원 이내
5. **포맷 처리**: 가로/세로 MP4 모두 오류 없이 처리

---

## 11. 논의가 필요한 열린 질문들

아래 항목들은 GPT와 논의하며 구체화할 부분입니다.

1. **화자 분리 방법**: pyannote-audio(로컬, CPU 느림) vs. AssemblyAI Speaker Diarization API(유료) vs. Whisper 결과만으로 휴리스틱 처리
2. **GPT-4o 비용 최적화**: 트랜스크립트 전체 vs. 청크 단위 전송, 캐싱 전략
3. **UI 프레임워크**: Streamlit(빠른 구현) vs. FastAPI + 단순 HTML(더 가벼움)
4. **비동기 처리**: 5~10개 영상을 순차 vs. 병렬 처리, 진행 상태 표시 방법
5. **클립 미리보기**: 브라우저 내 video 태그 vs. 썸네일 이미지만
6. **세로 영상 처리**: ffmpeg rotate 메타데이터 자동 처리 여부 확인 필요
7. **MVP 범위**: 1개 영상 처리 → 리뷰 → 다운로드 먼저, 일괄 처리는 v2

---

## 12. 메타데이터

```
Seed ID:         seed_54be8b5d5853
Interview ID:    interview_20260423_041432
Ambiguity Score: 0.18 (기준: ≤ 0.2)
생성일:          2026-04-23
버전:            1.0.0
```
