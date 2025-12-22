"""
Person API - FastAPI application
"""
import json
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import redis
from .config import DATABASE_URL, REDIS_URL

# FastAPI 앱 인스턴스 생성
app = FastAPI(title="Person API", version="1.0.0")

# 환경 변수 기반 설정
CHANNEL_PHOTO_REINDEX = 'photo:reindex'
# Redis 연결은 전역으로 생성 (이벤트 발행에 사용)
redis_client = redis.from_url(REDIS_URL)
# ignored_faces 테이블 생성 여부를 프로세스 전역에서 캐싱
_ignored_faces_table_ready = False

# DB 연결 헬퍼 (요청 단위로 생성/종료)
def get_db():
    return psycopg2.connect(DATABASE_URL)

# ignored_faces 테이블이 없는 환경을 대비해 최초 1회만 생성
def ensure_ignored_faces_table(conn):
    global _ignored_faces_table_ready
    if _ignored_faces_table_ready:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ignored_faces (
                id UUID PRIMARY KEY,
                owner_id UUID NOT NULL,
                face_embedding_id UUID NOT NULL REFERENCES face_embeddings(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(owner_id, face_embedding_id)
            );
        """)
    conn.commit()
    _ignored_faces_table_ready = True

# --- Models ---

# 사람 생성 요청 바디
class PersonCreate(BaseModel):
    name: str
    relationship: Optional[str] = None
    notes: Optional[str] = None

# 사람 수정 요청 바디 (부분 업데이트)
class PersonUpdate(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None
    notes: Optional[str] = None

# 얼굴-사람 연결 요청 바디
class FaceAssign(BaseModel):
    person_id: str

# --- Person CRUD ---

@app.post("/persons")
def create_person(person: PersonCreate, x_user_id: str = Header(...)):
    """Create a new person"""
    # 요청 헤더의 x-user-id를 소유자 기준으로 사용
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 신규 person UUID 발급
            person_id = str(uuid.uuid4())
            # persons 테이블에 레코드 삽입
            cur.execute("""
                INSERT INTO persons (id, owner_id, name, relationship, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (person_id, x_user_id, person.name, person.relationship, person.notes))
            result = cur.fetchone()
            # 트랜잭션 커밋 후 생성 결과 반환
            conn.commit()
            return result
    finally:
        # 연결 누수 방지를 위해 반드시 종료
        conn.close()

@app.get("/persons")
def list_persons(x_user_id: str = Header(...)):
    """List all persons for the user"""
    # 소유자 기준으로 person 목록 조회
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT p.*, 
                       (SELECT COUNT(*) FROM photo_persons pp WHERE pp.person_id = p.id) as photo_count
                FROM persons p
                WHERE p.owner_id = %s
                ORDER BY p.name
            """, (x_user_id,))
            # 각 person에 연결된 사진 수를 함께 반환
            return cur.fetchall()
    finally:
        conn.close()

@app.get("/persons/{person_id}")
def get_person(person_id: str, x_user_id: str = Header(...)):
    """Get person details"""
    # path 파라미터의 person_id와 소유자 기준으로 단건 조회
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM persons WHERE id = %s AND owner_id = %s
            """, (person_id, x_user_id))
            result = cur.fetchone()
            if not result:
                # 소유자 검증 실패 또는 존재하지 않음
                raise HTTPException(status_code=404, detail="Person not found")
            return result
    finally:
        conn.close()

@app.put("/persons/{person_id}")
def update_person(person_id: str, person: PersonUpdate, x_user_id: str = Header(...)):
    """Update person"""
    # 부분 업데이트: 요청 값이 없으면 기존 값 유지
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE persons 
                SET name = COALESCE(%s, name),
                    relationship = COALESCE(%s, relationship),
                    notes = COALESCE(%s, notes),
                    updated_at = NOW()
                WHERE id = %s AND owner_id = %s
                RETURNING *
            """, (person.name, person.relationship, person.notes, person_id, x_user_id))
            result = cur.fetchone()
            conn.commit()
            if not result:
                # 대상이 없거나 소유자가 다르면 404
                raise HTTPException(status_code=404, detail="Person not found")
            return result
    finally:
        conn.close()

@app.delete("/persons/{person_id}")
def delete_person(person_id: str, x_user_id: str = Header(...)):
    """Delete person"""
    # 소유자 기준으로 person 삭제
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM persons WHERE id = %s AND owner_id = %s
            """, (person_id, x_user_id))
            conn.commit()
            if cur.rowcount == 0:
                # 삭제 대상 없음
                raise HTTPException(status_code=404, detail="Person not found")
            return {"message": "Deleted"}
    finally:
        conn.close()

# --- Face Management ---

