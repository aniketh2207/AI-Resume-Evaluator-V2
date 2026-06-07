import os
import tempfile
import shutil
from bson import ObjectId
from fastapi import APIRouter, UploadFile, File, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

# Import config and services
from app.core.config import jobs_collection, candidates_collection, fast_llm
from app.services.gcs_service import upload_resume_to_gcs
from app.services.ai_pipeline import (
    process_candidate_pipeline, jd_evaluator_node, communicator_node
)
from app.utils.extractor import read_document_content, extract_jd_data

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])
job_router = APIRouter(prefix="/api/job", tags=["Jobs"])

# Run startup migration to ensure all existing jobs have a status field
try:
    result = jobs_collection.update_many({"status": {"$exists": False}}, {"$set": {"status": "active"}})
    if result.modified_count > 0:
        print(f"[Migration] Updated {result.modified_count} existing jobs to 'active' status.")
except Exception as migration_err:
    print(f"[Migration] Failed to run existing jobs status migration: {migration_err}")

@router.get("")
def get_all_jobs():
    """Fetch all stored job roles/folders."""
    jobs = []
    cursor = jobs_collection.find({})
    for document in cursor:
        document["_id"] = str(document["_id"])
        # Ensure status is populated in return payload even if migration skipped it
        if "status" not in document:
            document["status"] = "active"
        jobs.append(document)
    return {"jobs": jobs}

@router.post("")
def create_job(payload: dict):
    """Create a new job role folder."""
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Job role name is required.")
    
    job_doc = {
        "name": name,
        "jd_filename": None,
        "jd_text": None,
        "status": "active"
    }
    inserted = jobs_collection.insert_one(job_doc)
    job_doc["_id"] = str(inserted.inserted_id)
    return job_doc

@router.patch("/{job_id}/status")
def update_job_status(job_id: str, payload: dict):
    """Update job status (e.g. 'active' or 'inactive')."""
    try:
        status = payload.get("status")
        if not status:
            raise HTTPException(status_code=400, detail="Status is required.")
        status = status.lower()
        if status not in ["active", "inactive"]:
            raise HTTPException(status_code=400, detail="Invalid status type. Must be 'active' or 'inactive'.")
            
        result = jobs_collection.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": status}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Job Role folder not found.")
            
        return {"status": "success", "job_status": status}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{job_id}/jd")
