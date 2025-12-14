# 11. AI Service

범용 AI 처리 서비스 - 얼굴 인식, 메타데이터 추출, 인물 관리

## 구성

- `ai-worker/` - Python 얼굴 인식 워커 (Redis Subscribe)
- `person-api/` - FastAPI 인물 관리 API
- `sql/` - PostgreSQL + pgvector 초기화

## 빠른 시작

```bash
# 네트워크 필요 (최초 1회)
docker network create 10_modules

# 02.Media가 먼저 실행되어 있어야 함 (Redis, MinIO)
cd ../02.Media && docker compose up -d

# 11.AI 시작
cd ../11.AI
docker compose up --build
```

## 서비스

| 서비스 | 포트 | 설명 |
|:---|:---|:---|
| ai-postgres | 5433 | PostgreSQL + pgvector |
| ai-worker | - | 얼굴 분석 워커 (Redis Subscribe) |
| person-api | 5001 | 인물 관리 REST API |

## API 엔드포인트

### Person API (http://localhost:5001)

| Method | Path | 설명 |
|:---|:---|:---|
| POST | /persons | 인물 등록 |
| GET | /persons | 목록 조회 |
| GET | /persons/:id | 상세 조회 |
| PUT | /persons/:id | 수정 |
| DELETE | /persons/:id | 삭제 |
| GET | /faces/unassigned | 미확인 얼굴 목록 |
| POST | /faces/:faceId/assign | 얼굴에 인물 할당 |
| GET | /analysis/:mediaId | 분석 상태 조회 |

## 흐름

```
02.Media 사진 업로드
    ↓ Redis PUBLISH (photo:uploaded)
AI Worker 수신
    ↓ 얼굴 감지 + EXIF 파싱
    ↓ pgvector 유사도 검색
    ↓ 결과 저장
Redis PUBLISH (photo:analyzed)
    ↓
03.Search 인덱싱
```