@app.get("/faces/unassigned")
def list_unassigned_faces(x_user_id: str = Header(...)):
    """List faces that haven't been confirmed as belonging to a person"""
    # 미지정 얼굴 목록: 확정 연결이 없고(ignore 포함) 아닌 얼굴만 조회
    conn = get_db()
    try:
        ensure_ignored_faces_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                       fe.id, fe.media_id, fe.bbox_x, fe.bbox_y,
                       fe.bbox_width, fe.bbox_height, fe.created_at,
                       spp.person_id as suggested_person_id,
                       sp.name as suggested_person_name
                FROM face_embeddings fe
                JOIN analysis_results ar ON fe.media_id = ar.media_id
                LEFT JOIN photo_persons cpp
                  ON cpp.face_embedding_id = fe.id AND cpp.confirmed = true
                LEFT JOIN ignored_faces ig
                  ON ig.face_embedding_id = fe.id AND ig.owner_id = ar.owner_id
                LEFT JOIN LATERAL (
                  SELECT pp.person_id
                  FROM photo_persons pp
                  WHERE pp.face_embedding_id = fe.id AND pp.confirmed = false
                  ORDER BY pp.created_at DESC
                  LIMIT 1
                ) spp ON true
                LEFT JOIN persons sp
                  ON sp.id = spp.person_id
                WHERE ar.owner_id = %s
                  AND cpp.id IS NULL
                  AND ig.id IS NULL
                ORDER BY fe.created_at DESC
            """, (x_user_id,))
            # 추천 인물(confirmed=false) 정보가 있으면 함께 리턴
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/faces/{face_id}/ignore")
def ignore_face(face_id: str, x_user_id: str = Header(...)):
    """Ignore a face so it won't show up in the unassigned list"""
    # 특정 얼굴을 무시 처리하여 UI/조회에서 제외
    conn = get_db()
    try:
        ensure_ignored_faces_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 얼굴이 본인 소유인지 확인
            cur.execute("""
                SELECT fe.id
                FROM face_embeddings fe
                JOIN analysis_results ar ON ar.media_id = fe.media_id
                WHERE fe.id = %s AND ar.owner_id = %s
            """, (face_id, x_user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Face not found")

            # ignored_faces에 삽입 (중복은 무시)
            cur.execute("""
                INSERT INTO ignored_faces (id, owner_id, face_embedding_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (owner_id, face_embedding_id) DO NOTHING
            """, (str(uuid.uuid4()), x_user_id, face_id))

            # 자동 추천(confirmed=false) 연결은 제거
            cur.execute("""
                DELETE FROM photo_persons
                WHERE face_embedding_id = %s AND confirmed = false
            """, (face_id,))

            conn.commit()
            return {"message": "Face ignored", "face_id": face_id}
    finally:
        conn.close()

@app.post("/faces/{face_id}/assign")
def assign_face_to_person(face_id: str, data: FaceAssign, x_user_id: str = Header(...)):
    """Assign a face to a person"""
    # 얼굴을 특정 person에 확정 연결하는 엔드포인트
    conn = get_db()
    try:
        ensure_ignored_faces_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # person이 요청 사용자 소유인지 검증
            cur.execute("SELECT id FROM persons WHERE id = %s AND owner_id = %s", 
                       (data.person_id, x_user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Person not found")
            
            # face_embeddings에 person_id 업데이트
            cur.execute("""
                UPDATE face_embeddings SET person_id = %s WHERE id = %s
                RETURNING media_id
            """, (data.person_id, face_id))
            result = cur.fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail="Face not found")

            # 무시 목록에서 제거 (있다면)
            cur.execute("""
                DELETE FROM ignored_faces
                WHERE owner_id = %s AND face_embedding_id = %s
            """, (x_user_id, face_id))

            # 자동 추천(confirmed=false) 연결 제거
            cur.execute("""
                DELETE FROM photo_persons
                WHERE face_embedding_id = %s AND confirmed = false
            """, (face_id,))

            # media-person 확정 연결 생성/갱신 (upsert)
            cur.execute("""
                INSERT INTO photo_persons (id, media_id, person_id, face_embedding_id, confirmed)
                VALUES (%s, %s, %s, %s, true)
                ON CONFLICT (media_id, person_id) DO UPDATE
                SET face_embedding_id = EXCLUDED.face_embedding_id,
                    confirmed = true
            """, (str(uuid.uuid4()), result['media_id'], data.person_id, face_id))
            
            conn.commit()
            try:
                # 사진 재색인 이벤트 발행 (실패하더라도 API는 성공 처리)
                redis_client.publish(CHANNEL_PHOTO_REINDEX, json.dumps({
                    'mediaId': result['media_id'],
                }))
            except Exception as e:
                print(f"[Person API] Failed to publish reindex event: {e}")

            return {"message": "Face assigned", "person_id": data.person_id, "media_id": result['media_id']}
    finally:
        conn.close()

# --- Analysis Status ---

@app.get("/analysis/{media_id}")
def get_analysis_status(media_id: str, x_user_id: str = Header(...)):
    """Get analysis status for a media"""
    # 분석 결과를 media_id + owner 기준으로 조회
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM analysis_results 
                WHERE media_id = %s AND owner_id = %s
            """, (media_id, x_user_id))
            result = cur.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Analysis not found")
            return result
    finally:
        conn.close()

@app.get("/health")
def health_check():
    # 헬스 체크용 간단 응답
    return {"status": "ok"}