def upload_job_jd(job_id: str, jd: UploadFile = File(...)):
    """Upload or update a Job Description for a specific Job Role folder."""
    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Job ID format.")
        
    if not job:
        raise HTTPException(status_code=404, detail="Job Role folder not found.")
        
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(jd.filename)[1]) as temp_jd:
            temp_jd.write(jd.file.read())
            jd_path = temp_jd.name
            
        print("Extracting text from uploaded JD...")
        jd_text = read_document_content(fast_llm, jd_path)
        os.remove(jd_path)
        
        # Extract skills and eligibility criteria automatically on upload
        skills = []
        grad_years = []
        min_gpa = None
        other_criteria = None
        try:
            print("Running structured skill and eligibility extraction on job description...")
            extracted = extract_jd_data(fast_llm, jd_text)
            skills = [{"name": s.name, "weight": s.weight} for s in extracted.skills]
            
            # Normalize to sum exactly to 100 if needed
            weight_sum = sum(s["weight"] for s in skills)
            if weight_sum != 100 and len(skills) > 0:
                print(f"Extraction returned weights summing to {weight_sum}. Recalculating equal weights.")
                n = len(skills)
                base = 100 // n
                rem = 100 % n
                for i, s in enumerate(skills):
                    s["weight"] = base + (rem if i == 0 else 0)
            
            grad_years = extracted.required_graduation_years
            min_gpa = extracted.minimum_gpa
            other_criteria = extracted.other_eligibility_criteria
        except Exception as ext_err:
            print(f"JD extraction failed, using fallback: {str(ext_err)}")
            skills = []
            
        jobs_collection.update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "jd_filename": jd.filename, 
                    "jd_text": jd_text, 
                    "skills": skills,
                    "required_graduation_years": grad_years,
                    "minimum_gpa": min_gpa,
                    "other_eligibility_criteria": other_criteria
                }
            }
        )
        return {
            "status": "success", 
            "jd_filename": jd.filename, 
            "skills": skills,
            "required_graduation_years": grad_years,
            "minimum_gpa": min_gpa,
            "other_eligibility_criteria": other_criteria
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process Job Description: {str(e)}")

@router.put("/{job_id}/skills")
def update_job_skills(job_id: str, payload: dict):
    """Update configured skills, weights, and eligibility requirements for a job description."""
    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Job ID format.")
        
    if not job:
        raise HTTPException(status_code=404, detail="Job Role folder not found.")
        
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise HTTPException(status_code=400, detail="Skills must be a list.")
        
    total_weight = 0
    formatted_skills = []
    for s in skills:
        if not isinstance(s, dict) or "name" not in s or "weight" not in s:
            raise HTTPException(status_code=400, detail="Each skill must have a 'name' and 'weight'.")
        try:
            w = int(s["weight"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Skill weight must be an integer.")
            
        formatted_skills.append({
            "name": str(s["name"]),
            "weight": w
        })
        total_weight += w
        
    if total_weight != 100:
        raise HTTPException(status_code=400, detail=f"Total weights must sum to exactly 100. Current sum: {total_weight}%")
        
    grad_years = payload.get("required_graduation_years")
    min_gpa = payload.get("minimum_gpa")
    other_criteria = payload.get("other_eligibility_criteria")
    
    update_fields = {"skills": formatted_skills}
    
    if grad_years is not None:
        if not isinstance(grad_years, list):
            raise HTTPException(status_code=400, detail="required_graduation_years must be a list of integers.")
        try:
            grad_years = [int(y) for y in grad_years]
        except ValueError:
            raise HTTPException(status_code=400, detail="Each graduation year must be an integer.")
        update_fields["required_graduation_years"] = grad_years
        
    if min_gpa is not None:
        if min_gpa == "" or min_gpa == "null" or min_gpa == "None":
            update_fields["minimum_gpa"] = None
        else:
            try:
                update_fields["minimum_gpa"] = float(min_gpa)
            except ValueError:
                raise HTTPException(status_code=400, detail="minimum_gpa must be a number.")
    elif "minimum_gpa" in payload:
        update_fields["minimum_gpa"] = None
        
    if other_criteria is not None:
        update_fields["other_eligibility_criteria"] = str(other_criteria) if other_criteria else None
    elif "other_eligibility_criteria" in payload:
        update_fields["other_eligibility_criteria"] = None

    jobs_collection.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": update_fields}
    )
    
    # Re-evaluate all candidates under this job_id using updated criteria
    jd_text = job.get("jd_text")
    if jd_text:
        candidates = list(candidates_collection.find({"job_id": job_id}))
        print(f"Triggering re-evaluation for {len(candidates)} candidates under job {job_id}...")
        
        # Check if eligibility criteria exist in the job description
        has_eligibility = bool(
            update_fields.get("required_graduation_years") or 
            update_fields.get("minimum_gpa") is not None or 
            update_fields.get("other_eligibility_criteria")
        )
        criteria = {
            "required_graduation_years": update_fields.get("required_graduation_years", []),
            "minimum_gpa": update_fields.get("minimum_gpa"),
            "other_eligibility_criteria": update_fields.get("other_eligibility_criteria")
        }
        
        from google.cloud import storage
        from app.utils.extractor import check_candidate_eligibility
        from app.services.ai_pipeline import ats_workflow
        
        for cand in candidates:
            try:
                print(f"Re-evaluating candidate: {cand.get('name')} (ID: {cand.get('_id')})...")
                
                resume_gcs_uri = cand.get("resume_gcs_uri")
                is_eligible = True
                eligibility_reason = ""
                resume_text = ""
                
                # Run eligibility check if criteria are set and we have the resume GCS URI
                if has_eligibility and resume_gcs_uri:
                    try:
                        print(f"Downloading resume for eligibility pre-screen: {resume_gcs_uri}...")
                        parts = resume_gcs_uri[5:].split("/", 1)
                        bucket_name, blob_name = parts[0], parts[1]
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                            temp_path = temp_file.name
                        try:
                            storage_client = storage.Client()
                            bucket = storage_client.bucket(bucket_name)
                            blob = bucket.blob(blob_name)
                            blob.download_to_filename(temp_path)
                            
                            resume_text = read_document_content(fast_llm, temp_path)
                        finally:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                                
                        eligibility = check_candidate_eligibility(fast_llm, resume_text, criteria)
                        is_eligible = eligibility.is_eligible
                        eligibility_reason = eligibility.reason
                        print(f"Eligibility pre-screen result for {cand.get('name')}: eligible={is_eligible}, reason: {eligibility_reason}")
                    except Exception as gcs_err:
                        print(f"Failed to check eligibility for {cand.get('name')}: {gcs_err}")
                
                if not is_eligible:
                    # Short-circuit ineligible candidate
                    print(f"Candidate {cand.get('name')} failed eligibility check. Rejecting.")
                    update_fields_cand = {
                        "miscellaneous_details": "Skipped due to eligibility filter.",
                        "project_verification": "Skipped: Candidate did not meet basic job eligibility requirements.",
                        "score": 0,
                        "reasoning": f"AUTOMATIC PRE-SCREENING REJECTION:\n\nCandidate failed eligibility rules:\n{eligibility_reason}",
                        "ats_reasoning_summary": "Failed basic eligibility pre-screening.",
                        "jd_score": 0,
                        "jd_reasoning": f"AUTOMATIC PRE-SCREENING REJECTION:\n\nCandidate failed eligibility rules:\n{eligibility_reason}",
                        "jd_reasoning_summary": "Failed basic eligibility pre-screening.",
                        "final_weighted_score": 0.0,
                        "final_decision": "rejected",
                        "candidate_email": f"Dear {cand.get('name', 'Candidate')},\n\nThank you for your interest in our job role. After reviewing your profile, we have determined that you do not meet the minimum eligibility requirements specified for this position. Therefore, we will not be moving forward with your application at this time.\n\nBest regards,\nHR Recruiting Team",
                        "hiring_manager_brief": f"Candidate failed eligibility check: {eligibility_reason}. Evaluation bypassed to save pipeline usage.",
                        "interview_questions": []
                    }
                    candidates_collection.update_one(
                        {"_id": cand["_id"]},
                        {"$set": update_fields_cand}
                    )
                    continue

                # Candidate is eligible. Check if previous node results are null/missing
                is_profile_missing = not cand.get("education") or cand.get("github_data") is None or cand.get("score") is None
                
                if is_profile_missing:
                    print(f"Candidate {cand.get('name')} is missing profile outputs. Downloading resume and running full pipeline...")
                    
                    if not resume_text and resume_gcs_uri:
                        try:
                            parts = resume_gcs_uri[5:].split("/", 1)
                            bucket_name, blob_name = parts[0], parts[1]
                            
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                                temp_path = temp_file.name
                            try:
                                storage_client = storage.Client()
                                bucket = storage_client.bucket(bucket_name)
                                blob = bucket.blob(blob_name)
                                blob.download_to_filename(temp_path)
                                
                                resume_text = read_document_content(fast_llm, temp_path)
                            finally:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)
                        except Exception as dl_err:
                            print(f"Failed to download resume for full pipeline of {cand.get('name')}: {dl_err}")
                            
                    if not resume_text:
                        print(f"Skipping re-evaluation for {cand.get('name')} as resume text could not be extracted.")
                        continue
                        
                    state = {
                        "raw_resume": resume_text,
                        "jd_text": jd_text,
                        "matrix_path": os.path.join("data", "Profile Completion&Strength.xlsx"), 
                        "job_id": job_id,
                        "name": cand.get("name"), 
                        "github_username": cand.get("github_username"), 
                        "email": cand.get("email"), 
                        "phone": cand.get("phone"),
                        "category": None, "education": None, "experience": None, "projects": None,
                        "skills": None, "certifications": None, "miscellaneous_details": None,
                        "github_data": None, "project_verification": None, "score": None,
                        "reasoning": None, "ats_reasoning_summary": None, "jd_score": None, "jd_reasoning": None, "jd_reasoning_summary": None,
                        "final_weighted_score": None, "final_decision": None,
                        "candidate_email": None, "hiring_manager_brief": None, "interview_questions": None,
                        "resume_filename": cand.get("resume_filename"),
                        "resume_gcs_uri": resume_gcs_uri
                    }
                    
                    final_state = ats_workflow.invoke(state)
                    final_state.pop("raw_resume", None)
                    final_state.pop("jd_text", None)
                    if job_id:
                        final_state["job_id"] = job_id
                        
                    candidates_collection.update_one({"_id": cand["_id"]}, {"$set": final_state})
                    print(f"Full pipeline re-evaluation complete for candidate {cand.get('name')}. New Score: {final_state.get('final_weighted_score')}")
                    
                else:
                    # Previous node results exist. Only run jd_evaluator and communicator nodes.
                    print(f"Running jd_evaluator and communicator nodes for candidate: {cand.get('name')}...")
                    
                    ats_summary = cand.get("ats_reasoning_summary")
                    if not ats_summary or str(ats_summary).strip() == "" or ats_summary == "Assessment failed.":
                        reasoning_text = cand.get("reasoning", "")
                        if reasoning_text:
                            print(f"ats_reasoning_summary is missing for {cand.get('name')}. Generating fallback summary using LLM...")
                            try:
                                explanation = reasoning_text.split("=== DETAILED MATRIX CALCULATIONS ===")[0].strip()
                                messages = [
                                    SystemMessage(content="You are a professional technical recruiter. Summarize the following candidate evaluation explanation into a concise 1-2 sentence high-level summary explaining why they got their score (pointing out major strengths or deductions). Keep it clear and direct for a hover tooltip. Do not include detailed calculations or math."),
                                    HumanMessage(content=explanation)
                                ]
                                res = fast_llm.invoke(messages)
                                if isinstance(res.content, list):
                                    ats_summary = "".join([part.get("text", "") if isinstance(part, dict) else str(part) for part in res.content]).strip()
                                else:
                                    ats_summary = str(res.content).strip()
                            except Exception as sum_err:
                                print(f"Failed to generate fallback summary for {cand.get('name')}: {sum_err}")
                                explanation = reasoning_text.split("=== DETAILED MATRIX CALCULATIONS ===")[0].strip()
                                sentences = [s.strip() for s in explanation.split(".") if s.strip()]
                                ats_summary = ". ".join(sentences[:2]) + "." if sentences else "No reasoning summary available."
                        else:
                            ats_summary = "No reasoning summary available."
                            
                    eval_state = {
                        "raw_resume": "",
                        "jd_text": jd_text,
                        "matrix_path": None,
                        "job_id": job_id,
                        "name": cand.get("name"),
                        "github_username": cand.get("github_username"),
                        "email": cand.get("email"),
                        "phone": cand.get("phone"),
                        "category": cand.get("category"),
                        "education": cand.get("education"),
                        "experience": cand.get("experience"),
                        "projects": cand.get("projects"),
                        "skills": cand.get("skills"),
                        "certifications": cand.get("certifications"),
                        "github_project_links": cand.get("github_project_links", []),
                        "miscellaneous_details": cand.get("miscellaneous_details"),
                        "github_data": cand.get("github_data"),
                        "project_verification": cand.get("project_verification"),
                        "score": cand.get("score"),
                        "reasoning": cand.get("reasoning"),
                        "ats_reasoning_summary": ats_summary,
                        "resume_filename": cand.get("resume_filename"),
                        "resume_gcs_uri": resume_gcs_uri
                    }
                    
                    jd_res = jd_evaluator_node(eval_state)
                    eval_state.update(jd_res)
                    
                    comm_res = communicator_node(eval_state)
                    eval_state.update(comm_res)
                    
                    update_fields_cand = {
                        "jd_score": eval_state.get("jd_score"),
                        "jd_reasoning": eval_state.get("jd_reasoning"),
                        "jd_reasoning_summary": eval_state.get("jd_reasoning_summary"),
                        "final_weighted_score": eval_state.get("final_weighted_score"),
                        "final_decision": eval_state.get("final_decision"),
                        "candidate_email": eval_state.get("candidate_email"),
                        "hiring_manager_brief": eval_state.get("hiring_manager_brief"),
                        "interview_questions": eval_state.get("interview_questions")
                    }
                    if ats_summary:
                        update_fields_cand["ats_reasoning_summary"] = ats_summary
                        
                    candidates_collection.update_one(
                        {"_id": cand["_id"]},
                        {"$set": update_fields_cand}
                    )
                    print(f"Re-evaluation complete for candidate {cand.get('name')}. New Score: {eval_state.get('final_weighted_score')}")
            except Exception as eval_err:
                print(f"Error re-evaluating candidate {cand.get('name')}: {eval_err}")
                
    response_data = {"status": "success", "skills": formatted_skills}
    response_data.update({k: v for k, v in update_fields.items() if k != "skills"})
    return response_data

@router.post("/{job_id}/evaluate")
def evaluate_candidate_for_job(job_id: str, resume: UploadFile = File(...)):
    """Evaluate a candidate CV within a specific Job Role context using its stored JD."""
    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Job ID format.")
        
    if not job:
        raise HTTPException(status_code=404, detail="Job Role folder not found.")
        
    if job.get("status", "active") != "active":
        raise HTTPException(status_code=400, detail="Cannot evaluate resume. This job is currently inactive.")
        
    if not job.get("jd_text"):
        raise HTTPException(status_code=400, detail="Please upload a Job Description (JD) for this role folder first.")
        
    print(f"Received manual request for Job Role={job['name']}: Resume={resume.filename}")
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(resume.filename)[1]) as temp_resume:
            temp_resume.write(resume.file.read())
            resume_path = temp_resume.name
            
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt", encoding="utf-8") as temp_jd:
            temp_jd.write(job["jd_text"])
            jd_path = temp_jd.name

        # Upload file to GCS
        gcs_uri = upload_resume_to_gcs(resume_path, "manual", job_id)
        
        final_state = process_candidate_pipeline(
            resume_path=resume_path, 
            jd_path=jd_path, 
            job_id=job_id, 
            resume_gcs_uri=gcs_uri
        )

        os.remove(resume_path)
        os.remove(jd_path)
        
        return final_state
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline evaluation failed: {str(e)}")

