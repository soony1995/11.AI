"""
Storage Client - Download images from MinIO/S3
"""
import os
import boto3
from botocore.client import Config


class StorageClient:
    def __init__(self):
        self.endpoint = os.getenv('MINIO_ENDPOINT', 'http://localhost:9000')
        self.access_key = os.getenv('MINIO_ACCESS_KEY', 'minio')
        self.secret_key = os.getenv('MINIO_SECRET_KEY', 'minio123')
        self.bucket = os.getenv('MINIO_BUCKET', 'media-uploads')
        
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1'
        )
    
    def download(self, key: str) -> bytes:
        """Download object from storage"""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response['Body'].read()
