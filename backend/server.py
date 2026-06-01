import os
import tempfile
import json
import base64
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pymongo import MongoClient
from bson import ObjectId
from google.cloud import pubsub_v1
from contextlib import asynccontextmanager

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

from main import app as ats_workflow, ATS_State, fast_llm
from extractor import read_document_content, extract_jd_data, check_candidate_eligibility

# --- Configuration ---
cloud_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "E:/AI-Resume-Evaluator-V2/backend/ai-resume-evaluator-498012-305d5547940c.json"
PROJECT_ID = "ai-resume-evaluator-498012"
SUBSCRIPTION_ID = "ats-local-worker"

# Initialize MongoDB
db_client = MongoClient(cloud_url)
db = db_client.ats_database
candidates_collection = db.candidates
jobs_collection = db.jobs

# ==========================================
# 1. SHARED CORE LOGIC
# ==========================================
def process_candidate_pipeline(resume_path: str, jd_path: str, job_id: Optional[str] = None):
    """Shared function to run the LangGraph pipeline and save to DB."""
    print("Extracting text from files...")
    resume_text = read_document_content(fast_llm, resume_path)
    jd_text = read_document_content(fast_llm, jd_path)

    # Check eligibility first if job details contain criteria
    job = None
    if job_id:
        try:
            job = jobs_collection.find_one({"_id": ObjectId(job_id)})
        except Exception as e:
            print(f"Error fetching job for eligibility pre-screen: {e}")

    if job and (job.get("required_graduation_years") or job.get("minimum_gpa") is not None or job.get("other_eligibility_criteria")):
        criteria = {
            "required_graduation_years": job.get("required_graduation_years", []),
            "minimum_gpa": job.get("minimum_gpa"),
            "other_eligibility_criteria": job.get("other_eligibility_criteria")
        }
        
        print("Checking candidate eligibility against JD requirements...")
        try:
            eligibility = check_candidate_eligibility(fast_llm, resume_text, criteria)
            print(f"Eligibility decision: {eligibility.is_eligible}. Reason: {eligibility.reason}")
            
            if not eligibility.is_eligible:
                print("Candidate is ineligible. Short-circuiting LangGraph pipeline evaluation!")
                
                # Fast name extraction
                candidate_name = "Candidate"
                try:
                    from pydantic import BaseModel, Field
                    class QuickName(BaseModel):
                        name: str = Field(description="The full name of the candidate")
                    name_extractor = fast_llm.with_structured_output(QuickName)
                    extracted_name = name_extractor.invoke(f"Extract the candidate's full name from their resume text:\n\n{resume_text[:1000]}")
                    candidate_name = extracted_name.name
                except Exception as name_err:
                    print(f"Failed to extract candidate name for short-circuited flow: {name_err}")
                
                final_state = {
                    "name": candidate_name,
                    "github_username": "N/A",
                    "email": "N/A",
                    "phone": "N/A",
                    "category": "student",
                    "education": [],
                    "experience": [],
                    "projects": [],
                    "skills": [],
                    "certifications": [],
                    "miscellaneous_details": "Skipped due to eligibility filter.",
                    "github_data": None,
                    "project_verification": "Skipped: Candidate did not meet basic job eligibility requirements.",
                    "score": 0,
                    "reasoning": f"AUTOMATIC PRE-SCREENING REJECTION:\n\nCandidate failed eligibility rules:\n{eligibility.reason}",
                    "jd_score": 0,
                    "jd_reasoning": f"AUTOMATIC PRE-SCREENING REJECTION:\n\nCandidate failed eligibility rules:\n{eligibility.reason}",
                    "final_weighted_score": 0.0,
                    "final_decision": "rejected",
                    "candidate_email": f"Dear {candidate_name},\n\nThank you for your interest in our job role. After reviewing your profile, we have determined that you do not meet the minimum eligibility requirements specified for this position. Therefore, we will not be moving forward with your application at this time.\n\nBest regards,\nHR Recruiting Team",
                    "hiring_manager_brief": f"Candidate failed eligibility check: {eligibility.reason}. Evaluation bypassed to save pipeline usage.",
                    "interview_questions": [],
                    "job_id": job_id
                }
                
                inserted_doc = candidates_collection.insert_one(final_state)
                final_state["_id"] = str(inserted_doc.inserted_id)
                return final_state
        except Exception as filter_err:
            print(f"Error during eligibility screening, continuing with full pipeline: {filter_err}")

    state: ATS_State = {
        "raw_resume": resume_text,
        "jd_text": jd_text,
        "matrix_path": "Profile Completion&Strength.xlsx", 
        "job_id": job_id,
        "name": None, "github_username": None, "email": None, "phone": None,
        "category": None, "education": None, "experience": None, "projects": None,
        "skills": None, "certifications": None, "miscellaneous_details": None,
        "github_data": None, "project_verification": None, "score": None,
        "reasoning": None, "jd_score": None, "jd_reasoning": None,
        "final_weighted_score": None, "final_decision": None,
        "candidate_email": None, "hiring_manager_brief": None, "interview_questions": None
    }

    print("Triggering LangGraph Multi-Agent Pipeline...")
    final_state = ats_workflow.invoke(state)

    final_state.pop("raw_resume", None)
    final_state.pop("jd_text", None)
    
    # Associate evaluation with a specific job role if provided
    if job_id:
        final_state["job_id"] = job_id
    
    inserted_doc = candidates_collection.insert_one(final_state)
    final_state["_id"] = str(inserted_doc.inserted_id)
    
    return final_state