@router.post("/{job_id}/evaluate-batch")
def evaluate_candidates_from_drive(job_id: str):
    """Fetch unprocessed candidate resumes from Google Drive, process them, and move them to processed folder."""
    from app.services.drive_service import fetch_unprocessed_resumes, move_to_processed, resolve_job_folders

    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Job ID format.")
        
    if not job:
        raise HTTPException(status_code=404, detail="Job Role folder not found.")
        
    if job.get("status", "active") != "active":
        raise HTTPException(status_code=400, detail="Cannot evaluate resumes. This job is currently inactive.")
        
    try:
        folder_ids = resolve_job_folders(job["name"])
        unproc_id = folder_ids["unprocessed_id"]
        proc_id = folder_ids["processed_id"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if not job.get("jd_text"):
        raise HTTPException(status_code=400, detail="Please upload a Job Description (JD) for this role folder first.")

    print(f"Triggering Google Drive Batch Evaluation for Job Role={job['name']} (ID: {job_id})")
    
    try:
        resumes = fetch_unprocessed_resumes(unproc_id)
        if not resumes:
            return {"status": "success", "processed_count": 0, "message": "No new resumes found in Google Drive."}
            
        processed_count = 0
        for resume in resumes:
            resume_path = None
            jd_path = None
            try:
                # Write in-memory bytes to temporary file for LangGraph parser
                suffix = os.path.splitext(resume["file_name"])[1] or ".pdf"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_resume:
                    temp_resume.write(resume["pdf_bytes"])
                    resume_path = temp_resume.name
                    
                with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt", encoding="utf-8") as temp_jd:
                    temp_jd.write(job["jd_text"])
                    jd_path = temp_jd.name
                
                # Upload to GCS
                gcs_uri = upload_resume_to_gcs(resume_path, "drive_batch", job_id)
                
                # Evaluate candidate
                process_candidate_pipeline(
                    resume_path=resume_path,
                    jd_path=jd_path,
                    job_id=job_id,
                    resume_gcs_uri=gcs_uri
                )
                
                # Move Google Drive file to processed folder
                move_to_processed(resume["file_id"], unproc_id, proc_id)
                processed_count += 1
                
            except Exception as item_err:
                print(f"Error evaluating candidate resume '{resume.get('file_name')}': {item_err}")
            finally:
                if resume_path and os.path.exists(resume_path):
                    os.remove(resume_path)
                if jd_path and os.path.exists(jd_path):
                    os.remove(jd_path)
                    
        return {
            "status": "success",
            "processed_count": processed_count,
            "message": f"Successfully evaluated {processed_count} resumes from Google Drive."
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch evaluation failed: {str(e)}")

# Singular delete endpoint to match '/api/job/{job_id}' path from frontend
@job_router.delete("/{job_id}")
def delete_job(job_id: str):
    try:
        result = jobs_collection.delete_one({"_id": ObjectId(job_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Job Role not found.")
        
        # Also clean up all candidates belonging to this job
        candidates_collection.delete_many({"job_id": job_id})
        
        return {"status": "success"}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
