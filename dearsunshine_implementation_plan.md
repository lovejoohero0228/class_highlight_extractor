# DearSunshine 구현 계획서

## 0. 프로젝트 요약

**DearSunshine**은 영어 수업 MP4 영상을 업로드하면, 아이들이 영어로 말하거나 대답하거나 노래하거나 따라 말하는 구간을 자동으로 찾아 30초~2분짜리 하이라이트 후보 클립으로 잘라주는 웹 서비스다.

초기 버전은 **화자 분리 없이** 구현한다. 목표는 완벽한 자동 편집이 아니라, 선생님이 학부모에게 카카오톡으로 보내기 좋은 **수업 하이라이트 후보 영상**을 빠르게 만들어주는 것이다.

사용자는 1명이며, 로그인은 필요 없다. 모바일 웹 페이지에서 바로 영상을 업로드하고, 처리된 클립을 미리보고, 삭제하거나 다운로드할 수 있어야 한다.

---

## 1. 핵심 제품 방향

이 서비스는 “정밀한 화자 분석 시스템”이 아니라 **수업 하이라이트 후보 생성기**다.

따라서 MVP에서는 다음을 우선한다.

1. 모바일에서 MP4 업로드 가능
2. 서버에서 오디오 추출
3. Whisper API로 transcript + timestamp 생성
4. transcript를 기반으로 활동 구간 후보 탐지
5. GPT 모델로 후보 구간 정제
6. ffmpeg로 클립 생성
7. 모바일 웹에서 preview / delete / download 가능

MVP에서는 다음은 하지 않는다.

- 화자 분리
- 아이 개인 식별
- 학부모용 페이지
- 로그인 / 회원 관리
- 실시간 처리
- 복잡한 영상 편집 UI
- 브라우저 안에서 직접 트리밍

---

## 2. 권장 기술 스택

### Backend

- Python 3.11+
- FastAPI
- Uvicorn
- ffmpeg / ffprobe
- OpenAI API
- Pydantic
- python-multipart
- aiofiles

### Frontend

- 단일 HTML + CSS + Vanilla JS
- 모바일 우선 반응형 UI
- `<video controls>` 기반 preview
- 별도 React/Vue 불필요

### Storage

초기 버전은 DB 없이 로컬 파일 시스템 + JSON 메타데이터를 사용한다.

나중에 필요하면 SQLite로 이전할 수 있게 repository 계층을 얇게 둔다.

---

## 3. 배포 형태

초기 배포 목표는 다음 둘 중 하나다.

### Option A. 로컬 네트워크 배포

Windows PC에서 서버 실행:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

같은 Wi-Fi에 연결된 휴대폰에서 접속:

```text
http://<PC_LOCAL_IP>:8000
```

예:

```text
http://192.168.0.12:8000
```

### Option B. 개인용 외부 접속 배포

나만 쓰지만 외부에서 모바일 업로드가 필요하면 다음 중 하나 사용:

- Cloudflare Tunnel
- Tailscale Funnel
- ngrok
- Railway / Render / Fly.io 등의 작은 서버

단, 영상 파일을 업로드해야 하므로 무료 PaaS는 용량/타임아웃 제한을 확인해야 한다.

MVP에서는 **로컬 네트워크 배포**를 우선한다.

---

## 4. 디렉터리 구조

```text
dearsunshine/
├─ app/
│  ├─ main.py
│  ├─ config.py
│  ├─ models.py
│  ├─ storage.py
│  ├─ pipeline.py
│  ├─ ffmpeg_utils.py
│  ├─ transcription.py
│  ├─ highlight_detection.py
│  ├─ clipper.py
│  ├─ static/
│  │  ├─ index.html
│  │  ├─ styles.css
│  │  └─ app.js
│  └─ templates/
│     └─ index.html        # 선택 사항. Jinja 쓸 경우만.
├─ data/
│  ├─ uploads/
│  ├─ audio/
│  ├─ transcripts/
│  ├─ jobs/
│  └─ clips/
├─ tests/
├─ .env.example
├─ requirements.txt
├─ README.md
└─ run_local.bat
```

---

## 5. 데이터 모델

`app/models.py`

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Literal, Optional


class JobStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ClipStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    deleted = "deleted"


class VideoMetadata(BaseModel):
    video_id: str
    original_filename: str
    source_path: str
    duration_seconds: float | None = None
    orientation: Literal["landscape", "portrait", "unknown"] = "unknown"