# ==========================================
# GMAIL INGESTION HELPERS
# ==========================================
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service():
    """Gets Gmail client using saved token.json."""
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(backend_dir, 'token.json')
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            print(f"Error loading credentials from token.json: {e}")
    return None

def find_attachments(parts):
    """Recursively search for PDF/DOCX attachments in email message parts."""
    attachments = []
    for part in parts:
        filename = part.get('filename')
        body = part.get('body', {})
        attachment_id = body.get('attachmentId')
        
        if filename and attachment_id:
            ext = os.path.splitext(filename)[1].lower()
            if ext in ['.pdf', '.docx']:
                attachments.append({
                    'filename': filename,
                    'attachment_id': attachment_id
                })
        
        if part.get('parts'):
            attachments.extend(find_attachments(part['parts']))
            
    return attachments

def process_pubsub_message(message: pubsub_v1.subscriber.message.Message):
    print(f"\n🔔 New Email Event Detected! Message ID: {message.message_id}")
    
    try:
        payload = json.loads(message.data.decode("utf-8"))
        print(f"Gmail Payload: {json.dumps(payload, indent=2)}")
        
        history_id = payload.get("historyId")
        
        service = get_gmail_service()
        if not service:
            print("❌ Gmail service not initialized. token.json is missing or invalid.")
            message.ack()
            return
            
        # List the latest message
        results = service.users().messages().list(userId='me', maxResults=1).execute()
        messages = results.get('messages', [])
        if not messages:
            print("No recent messages found in Gmail.")
            message.ack()
            return
            
        msg_id = messages[0]['id']
        msg = service.users().messages().get(userId='me', id=msg_id).execute()
        
        payload_data = msg.get('payload', {})
        headers = payload_data.get('headers', [])
        
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Unknown Sender")
        
        parts = payload_data.get('parts', [])
        attachments = find_attachments(parts)
        
        if not attachments:
            print(f"No resume attachments (PDF/DOCX) found in email '{subject}' from {sender}.")
            message.ack()
            return
            
        target_attachment = attachments[0]
        print(f"Found candidate email from {sender} with attachment: {target_attachment['filename']}")
        
        # 1. Match email subject to a job in database
        all_jobs = list(jobs_collection.find({}))
        matched_job = None
        
        for job in all_jobs:
            job_name = job.get('name', '').lower().strip()
            if job_name in subject.lower() or subject.lower() in job_name:
                matched_job = job
                break
                
        if not matched_job:
            print(f"⚠️ Warning: No matching job role found in database for subject '{subject}'")
            if all_jobs:
                matched_job = all_jobs[0]
                print(f"👉 Falling back to first available job for evaluation: '{matched_job['name']}' (ID: {matched_job['_id']})")
            else:
                print("❌ ERROR: No job roles exist in the database at all.")
                message.ack()
                return
                
        if not matched_job.get("jd_text"):
            print(f"❌ ERROR: Job '{matched_job['name']}' has no Job Description text loaded.")
            message.ack()
            return
            
        # 2. Download the attachment file
        print(f"Downloading attachment '{target_attachment['filename']}'...")
        att_id = target_attachment['attachment_id']
        
        att_data = service.users().messages().attachments().get(
            userId='me', 
            messageId=msg_id, 
            id=att_id
        ).execute()
        
        file_data = base64.urlsafe_b64decode(att_data['data'].encode('UTF-8'))
        
        # 3. Save files to temp folders
        suffix = os.path.splitext(target_attachment['filename'])[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_resume:
            temp_resume.write(file_data)
            resume_path = temp_resume.name
            
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt", encoding="utf-8") as temp_jd:
            temp_jd.write(matched_job["jd_text"])
            jd_path = temp_jd.name
            
        # 4. Trigger evaluation pipeline
        try:
            print(f"🚀 Triggering Multi-Agent Evaluation Pipeline for candidate {sender}...")
            final_state = process_candidate_pipeline(
                resume_path=resume_path,
                jd_path=jd_path,
                job_id=str(matched_job["_id"])
            )
            print(f"🏆 Pipeline Run Successful. Candidate: {final_state.get('name')} | Final Decision: {final_state.get('final_decision')}")
        except Exception as eval_err:
            print(f"❌ Evaluation Pipeline Failed: {eval_err}")
        finally:
            if os.path.exists(resume_path):
                os.remove(resume_path)
            if os.path.exists(jd_path):
                os.remove(jd_path)
                
    except Exception as e:
        print(f"❌ Error processing message: {e}")
        
    message.ack() # Ensure Google deletes the notification from the queue

@asynccontextmanager
async def lifespan(app: FastAPI):
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
    
    print(f"🚀 Starting Pub/Sub worker on {SUBSCRIPTION_ID}...")
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_pubsub_message)
    
    yield
    
    print("Shutting down background worker...")
    streaming_pull_future.cancel()
    subscriber.close()

