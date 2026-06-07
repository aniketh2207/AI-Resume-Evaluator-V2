import os
import uuid
from google.cloud import storage

def upload_resume_to_gcs(local_file_path: str, candidate_email: str, job_id: str) -> str:
    """Uploads candidate resume PDF from local temp path to Google Cloud Storage bucket."""
    bucket_name = "ats-candidate-resumes-498012"
    
    # Generate unique clean filename: job_id/candidate_email_uuid.pdf
    email_clean = "".join(c for c in candidate_email if c.isalnum() or c in ".-_@")
    email_clean = email_clean.replace("@", "_at_").lower().strip()
    
    unique_id = uuid.uuid4().hex
    blob_name = f"{job_id}/{email_clean}_{unique_id}.pdf"
    
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        # Upload the file to GCS bucket
        blob.upload_from_filename(local_file_path, content_type="application/pdf")
        
        gcs_uri = f"gs://{bucket_name}/{blob_name}"
        print(f"Successfully uploaded resume to GCS: {gcs_uri}")
        return gcs_uri
    except Exception as e:
        print(f"Error uploading resume to GCS: {e}")
        return ""