class TranscriptSegment(BaseModel):
    start_time: float
    end_time: float
    text: str


class ActivityBlock(BaseModel):
    start_time: float
    end_time: float
    activity_type: Literal["answering", "singing", "repeating", "playing", "unknown"]
    confidence_score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class Clip(BaseModel):
    clip_id: str
    video_id: str
    clip_start: float
    clip_end: float
    clip_duration: float
    activity_type: str
    confidence_score: float
    clip_status: ClipStatus = ClipStatus.pending
    output_path: str
    preview_url: str | None = None
    download_url: str | None = None


class Job(BaseModel):
    job_id: str
    status: JobStatus
    video: VideoMetadata
    progress: int = 0
    message: str = ""
    transcript_path: Optional[str] = None
    clips: list[Clip] = []
    error: Optional[str] = None
```

---

## 6. API 설계

### `GET /`

모바일 웹 UI 반환.

### `POST /api/videos`

MP4 업로드.

Request:

```text
multipart/form-data
file: video/mp4
```

Response:

```json
{
  "job_id": "job_xxx",
  "status": "uploaded"
}
```

업로드 후 백그라운드 작업으로 pipeline 실행.

### `GET /api/jobs`

최근 작업 목록 반환.

Response:

```json
[
  {
    "job_id": "job_xxx",
    "status": "completed",
    "progress": 100,
    "message": "3 clips generated",
    "video": {
      "original_filename": "class_001.mp4"
    }
  }
]
```

### `GET /api/jobs/{job_id}`

작업 상세 조회.

Response:

```json
{
  "job_id": "job_xxx",
  "status": "completed",
  "progress": 100,
  "message": "completed",
  "clips": [
    {
      "clip_id": "clip_xxx",
      "clip_start": 12.5,
      "clip_end": 64.0,
      "clip_duration": 51.5,
      "activity_type": "answering",
      "confidence_score": 0.84,
      "preview_url": "/api/clips/clip_xxx/preview",
      "download_url": "/api/clips/clip_xxx/download"
    }
  ]
}
```

### `DELETE /api/clips/{clip_id}`

클립을 삭제 처리한다. 실제 파일을 지우거나 `clip_status=deleted`로 변경한다.

Response:

```json
{
  "ok": true
}
```

### `GET /api/clips/{clip_id}/preview`

브라우저 `<video>`에서 재생 가능한 MP4 파일 반환.

### `GET /api/clips/{clip_id}/download`

MP4 다운로드.

---

## 7. 처리 파이프라인

`app/pipeline.py`

```text
process_video(job_id)
  1. load job metadata
  2. update status = processing, progress = 5
  3. ffprobe로 duration/orientation 확인
  4. ffmpeg로 audio wav 추출
  5. Whisper API로 transcript 생성
  6. transcript JSON 저장
  7. transcript 기반 활동 후보 생성
  8. GPT로 후보 정제
  9. clip start/end 보정
 10. ffmpeg로 clip 생성
 11. job metadata 업데이트
 12. status = completed
```

실패 시:

```text
status = failed
error = exception message
```

---

## 8. ffmpeg 처리

### 오디오 추출

```bash
ffmpeg -y -i input.mp4 -vn -ac 1 -ar 16000 output.wav
```

### 영상 자르기

정확성과 호환성을 위해 MVP에서는 재인코딩을 사용한다.

```bash
ffmpeg -y \
  -ss {start} \
  -to {end} \
  -i input.mp4 \
  -map 0:v:0 -map 0:a? \
  -c:v libx264 \
  -preset veryfast \
  -crf 23 \
  -c:a aac \
  -movflags +faststart \
  output.mp4
