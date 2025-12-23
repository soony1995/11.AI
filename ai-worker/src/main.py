"""
AI Worker - Main entry point
Listens to Redis pub/sub for photo events and processes them
"""
import json
import redis
from .face_detector import FaceDetector
from .exif_parser import ExifParser
from .db import Database
from .storage import StorageClient
from .config import (
    AUTO_MATCH_DISTANCE_THRESHOLD,
    AUTO_MATCH_MIN_CONFIRMED,
    DATABASE_URL,
    PROCESSING_TIMEOUT_MINUTES,
    REDIS_URL,
)

# Redis channels
# 사진 업로드 이벤트 수신 채널
CHANNEL_PHOTO_UPLOADED = 'photo:uploaded'
# 사진 삭제 이벤트 수신 채널
CHANNEL_PHOTO_DELETED = 'photo:deleted'
# 분석 완료 이벤트 발행 채널
CHANNEL_PHOTO_ANALYZED = 'photo:analyzed'

def main():
    # 워커 시작 로그
    print("[AI Worker] Starting...")
    
    # 구성 요소 초기화 (Redis, DB, 스토리지, 얼굴 탐지, EXIF 파서)
    redis_client = redis.from_url(REDIS_URL)
    pubsub = redis_client.pubsub()
    db = Database(DATABASE_URL)
    storage = StorageClient()
    face_detector = FaceDetector()
    exif_parser = ExifParser()
    
    # 업로드/삭제 이벤트 채널 구독
    pubsub.subscribe(CHANNEL_PHOTO_UPLOADED, CHANNEL_PHOTO_DELETED)
    print(f"[AI Worker] Subscribed to {CHANNEL_PHOTO_UPLOADED}, {CHANNEL_PHOTO_DELETED}")
    
    # 시작 시 오래된 PROCESSING 레코드 정리
    db.mark_stale_processing(PROCESSING_TIMEOUT_MINUTES)

    # 메시지 루프: Redis pub/sub 스트림을 계속 대기/처리
    for message in pubsub.listen():
        # 구독 확인/핵심 이벤트 이외 메시지는 무시
        if message['type'] != 'message':
            continue
            
        try:
            # 새 메시지마다 오래된 PROCESSING 레코드 정리
            db.mark_stale_processing(PROCESSING_TIMEOUT_MINUTES)

            # 이벤트 payload 파싱
            payload = json.loads(message['data'])
            channel = message.get('channel')
            if isinstance(channel, bytes):
                channel = channel.decode()
            media_id = payload['id']
            owner_id = payload['ownerId']
            stored_key = payload['storedKey']

            if channel == CHANNEL_PHOTO_DELETED or payload.get('action') == 'deleted':
                print(f"[AI Worker] Deleting AI records: {media_id}")
                db.delete_media_records(media_id)
                continue

            print(f"[AI Worker] Processing: {media_id}")
            
            # 분석 레코드 생성 및 상태 갱신
            db.create_analysis(media_id, owner_id)
            db.update_analysis_status(media_id, 'PROCESSING')
            
            # 스토리지에서 원본 이미지를 다운로드
            image_bytes = storage.download(stored_key)
            
            # Step 1: EXIF 추출 (촬영 시간/위치/카메라 정보)
            exif_data = exif_parser.parse(image_bytes)
            
            # Step 2: 얼굴 검출 및 임베딩 생성
            faces, embeddings = face_detector.detect_faces_and_embeddings(image_bytes)
            
            # Step 3: 얼굴 임베딩 저장 + 기존 인물과 유사도 매칭
            face_count = 0
            for i, (face, embedding) in enumerate(zip(faces, embeddings)):
                # 유사 얼굴 탐색 (확정 샘플 수와 임계치 조건 만족 시 후보 반환)
                similar_person = db.find_similar_face(
                    embedding.tolist(),
                    owner_id,
                    distance_threshold=AUTO_MATCH_DISTANCE_THRESHOLD,
                    min_confirmed_samples=AUTO_MATCH_MIN_CONFIRMED,
                )
                
                # 얼굴 임베딩 저장 (아직 person_id는 확정되지 않음)
                face_id = db.save_face_embedding(
                    media_id=media_id,
                    embedding=embedding.tolist(),
                    bbox=face,
                    person_id=None
                )
                
                if similar_person:
                    # 유사 인물이 있으면 자동 연결 (confirmed=false)
                    db.link_photo_person(media_id, similar_person, face_id, confirmed=False)
                
                face_count += 1
            
            # Step 4: 분석 결과 업데이트 (얼굴 수 + EXIF 메타데이터)
            db.update_analysis_complete(
                media_id=media_id,
                face_count=face_count,
                taken_at=exif_data.get('taken_at'),
                latitude=exif_data.get('latitude'),
                longitude=exif_data.get('longitude'),
                camera_make=exif_data.get('camera_make'),
                camera_model=exif_data.get('camera_model')
            )
            
            # 분석 완료 이벤트 발행 (다운스트림 작업 트리거)
            redis_client.publish(CHANNEL_PHOTO_ANALYZED, json.dumps({
                'mediaId': media_id,
                'status': 'DONE',
                'faceCount': face_count
            }))
            
            print(f"[AI Worker] Completed: {media_id}, faces: {face_count}")
            
        except Exception as e:
            # 오류 발생 시 로그 출력 및 분석 상태를 에러로 기록
            print(f"[AI Worker] Error: {e}")
            if 'media_id' in locals():
                db.update_analysis_error(media_id, str(e))

if __name__ == '__main__':
    # 직접 실행 시 워커 진입
    main()
