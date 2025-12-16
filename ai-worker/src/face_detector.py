"""
Face Detection and Embedding using face_recognition library
"""
import io
import os
import face_recognition
import numpy as np
from PIL import Image
from PIL import ImageOps


class FaceDetector:
    def __init__(self, model: str = 'hog'):
        """
        Initialize face detector
        Args:
            model: 'hog' (faster, less accurate) or 'cnn' (slower, more accurate)
        """
        self.model = os.getenv('FACE_MODEL', model)
        self.upsample = int(os.getenv('FACE_UPSAMPLE', '1'))
        if self.upsample < 0:
            self.upsample = 0
    
    def detect_faces(self, image_bytes: bytes) -> list[dict]:
        """
        Detect faces in image and return bounding boxes
        Returns: List of {'x': int, 'y': int, 'width': int, 'height': int}
        """
        image = self._load_image(image_bytes)
        
        # face_recognition returns (top, right, bottom, left)
        face_locations = face_recognition.face_locations(
            image,
            number_of_times_to_upsample=self.upsample,
            model=self.model,
        )
        
        faces = []
        for (top, right, bottom, left) in face_locations:
            faces.append({
                'x': left,
                'y': top,
                'width': right - left,
                'height': bottom - top
            })
        
        return faces
    
    def detect_faces_and_embeddings(self, image_bytes: bytes) -> tuple[list[dict], list[np.ndarray]]:
        """
        Detect faces and compute embeddings using a single face_locations pass.
        Returns: (faces, embeddings)
        """
        image = self._load_image(image_bytes)

        face_locations = face_recognition.face_locations(
            image,
            number_of_times_to_upsample=self.upsample,
            model=self.model,
        )

        faces: list[dict] = []
        for (top, right, bottom, left) in face_locations:
            faces.append({
                'x': left,
                'y': top,
                'width': right - left,
                'height': bottom - top
            })

        embeddings = face_recognition.face_encodings(image, face_locations)
        return faces, embeddings

    def get_embeddings(self, image_bytes: bytes) -> list[np.ndarray]:
        """
        Get face embeddings (128-dimensional vectors)
        Returns: List of numpy arrays, one per face
        """
        image = self._load_image(image_bytes)
        
        face_locations = face_recognition.face_locations(
            image,
            number_of_times_to_upsample=self.upsample,
            model=self.model,
        )
        embeddings = face_recognition.face_encodings(image, face_locations)
        
        return embeddings
    
    def compare_faces(self, known_embedding: np.ndarray, unknown_embedding: np.ndarray, 
                      tolerance: float = 0.6) -> tuple[bool, float]:
        """
        Compare two face embeddings
        Returns: (is_match, distance)
        """
        distance = np.linalg.norm(known_embedding - unknown_embedding)
        is_match = distance <= tolerance
        return is_match, float(distance)
    
    def _load_image(self, image_bytes: bytes) -> np.ndarray:
        """Load image bytes into numpy array"""
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert('RGB')
        return np.array(image)
