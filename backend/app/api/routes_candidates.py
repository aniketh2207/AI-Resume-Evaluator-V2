import os
import tempfile
import datetime
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse
from google.cloud import storage

# Import config, GCS, pipeline
from app.core.config import candidates_collection
from app.services.gcs_service import upload_resume_to_gcs
from app.services.ai_pipeline import process_candidate_pipeline

router = APIRouter(prefix="/api/candidates", tags=["Candidates"])
legacy_router = APIRouter(tags=["Legacy"])

@router.get("")
def get_all_candidates(job_id: Optional[str] = None):
    """Fetch all stored candidates, optionally filtered by Job Role ID."""
    candidates = []
    query = {}
    if job_id:
        query["job_id"] = job_id
    cursor = candidates_collection.find(query)
    for document in cursor:
        document["_id"] = str(document["_id"])
        candidates.append(document)
    return {"candidates": candidates}

@router.get("/{candidate_id}/resume")
def get_candidate_resume(candidate_id: str):
    """Serve the GCS private PDF file of a candidate using a temporary V4 Signed URL redirect."""
    try:
        cand = candidates_collection.find_one({"_id": ObjectId(candidate_id)})
        if not cand:
            raise HTTPException(status_code=404, detail="Candidate not found")
        
        resume_gcs_uri = cand.get("resume_gcs_uri")
        if not resume_gcs_uri:
            raise HTTPException(status_code=404, detail="Resume GCS URI is missing for this candidate")
            
        # Parse gs:// URI into bucket and blob name
        if not resume_gcs_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="Invalid GCS URI format stored in DB")
            
        parts = resume_gcs_uri[5:].split("/", 1)
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="Invalid GCS URI format stored in DB")
            
        bucket_name, blob_name = parts[0], parts[1]
        
        # Connect to GCS client and generate V4 Signed URL
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="GET"
        )
        
        return RedirectResponse(url=signed_url)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{candidate_id}")
def update_candidate_status(candidate_id: str, payload: dict):
    """Update candidate properties like final_decision status."""
    try:
        decision = payload.get("final_decision")
        if not decision:
            raise HTTPException(status_code=400, detail="final_decision status is required.")
        
        decision = decision.lower()
        if decision not in ["inprogress", "shortlisted", "selected", "rejected"]:
            raise HTTPException(status_code=400, detail="Invalid status type.")
            
        result = candidates_collection.update_one(
            {"_id": ObjectId(candidate_id)},
            {"$set": {"final_decision": decision}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Candidate not found.")
            
        return {"status": "success", "final_decision": decision}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{candidate_id}")
def delete_candidate(candidate_id: str):
    """Delete candidate from MongoDB and clean up their resume in GCS if applicable."""
    try:
        cand = candidates_collection.find_one({"_id": ObjectId(candidate_id)})
        if not cand:
            raise HTTPException(status_code=404, detail="Candidate not found")
            
        # Clean up GCS resume if present
        resume_gcs_uri = cand.get("resume_gcs_uri")
        if resume_gcs_uri and resume_gcs_uri.startswith("gs://"):
            try:
                parts = resume_gcs_uri[5:].split("/", 1)
                if len(parts) == 2:
                    bucket_name, blob_name = parts[0], parts[1]
                    storage_client = storage.Client()
                    bucket = storage_client.bucket(bucket_name)
                    blob = bucket.blob(blob_name)
                    blob.delete()
                    print(f"Deleted GCS file: {resume_gcs_uri}")
            except Exception as gcs_err:
                print(f"Failed to delete GCS file {resume_gcs_uri}: {gcs_err}")

        # Delete from MongoDB
        result = candidates_collection.delete_one({"_id": ObjectId(candidate_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Candidate not found in database")
            
        return {"status": "success", "message": f"Candidate {candidate_id} deleted successfully"}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@legacy_router.post("/api/evaluate")
def evaluate_candidate_endpoint(
    resume: UploadFile = File(description="The candidate's resume (PDF/DOCX)"),
    jd: UploadFile = File(description="The job description (PDF/DOCX)")
):
    print(f"Received manual request: Resume={resume.filename}, JD={jd.filename}")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(resume.filename)[1]) as temp_resume:
            temp_resume.write(resume.file.read())
            resume_path = temp_resume.name
            
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(jd.filename)[1]) as temp_jd:
            temp_jd.write(jd.file.read())
            jd_path = temp_jd.name

        gcs_uri = upload_resume_to_gcs(resume_path, "manual", "legacy_evaluate")
        final_state = process_candidate_pipeline(
            resume_path=resume_path, 
            jd_path=jd_path, 
            resume_gcs_uri=gcs_uri
        )

        os.remove(resume_path)
        os.remove(jd_path)
        
        return final_state

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")
