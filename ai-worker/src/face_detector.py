"""
Face Detection and Embedding using face_recognition library
"""
import io
import face_recognition
import numpy as np
from PIL import Image


class FaceDetector:
    def __init__(self, model: str = 'hog'):
        """
        Initialize face detector
        Args:
            model: 'hog' (faster, less accurate) or 'cnn' (slower, more accurate)
        """
        self.model = model
    
    def detect_faces(self, image_bytes: bytes) -> list[dict]:
        """
        Detect faces in image and return bounding boxes
        Returns: List of {'x': int, 'y': int, 'width': int, 'height': int}
        """
        image = self._load_image(image_bytes)
        
        # face_recognition returns (top, right, bottom, left)
        face_locations = face_recognition.face_locations(image, model=self.model)
        
        faces = []
        for (top, right, bottom, left) in face_locations:
            faces.append({
                'x': left,
                'y': top,
                'width': right - left,
                'height': bottom - top
            })
        
        return faces
    
    def get_embeddings(self, image_bytes: bytes) -> list[np.ndarray]:
        """
        Get face embeddings (128-dimensional vectors)
        Returns: List of numpy arrays, one per face
        """
        image = self._load_image(image_bytes)
        
        face_locations = face_recognition.face_locations(image, model=self.model)
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
        return np.array(image)
