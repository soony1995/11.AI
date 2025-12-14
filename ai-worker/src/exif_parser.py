"""
EXIF Parser - Extract metadata from images
"""
import io
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


class ExifParser:
    def parse(self, image_bytes: bytes) -> dict:
        """
        Parse EXIF data from image
        Returns: {
            'taken_at': datetime,
            'latitude': float,
            'longitude': float,
            'camera_make': str,
            'camera_model': str
        }
        """
        result = {
            'taken_at': None,
            'latitude': None,
            'longitude': None,
            'camera_make': None,
            'camera_model': None
        }
        
        try:
            image = Image.open(io.BytesIO(image_bytes))
            exif_data = image._getexif()
            
            if not exif_data:
                return result
            
            exif = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                exif[tag] = value
            
            # Parse date
            date_str = exif.get('DateTimeOriginal') or exif.get('DateTime')
            if date_str:
                try:
                    result['taken_at'] = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                except ValueError:
                    pass
            
            # Parse camera info
            result['camera_make'] = exif.get('Make')
            result['camera_model'] = exif.get('Model')
            
            # Parse GPS
            gps_info = exif.get('GPSInfo')
            if gps_info:
                gps = {}
                for key, val in gps_info.items():
                    tag = GPSTAGS.get(key, key)
                    gps[tag] = val
                
                lat = self._convert_to_degrees(gps.get('GPSLatitude'))
                lon = self._convert_to_degrees(gps.get('GPSLongitude'))
                
                if lat and lon:
                    if gps.get('GPSLatitudeRef') == 'S':
                        lat = -lat
                    if gps.get('GPSLongitudeRef') == 'W':
                        lon = -lon
                    
                    result['latitude'] = lat
                    result['longitude'] = lon
                    
        except Exception as e:
            print(f"[ExifParser] Error parsing EXIF: {e}")
        
        return result
    
    def _convert_to_degrees(self, value) -> float | None:
        """Convert GPS coordinates to degrees"""
        if not value:
            return None
        
        try:
            d = float(value[0])
            m = float(value[1])
            s = float(value[2])
            return d + (m / 60.0) + (s / 3600.0)
        except (IndexError, TypeError, ValueError):
            return None