```

주의:

- 모바일 브라우저 호환성을 위해 H.264 + AAC 사용
- `-movflags +faststart` 필수
- 세로 영상은 원본 orientation metadata를 확인해야 함
- 가능하면 처음에는 재인코딩으로 안정성 우선

---

## 9. Transcript 생성

`app/transcription.py`

OpenAI Whisper API를 사용한다.

요구 출력:

```json
[
  {
    "start_time": 0.0,
    "end_time": 3.2,
    "text": "Hello everyone."
  }
]
```

구현 시 주의:

- 같은 영상 재처리 시 transcript 파일이 있으면 API 재호출하지 않는다.
- transcript 파일명은 `{job_id}.json` 또는 `{video_id}.json` 사용.
- API 실패 시 job failed 처리.

---

## 10. 하이라이트 후보 탐지 전략

MVP는 두 단계로 구성한다.

### 10.1 규칙 기반 1차 후보 생성

Transcript segment를 순회하면서 다음 패턴을 찾는다.

#### 질문-응답 패턴

영어 수업에서 자주 나오는 교사 발화:

```text
what is this
what color
what animal
how many
who is this
can you say
repeat after me
say it again
what do you see
is it a ...
do you like ...
let's say
let's read
```

이런 문장 이후 5~30초 구간을 후보로 잡는다.

#### 반복/따라 말하기 패턴

```text
repeat after me
say
one more time
together
everybody
again
```

해당 segment 전후 10~45초를 후보로 잡는다.

#### 노래/챈트 패턴

```text
song
sing
music
clap
chant
let's sing
```

해당 segment 전후 30~120초를 후보로 잡는다.

#### 리액션 패턴

```text
good job
great
excellent
very good
well done
nice
```

리액션 앞 20~45초를 후보로 잡는다.

### 10.2 후보 병합

겹치거나 가까운 후보는 병합한다.

규칙:

- 후보 간 gap이 8초 이하이면 병합
- 병합 후 120초 초과 시 confidence 높은 구간 중심으로 자름
- 최소 길이 20초 미만이면 제거하거나 앞뒤 padding 추가
- 최종 후보는 영상당 최대 5개만 GPT에 보냄

### 10.3 GPT 기반 정제

규칙 기반 후보 주변의 transcript window만 GPT에 보낸다.

GPT는 다음을 판단한다.

- 학부모에게 보여줄 만한 학생 참여 구간인가
- 자연스러운 시작/끝 지점은 어디인가
- 활동 유형은 무엇인가
- 신뢰도는 얼마인가

최종 출력은 영상당 0~3개 클립만 사용한다.

---

## 11. GPT 프롬프트

`app/highlight_detection.py`에 프롬프트 상수로 둔다.

```text
You are an assistant that helps create highlight clips from English class videos.

The transcript is from a short English class video recorded on a phone.
The goal is to find moments where children are actively participating: answering, repeating, singing, chanting, playing, or responding in English.

Important:
- Do not require speaker diarization.
- Infer activity from classroom structure and transcript patterns.
- A good highlight usually includes: teacher prompt/question -> child or group response -> teacher reaction.
- Prefer fewer, higher-quality clips.
- False positives are worse than missing a weak moment.
- Each final clip should be 30 to 120 seconds when possible.
- It is okay to return zero clips.

Return JSON only.

Input:
- video_duration_sec
- transcript segments with start_time, end_time, text
- candidate windows generated by rules

Output schema:
{
  "clips": [
    {
      "start_sec": 12.5,
      "end_sec": 67.0,
      "activity_type": "answering",
      "confidence_score": 0.84,
      "reason": "Teacher asks a question, children answer repeatedly, and teacher gives positive feedback."
    }
  ]
}

Allowed activity_type values:
- answering
- singing
- repeating
- playing
- unknown

