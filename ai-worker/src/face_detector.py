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
        self.max_dim = int(os.getenv('FACE_MAX_DIM', '1600'))
        if self.max_dim < 0:
            self.max_dim = 0
        self.fallback_model = os.getenv('FACE_FALLBACK_MODEL', 'hog')
    
    def detect_faces(self, image_bytes: bytes) -> list[dict]:
        """
        Detect faces in image and return bounding boxes
        Returns: List of {'x': int, 'y': int, 'width': int, 'height': int}
        """
        image, scale = self._prepare_image(image_bytes)
        
        # face_recognition returns (top, right, bottom, left)
        face_locations = self._safe_face_locations(image)
        
        faces = []
        for (top, right, bottom, left) in face_locations:
            left, top, right, bottom = self._to_original_coords(left, top, right, bottom, scale)
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
        image, scale = self._prepare_image(image_bytes)

        face_locations = self._safe_face_locations(image)

        faces: list[dict] = []
        for (top, right, bottom, left) in face_locations:
            left, top, right, bottom = self._to_original_coords(left, top, right, bottom, scale)
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
        image, _ = self._prepare_image(image_bytes)
        
        face_locations = self._safe_face_locations(image)
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
    
    def _prepare_image(self, image_bytes: bytes) -> tuple[np.ndarray, float]:
        """Load image bytes into numpy array with optional downscale."""
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert('RGB')
        original_width, original_height = image.size
        scale = 1.0
        if self.max_dim > 0:
            max_side = max(original_width, original_height)
            if max_side > self.max_dim:
                scale = self.max_dim / max_side
                resized_width = max(1, int(round(original_width * scale)))
                resized_height = max(1, int(round(original_height * scale)))
                image = image.resize((resized_width, resized_height), Image.LANCZOS)
        return np.array(image), scale

    def _safe_face_locations(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Detect faces with fallback to reduce failures on low-memory hosts."""
        try:
            return face_recognition.face_locations(
                image,
                number_of_times_to_upsample=self.upsample,
                model=self.model,
            )
        except Exception as error:
            if self.model == 'cnn' and self.fallback_model:
                print(f"[FaceDetector] cnn failed: {error}. Falling back to {self.fallback_model}.")
                return face_recognition.face_locations(
                    image,
                    number_of_times_to_upsample=max(0, self.upsample - 1),
                    model=self.fallback_model,
                )
            raise

    def _to_original_coords(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        scale: float,
    ) -> tuple[int, int, int, int]:
        """Map resized coords back to original image space."""
        if scale == 1.0:
            return left, top, right, bottom
        inv = 1.0 / scale
        return (
            int(round(left * inv)),
            int(round(top * inv)),
            int(round(right * inv)),
            int(round(bottom * inv)),
        )
