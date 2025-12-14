"""
AI Worker - Main entry point
Listens to Redis pub/sub for photo events and processes them
"""
import os
import json
import redis
from .face_detector import FaceDetector
from .exif_parser import ExifParser
from .db import Database
from .storage import StorageClient

# Configuration
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgres://ai:ai_password@localhost:5433/ai_db')

# Redis channels
CHANNEL_PHOTO_UPLOADED = 'photo:uploaded'
CHANNEL_PHOTO_ANALYZED = 'photo:analyzed'

def main():
    print("[AI Worker] Starting...")
    
    # Initialize components
    redis_client = redis.from_url(REDIS_URL)
    pubsub = redis_client.pubsub()
    db = Database(DATABASE_URL)
    storage = StorageClient()
    face_detector = FaceDetector()
    exif_parser = ExifParser()
    
    # Subscribe to photo events
    pubsub.subscribe(CHANNEL_PHOTO_UPLOADED)
    print(f"[AI Worker] Subscribed to {CHANNEL_PHOTO_UPLOADED}")
    
    # Process messages
    for message in pubsub.listen():
        if message['type'] != 'message':
            continue
            
        try:
            payload = json.loads(message['data'])
            media_id = payload['id']
            owner_id = payload['ownerId']
            stored_key = payload['storedKey']
            
            print(f"[AI Worker] Processing: {media_id}")
            
            # Create analysis record
            db.create_analysis(media_id, owner_id)
            db.update_analysis_status(media_id, 'PROCESSING')
            
            # Download image from storage
            image_bytes = storage.download(stored_key)
            
            # Step 1: Parse EXIF
            exif_data = exif_parser.parse(image_bytes)
            
            # Step 2: Detect faces
            faces = face_detector.detect_faces(image_bytes)
            embeddings = face_detector.get_embeddings(image_bytes)
            
            # Step 3: Save face embeddings and match with existing persons
            face_count = 0
            for i, (face, embedding) in enumerate(zip(faces, embeddings)):
                # Check for similar faces
                similar_person = db.find_similar_face(embedding, owner_id)
                
                # Save face embedding
                face_id = db.save_face_embedding(
                    media_id=media_id,
                    embedding=embedding.tolist(),
                    bbox=face,
                    person_id=similar_person
                )
                
                if similar_person:
                    # Auto-link to existing person
                    db.link_photo_person(media_id, similar_person, face_id, confirmed=False)
                
                face_count += 1
            
            # Step 4: Update analysis result
            db.update_analysis_complete(
                media_id=media_id,
                face_count=face_count,
                taken_at=exif_data.get('taken_at'),
                latitude=exif_data.get('latitude'),
                longitude=exif_data.get('longitude'),
                camera_make=exif_data.get('camera_make'),
                camera_model=exif_data.get('camera_model')
            )
            
            # Publish completion event
            redis_client.publish(CHANNEL_PHOTO_ANALYZED, json.dumps({
                'mediaId': media_id,
                'status': 'DONE',
                'faceCount': face_count
            }))
            
            print(f"[AI Worker] Completed: {media_id}, faces: {face_count}")
            
        except Exception as e:
            print(f"[AI Worker] Error: {e}")
            if 'media_id' in locals():
                db.update_analysis_error(media_id, str(e))

if __name__ == '__main__':
    main()