Rules:
- Keep start_sec and end_sec within the video duration.
- Add enough context so the clip feels natural.
- Avoid clips that are mostly teacher talking.
- Avoid clips with unclear student participation.
- Limit to the best 0 to 3 clips.
```

---

## 12. 클립 경계 보정

GPT 결과를 그대로 쓰지 말고 후처리한다.

```python
MIN_CLIP_SEC = 30
MAX_CLIP_SEC = 120
START_PADDING_SEC = 2
END_PADDING_SEC = 3
```

보정 규칙:

1. start = max(0, start - START_PADDING_SEC)
2. end = min(duration, end + END_PADDING_SEC)
3. 길이가 30초 미만이면 중심 기준으로 확장
4. 길이가 120초 초과면 중심 기준으로 축소
5. start < end 검증
6. confidence 0.55 미만은 제거
7. confidence 순으로 정렬 후 최대 3개만 유지

---

## 13. 모바일 UI 요구사항

`app/static/index.html`

### 화면 구성

1. 헤더
   - DearSunshine
   - English Class Highlight Generator

2. 업로드 카드
   - MP4 선택
   - 업로드 버튼
   - 모바일 카메라/갤러리 선택 지원

```html
<input type="file" accept="video/mp4,video/*" multiple>
```

3. 작업 목록
   - 파일명
   - 상태
   - 진행률
   - 에러 메시지

4. 클립 목록
   - activity type
   - confidence
   - start/end
   - `<video controls playsinline>` preview
   - delete 버튼
   - download 버튼

### 모바일 UX

- 버튼은 터치하기 쉽게 높이 44px 이상
- 카드형 레이아웃
- 긴 텍스트 최소화
- 처리 중에는 progress 표시
- iPhone Safari 대응을 위해 `playsinline` 사용

---

## 14. Frontend 동작

`app/static/app.js`

### Upload

```javascript
async function uploadFiles(files) {
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);

    const res = await fetch("/api/videos", {
      method: "POST",
      body: form,
    });

    const data = await res.json();
    addJobToList(data.job_id);
  }
}
```

### Polling

```javascript
setInterval(async () => {
  const res = await fetch("/api/jobs");
  const jobs = await res.json();
  renderJobs(jobs);
}, 3000);
```

### Preview

```html
<video controls playsinline preload="metadata" src="/api/clips/{clip_id}/preview"></video>
```

### Download

```html
<a href="/api/clips/{clip_id}/download" download>Download</a>
```

---

## 15. 환경 변수

`.env.example`

```bash
OPENAI_API_KEY=your_api_key_here
DATA_DIR=./data
MAX_UPLOAD_MB=1000
OPENAI_TRANSCRIBE_MODEL=whisper-1
OPENAI_ANALYSIS_MODEL=gpt-4o-mini
```

분석 모델은 비용 절감을 위해 처음에는 `gpt-4o-mini`를 우선 사용한다. 품질이 부족하면 `gpt-4o`로 바꿀 수 있게 설정화한다.

---

## 16. requirements.txt

```text
fastapi
uvicorn[standard]
python-multipart
aiofiles
pydantic
pydantic-settings
openai
python-dotenv
```

ffmpeg는 Python 패키지가 아니라 시스템에 설치되어 PATH에서 실행 가능해야 한다.

Windows에서는 다음 중 하나로 설치 가능하다.

```bash
winget install Gyan.FFmpeg
```

또는 ffmpeg zip을 내려받아 PATH에 추가한다.

---

## 17. FastAPI 구현 스케치

`app/main.py`

```python
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.storage import create_job, list_jobs, get_job, save_job, find_clip
from app.pipeline import process_video

app = FastAPI(title="DearSunshine")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def index():
    return FileResponse("app/static/index.html")


@app.post("/api/videos")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".mp4", ".mov", ".m4v")):
        raise HTTPException(status_code=400, detail="Only video files are supported")

    job = await create_job(file)
    background_tasks.add_task(process_video, job.job_id)
    return {"job_id": job.job_id, "status": job.status}


@app.get("/api/jobs")
def api_list_jobs():
    return list_jobs()


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/clips/{clip_id}")
def api_delete_clip(clip_id: str):
    clip, job = find_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip.clip_status = "deleted"
    save_job(job)
    return {"ok": True}


@app.get("/api/clips/{clip_id}/preview")
def api_preview_clip(clip_id: str):
    clip, _ = find_clip(clip_id)
    if not clip or clip.clip_status == "deleted":
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(clip.output_path, media_type="video/mp4")


@app.get("/api/clips/{clip_id}/download")
def api_download_clip(clip_id: str):
    clip, _ = find_clip(clip_id)
    if not clip or clip.clip_status == "deleted":
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(
        clip.output_path,
        media_type="video/mp4",
        filename=f"dearsunshine_{clip.clip_id}.mp4",
    )
```

---

## 18. 저장소 구현 방향

`app/storage.py`

- job 생성 시 UUID 사용
- 업로드 파일은 `data/uploads/{job_id}_{safe_filename}`
- job metadata는 `data/jobs/{job_id}.json`
- transcript는 `data/transcripts/{job_id}.json`
- clips는 `data/clips/{job_id}/clip_001.mp4`

필수 함수:

```python
async def create_job(file: UploadFile) -> Job

def get_job(job_id: str) -> Job | None

def save_job(job: Job) -> None

def list_jobs() -> list[Job]

