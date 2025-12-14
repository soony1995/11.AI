"""
Database operations for AI Worker
Uses pgvector for face embedding similarity search
"""
import uuid
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector


class Database:
    def __init__(self, database_url: str):
        self.conn = psycopg2.connect(database_url)
        register_vector(self.conn)
    
    def create_analysis(self, media_id: str, owner_id: str):
        """Create initial analysis record"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO analysis_results (id, media_id, owner_id, status)
                VALUES (%s, %s, %s, 'PENDING')
                ON CONFLICT (media_id) DO UPDATE SET status = 'PENDING', updated_at = NOW()
            """, (str(uuid.uuid4()), media_id, owner_id))
            self.conn.commit()
    
    def update_analysis_status(self, media_id: str, status: str):
        """Update analysis status"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE analysis_results 
                SET status = %s, updated_at = NOW()
                WHERE media_id = %s
            """, (status, media_id))
            self.conn.commit()
    
    def update_analysis_complete(self, media_id: str, face_count: int,
                                  taken_at=None, latitude=None, longitude=None,
                                  camera_make=None, camera_model=None):
        """Update analysis with results"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE analysis_results 
                SET status = 'DONE',
                    face_count = %s,
                    taken_at = %s,
                    latitude = %s,
                    longitude = %s,
                    camera_make = %s,
                    camera_model = %s,
                    analyzed_at = NOW(),
                    updated_at = NOW()
                WHERE media_id = %s
            """, (face_count, taken_at, latitude, longitude, 
                  camera_make, camera_model, media_id))
            self.conn.commit()
    
    def update_analysis_error(self, media_id: str, error_message: str):
        """Update analysis with error"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE analysis_results 
                SET status = 'FAILED', error_message = %s, updated_at = NOW()
                WHERE media_id = %s
            """, (error_message, media_id))
            self.conn.commit()
    
    def save_face_embedding(self, media_id: str, embedding: list, 
                            bbox: dict, person_id: str = None) -> str:
        """Save face embedding to database"""
        face_id = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO face_embeddings 
                (id, media_id, person_id, embedding, bbox_x, bbox_y, bbox_width, bbox_height)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (face_id, media_id, person_id, embedding,
                  bbox.get('x'), bbox.get('y'), 
                  bbox.get('width'), bbox.get('height')))
            self.conn.commit()
        return face_id
    
    def find_similar_face(self, embedding: list, owner_id: str, 
                          threshold: float = 0.6) -> str | None:
        """
        Find similar face in database using cosine similarity
        Returns person_id if found, None otherwise
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Use pgvector cosine distance (<=>)
            cur.execute("""
                SELECT fe.person_id, 
                       1 - (fe.embedding <=> %s::vector) as similarity
                FROM face_embeddings fe
                JOIN persons p ON fe.person_id = p.id
                WHERE p.owner_id = %s
                  AND fe.person_id IS NOT NULL
                ORDER BY fe.embedding <=> %s::vector
                LIMIT 1
            """, (embedding, owner_id, embedding))
            
            result = cur.fetchone()
            if result and result['similarity'] >= (1 - threshold):
                return result['person_id']
            return None
    
    def link_photo_person(self, media_id: str, person_id: str, 
                          face_id: str = None, confirmed: bool = False):
        """Link a photo to a person"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO photo_persons (id, media_id, person_id, face_embedding_id, confirmed)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (media_id, person_id) DO UPDATE 
                SET face_embedding_id = EXCLUDED.face_embedding_id,
                    confirmed = EXCLUDED.confirmed
            """, (str(uuid.uuid4()), media_id, person_id, face_id, confirmed))
            self.conn.commit()