# ==========================================
# 3. FASTAPI ENDPOINTS
# ==========================================
api = FastAPI(title="AI ATS Evaluator API", lifespan=lifespan)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Job Role (Folder) Management -----------------

@api.get("/api/jobs")
def get_all_jobs():
    """Fetch all stored job roles/folders."""
    jobs = []
    cursor = jobs_collection.find({})
    for document in cursor:
        document["_id"] = str(document["_id"])
        jobs.append(document)
    return {"jobs": jobs}

@api.post("/api/jobs")
def create_job(payload: dict):
    """Create a new job role folder."""
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Job role name is required.")
    
    job_doc = {
        "name": name,
        "jd_filename": None,
        "jd_text": None
    }
    inserted = jobs_collection.insert_one(job_doc)
    job_doc["_id"] = str(inserted.inserted_id)
    return job_doc

@api.post("/api/jobs/{job_id}/jd")
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

@api.put("/api/jobs/{job_id}/skills")
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
    
    response_data = {"status": "success", "skills": formatted_skills}
    response_data.update({k: v for k, v in update_fields.items() if k != "skills"})
    return response_data

@api.post("/api/jobs/{job_id}/evaluate")
def evaluate_candidate_for_job(job_id: str, resume: UploadFile = File(...)):
    """Evaluate a candidate CV within a specific Job Role context using its stored JD."""
    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Job ID format.")
        
    if not job:
        raise HTTPException(status_code=404, detail="Job Role folder not found.")
        
    if not job.get("jd_text"):
        raise HTTPException(status_code=400, detail="Please upload a Job Description (JD) for this role folder first.")
        
    print(f"Received manual request for Job Role={job['name']}: Resume={resume.filename}")
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(resume.filename)[1]) as temp_resume:
            temp_resume.write(resume.file.read())
            resume_path = temp_resume.name
            
        # Store JD to temp file for read_document_content requirements if needed or pass string directly
        # Since process_candidate_pipeline requires two paths, we create a temporary file for the stored JD text
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt", encoding="utf-8") as temp_jd:
            temp_jd.write(job["jd_text"])
            jd_path = temp_jd.name

        # Trigger shared pipeline logic
        final_state = process_candidate_pipeline(resume_path, jd_path, job_id=job_id)

        os.remove(resume_path)
        os.remove(jd_path)
        
        return final_state
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline evaluation failed: {str(e)}")

# ----------------- Legacy General / Direct endpoints -----------------

@api.post("/api/evaluate")
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

        # Trigger the shared logic block
        final_state = process_candidate_pipeline(resume_path, jd_path)

        os.remove(resume_path)
        os.remove(jd_path)
        
        return final_state

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")

@api.get("/api/candidates")
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

@api.patch("/api/candidates/{candidate_id}")
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

if __name__ == "__main__":
    uvicorn.run("server:api", host="0.0.0.0", port=8000, reload=True)