def find_clip(clip_id: str) -> tuple[Clip | None, Job | None]
```

---

## 19. 보안 및 개인 사용 전제

나만 쓰는 서비스이므로 로그인은 MVP에서 제외한다.

단, 외부 URL로 노출할 경우 최소한 다음 중 하나는 적용한다.

1. Cloudflare Access
2. Basic Auth
3. 긴 secret path
4. Tailscale 같은 private network

외부 공개 인터넷에 인증 없이 열지 않는다.

---

## 20. 테스트 시나리오

### 기본 기능

1. 모바일 브라우저에서 접속
2. MP4 업로드
3. 처리 상태가 processing으로 변경
4. 완료 후 클립 목록 표시
5. 각 클립 preview 재생
6. 불필요한 클립 삭제
7. 남은 클립 다운로드

### 영상 케이스

- 5분 가로 영상
- 10분 세로 영상
- 아이들 노래 포함 영상
- 질문-대답 중심 영상
- 거의 선생님만 말하는 영상
- 무음/소음 많은 영상
- 클립이 0개여야 하는 영상

### 품질 기준

- 영상당 0~3개 클립 생성
- 클립 길이 30~120초
- 모바일에서 재생 가능
- 다운로드된 파일이 카카오톡 전송 가능
- 오검출은 UI에서 쉽게 삭제 가능

---

## 21. MVP 완료 조건

다음이 가능하면 MVP 완료로 본다.

1. 모바일 웹에서 MP4 업로드 가능
2. 업로드된 영상이 서버에서 처리됨
3. Whisper transcript 생성됨
4. 활동 단위 후보 클립이 0~3개 생성됨
5. 클립이 MP4로 저장됨
6. 모바일 웹에서 preview 가능
7. 클립 삭제 가능
8. 클립 다운로드 가능
9. 세로/가로 영상 모두 재생 오류 없음
10. 같은 영상 재처리 시 transcript 캐시 사용

---

## 22. 구현 우선순위

### 1순위

- FastAPI 서버
- 모바일 HTML UI
- 업로드
- ffmpeg 오디오 추출
- Whisper transcription
- 기본 후보 탐지
- ffmpeg clip 생성
- preview/download

### 2순위

- GPT 기반 후보 정제
- 여러 파일 업로드
- 진행률 표시 개선
- 에러 처리
- transcript 캐시

### 3순위

- Basic Auth
- Cloudflare Tunnel 배포 문서
- SQLite 이전
- 클립 이름 자동 생성
- ZIP 다운로드
- 수동 start/end 조정 UI

---

## 23. Codex에게 주는 구현 지시

다음 순서로 구현한다.

1. 위 디렉터리 구조 생성
2. FastAPI skeleton 작성
3. 정적 모바일 UI 작성
4. 로컬 파일 저장소 작성
5. ffmpeg utility 작성
6. upload API와 job metadata 저장 구현
7. background task pipeline 구현
8. Whisper API 연동
9. 규칙 기반 highlight candidate detector 구현
10. GPT refinement 함수 구현
11. clipper 구현
12. preview/download/delete API 구현
13. 모바일 브라우저에서 end-to-end 테스트
14. README에 Windows 실행법 작성
15. `.env.example`, `requirements.txt`, `run_local.bat` 작성

처음부터 완벽한 탐지 정확도를 목표로 하지 말고, end-to-end가 먼저 동작하도록 구현한다.

---

## 24. run_local.bat 예시

```bat
@echo off
call conda activate dearsunshine
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
```

---

## 25. README 실행 안내 예시

```bash
conda create -n dearsunshine python=3.11 -y
conda activate dearsunshine
pip install -r requirements.txt
copy .env.example .env
```

`.env`에 OpenAI API key 입력.

ffmpeg 설치 확인:

```bash
ffmpeg -version
ffprobe -version
```

서버 실행:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PC에서 접속:

```text
http://localhost:8000
```

휴대폰에서 접속:

```text
http://<PC_LOCAL_IP>:8000
```

---

## 26. 중요한 설계 원칙

- MVP는 화자분리 없이 간다.
- 사용자가 직접 리뷰하고 삭제할 수 있으므로 false positive를 완전히 없애려고 과도하게 복잡하게 만들지 않는다.
- 대신 너무 많은 클립을 만들지 않는다. 영상당 최대 3개가 좋다.
- 모바일 preview/download UX를 가장 중요하게 본다.
- API 비용이 발생하는 transcript와 GPT 결과는 반드시 캐시한다.
- ffmpeg 결과물은 모바일 호환성을 우선해 H.264/AAC MP4로 만든다.
- 외부 배포 시 인증 없이 공개하지 않는다.
