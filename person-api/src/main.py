"""
Person API - FastAPI application
"""
import os
import json
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import redis

app = FastAPI(title="Person API", version="1.0.0")

DATABASE_URL = os.getenv('DATABASE_URL', 'postgres://ai:ai_password@localhost:5433/ai_db')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
CHANNEL_PHOTO_REINDEX = 'photo:reindex'
redis_client = redis.from_url(REDIS_URL)

def get_db():
    return psycopg2.connect(DATABASE_URL)

# --- Models ---

class PersonCreate(BaseModel):
    name: str
    relationship: Optional[str] = None
    notes: Optional[str] = None

class PersonUpdate(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None
    notes: Optional[str] = None

class FaceAssign(BaseModel):
    person_id: str

# --- Person CRUD ---

@app.post("/persons")
def create_person(person: PersonCreate, x_user_id: str = Header(...)):
    """Create a new person"""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            person_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO persons (id, owner_id, name, relationship, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (person_id, x_user_id, person.name, person.relationship, person.notes))
            result = cur.fetchone()
            conn.commit()
            return result
    finally:
        conn.close()

@app.get("/persons")
def list_persons(x_user_id: str = Header(...)):
    """List all persons for the user"""
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
            return cur.fetchall()
    finally:
        conn.close()

@app.get("/persons/{person_id}")
def get_person(person_id: str, x_user_id: str = Header(...)):
    """Get person details"""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM persons WHERE id = %s AND owner_id = %s
            """, (person_id, x_user_id))
            result = cur.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Person not found")
            return result
    finally:
        conn.close()

@app.put("/persons/{person_id}")
def update_person(person_id: str, person: PersonUpdate, x_user_id: str = Header(...)):
    """Update person"""
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
                raise HTTPException(status_code=404, detail="Person not found")
            return result
    finally:
        conn.close()

@app.delete("/persons/{person_id}")
def delete_person(person_id: str, x_user_id: str = Header(...)):
    """Delete person"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM persons WHERE id = %s AND owner_id = %s
            """, (person_id, x_user_id))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Person not found")
            return {"message": "Deleted"}
    finally:
        conn.close()

# --- Face Management ---

@app.get("/faces/unassigned")
def list_unassigned_faces(x_user_id: str = Header(...)):
    """List faces that haven't been assigned to a person"""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT fe.id, fe.media_id, fe.bbox_x, fe.bbox_y, 
                       fe.bbox_width, fe.bbox_height, fe.created_at
                FROM face_embeddings fe
                JOIN analysis_results ar ON fe.media_id = ar.media_id
                WHERE ar.owner_id = %s AND fe.person_id IS NULL
                ORDER BY fe.created_at DESC
            """, (x_user_id,))
            return cur.fetchall()
    finally:
        conn.close()

@app.post("/faces/{face_id}/assign")
def assign_face_to_person(face_id: str, data: FaceAssign, x_user_id: str = Header(...)):
    """Assign a face to a person"""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verify person belongs to user
            cur.execute("SELECT id FROM persons WHERE id = %s AND owner_id = %s", 
                       (data.person_id, x_user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Person not found")
            
            # Update face embedding
            cur.execute("""
                UPDATE face_embeddings SET person_id = %s WHERE id = %s
                RETURNING media_id
            """, (data.person_id, face_id))
            result = cur.fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail="Face not found")
            
            # Create photo-person link
            cur.execute("""
                INSERT INTO photo_persons (id, media_id, person_id, face_embedding_id, confirmed)
                VALUES (%s, %s, %s, %s, true)
                ON CONFLICT (media_id, person_id) DO UPDATE SET confirmed = true
            """, (str(uuid.uuid4()), result['media_id'], data.person_id, face_id))
            
            conn.commit()
            try:
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
    return {"status": "ok"}
