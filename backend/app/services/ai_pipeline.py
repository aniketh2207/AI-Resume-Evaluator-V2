import os
import sys
import json
from bson import ObjectId
from typing import Optional, List
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
import time

# Import from core and models
from app.core.config import fast_llm, heavy_llm, candidates_collection, jobs_collection, backend_dir
from app.models.schemas import (
    ATS_State, SkillScore, JDFitResult, FinalDeliverables, 
    ProjectVerificationResult, ExtractedSkill, JDSkillsExtraction
)
from app.services.gcs_service import upload_resume_to_gcs

# Import utilities
from app.utils.extractor import extract_candidate_info, CandidateInfo, read_document_content, check_candidate_eligibility
from app.utils.tools import run_github_agent, GitHubReport
from app.utils.assessor import load_scoring_matrix, evaluate_candidate

def route_candidate(state: ATS_State):
    if state['category'] == "student":
        return "student"
    else:
        return "experienced"

def extractor_node(state: ATS_State):
    print("Extracting Candidate Info...")
    try:
        info: CandidateInfo = extract_candidate_info(fast_llm, state["raw_resume"])
        education_list = [edu.model_dump() for edu in info.education]
        experience_list = [exp.model_dump() for exp in info.experience]
        projects_list = [proj.model_dump() for proj in info.projects]
        github_project_links_list = [link.model_dump() for link in info.github_project_links] if info.github_project_links else []
        
        return {
            "name": info.name,
            "github_username": info.github_username,
            "email": info.email,
            "phone": info.phone,
            "category": info.category,
            "education": education_list,
            "experience": experience_list,
            "projects": projects_list,
            "skills": info.skills,
            "certifications": info.certifications,
            "github_project_links": github_project_links_list,
            "miscellaneous_details": info.miscellaneous_details
        }
    except Exception as e:
        print(f"Error during resume extraction: {str(e)}")
        return {
            "name": "Unknown Candidate",
            "github_username": None,
            "email": None,
            "phone": None,
            "category": "student",
            "education": [],
            "experience": [],
            "projects": [],
            "skills": [],
            "certifications": [],
            "github_project_links": [],
            "miscellaneous_details": f"Extraction failed: {str(e)}"
        }
    
def github_node(state: ATS_State):
    username = state.get("github_username")
    project_links = state.get("github_project_links")
    
    has_username = username and str(username).strip().lower() not in ["null", "none", "na", "n/a", ""]
    has_links = project_links and len(project_links) > 0
    
    if not has_username and not has_links:
        print("No GitHub username or repo links found. Skipping GitHub investigation.")
        return {
            "github_username": None,
            "github_data": {
                "name": "N/A",
                "total_public_repositories": 0,
                "account_created": "N/A",
                "bio": "No GitHub profile or repository links provided",
                "recent_projects": []
            }
        }
        
    print(f"Investigating GitHub. Username: {username or 'N/A'}, Repo Links Count: {len(project_links) if project_links else 0}....")
    try:
        project_titles = []
        if state.get("projects"):
            project_titles = [proj.get("title", "") for proj in state["projects"] if proj.get("title")]
            
        github_report: GitHubReport = run_github_agent(
            username=username if has_username else None,
            projects_to_verify=project_titles,
            github_project_links=project_links
        )
        return {
            "github_data": github_report.model_dump()
        }
    except Exception as e:
        print(f"Error during GitHub investigation: {str(e)}")
        return {
            "github_data": {
                "name": username or "N/A",
                "total_public_repositories": 0,
                "account_created": "Unknown",
                "bio": f"Investigation failed: {str(e)}",
                "recent_projects": []
            }
        }

def project_verification_node(state: ATS_State):
    time.sleep(3)
    username = state.get("github_username")
    if not state.get("projects") or not state.get("github_data") or not state["github_data"].get("recent_projects"):
        print("Bypassing Project Verification (no GitHub profile or repositories)...")
        return {
            "project_verification": "Project Verification skipped: No GitHub profile or repositories retrieved."
        }
        
    print("Cross-verifying candidate projects against GitHub data...")
    try:
        structured_llm = heavy_llm.with_structured_output(ProjectVerificationResult)
        messages = [
            SystemMessage(content="""You are a strict, highly professional Technical Auditor.
            Compare the projects listed in the candidate's resume against their live GitHub repositories.
            
            NOTE: The current local simulation time is May 30, 2026. Therefore, dates in 2025 and 2026 are valid recent historical dates, not future dates.
            
            For each project:
            1. Find the corresponding repository in the GitHub data.
            2. Match the claimed technology stack (e.g. Django, LangChain, Vue.js) against the repository's languages and metadata.
            3. Check if the repository is a Forked repository (a copy of someone else's repository).
            4. Verify the candidate's active contributions (check last pushed date, stars).
            
            Format your report cleanly in Markdown. Clearly list matches, minor mismatches, and warnings (e.g., if a project is a fork, completely inactive, or doesn't match the claimed tech stack)."""),
            
            HumanMessage(content=f"""
            Candidate Name: {state['name']}
            GitHub Username: {username or 'N/A'}
            
            Projects Claimed in Resume:
            {json.dumps(state['projects'], indent=2)}
            
            GitHub Data Retrieved:
            {json.dumps(state['github_data'], indent=2)}
            """)
        ]
        result = structured_llm.invoke(messages)
        return {
            "project_verification": result.verification_report
        }
    except Exception as e:
        print(f"Error during project verification: {str(e)}")
        return {
            "project_verification": f"Project Verification failed due to model error: {str(e)}"
        }

def student_node(state: ATS_State):
    print("Candidate is a student, evaluating against Student Matrix...")
    excel_path = state.get("matrix_path") or os.path.join("data", "Profile Completion&Strength.xlsx")
    if not os.path.isabs(excel_path):
        excel_path = os.path.join(backend_dir, excel_path)
    try:
        matrix = load_scoring_matrix(excel_path, sheet_name="Student_CareerScapeScore")
        result = evaluate_candidate(
            heavy_llm, 
            candidate_name=state["name"], 
            github_data=state["github_data"], 
            scoring_markdown=matrix, 
            resume_text="",
            structured_resume=state,
            project_verification=state.get("project_verification")
        )
        
        formatted_reasoning = (
            f"{result.reasoning}\n\n"
            f"=== DETAILED MATRIX CALCULATIONS ===\n"
            f"{result.detailed_calculations}\n\n"
            f"=== SCORING BREAKDOWN ===\n"
            f"{json.dumps(result.scoring_breakdown.model_dump(), indent=2)}"
        )
        
        return {
            "score": result.score,
            "reasoning": formatted_reasoning,
            "ats_reasoning_summary": result.ats_reasoning_summary,
            "final_decision": result.decision,
            "jd_score": None,
            "jd_reasoning": "No JD provided" if not state.get("jd_text") else None,
            "final_weighted_score": float(result.score)
        }
    except Exception as e:
        print(f"Error during student assessment: {str(e)}")
        return {
            "score": 0,
            "reasoning": f"Assessment failed: {str(e)}",
            "ats_reasoning_summary": "Assessment failed.",
            "final_decision": "rejected",
            "jd_score": None,
            "jd_reasoning": "Assessment failed",
            "final_weighted_score": 0.0
        }

def experienced_node(state: ATS_State):
    print("Candidate is experienced, evaluating against Experienced Matrix...")
    excel_path = state.get("matrix_path") or os.path.join("data", "Profile Completion&Strength.xlsx")
    if not os.path.isabs(excel_path):
        excel_path = os.path.join(backend_dir, excel_path)
    try:
        matrix = load_scoring_matrix(excel_path, sheet_name="Expereinced Candidate")
        result = evaluate_candidate(
            heavy_llm, 
            candidate_name=state["name"], 
            github_data=state["github_data"], 
            scoring_markdown=matrix, 
            resume_text="",
            structured_resume=state,
            project_verification=state.get("project_verification")
        )
        
        formatted_reasoning = (
            f"{result.reasoning}\n\n"
            f"=== DETAILED MATRIX CALCULATIONS ===\n"
            f"{result.detailed_calculations}\n\n"
            f"=== SCORING BREAKDOWN ===\n"
            f"{json.dumps(result.scoring_breakdown.model_dump(), indent=2)}"
        )
        
        return {
            "score": result.score,
            "reasoning": formatted_reasoning,
            "ats_reasoning_summary": result.ats_reasoning_summary,
            "final_decision": result.decision,
            "jd_score": None,
            "jd_reasoning": "No JD provided" if not state.get("jd_text") else None,
            "final_weighted_score": float(result.score)
        }
    except Exception as e:
        print(f"Error during experienced assessment: {str(e)}")
        return {
            "score": 0,
            "reasoning": f"Assessment failed: {str(e)}",
            "ats_reasoning_summary": "Assessment failed.",
            "final_decision": "rejected",
            "jd_score": None,
            "jd_reasoning": "Assessment failed",
            "final_weighted_score": 0.0
        }

def jd_evaluator_node(state: ATS_State):
    time.sleep(3)
    print("Evaluating candidate against Job Description with custom skill weights...")
    try:
        # Fetch job skills
        skills_list = []
        job_id = state.get("job_id")
        if job_id:
            try:
                from pymongo import MongoClient
                from bson import ObjectId
                # Retrieve skills from database
                cloud_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
                db_client = MongoClient(cloud_url)
                db = db_client.ats_database
                job = db.jobs.find_one({"_id": ObjectId(job_id)})
                if job and job.get("skills"):
                    skills_list = job["skills"]
                    print(f"Retrieved {len(skills_list)} custom skills from database for Job ID {job_id}.")
            except Exception as db_err:
                print(f"Error fetching job custom skills: {str(db_err)}")

        if not skills_list:
            print("No job custom skills found in database or job_id is missing. Extracting default skills on the fly...")
            try:
                structured_extractor = fast_llm.with_structured_output(JDSkillsExtraction)
                extracted = structured_extractor.invoke(f"Extract key technical skills from this job description:\n\n{state['jd_text']}")
                skills_list = [{"name": s.name, "weight": s.weight} for s in extracted.skills]
                print(f"On-the-fly skills extraction complete. Extracted {len(skills_list)} skills.")
            except Exception as ext_err:
                print(f"Error during on-the-fly skills extraction: {str(ext_err)}")
                # Ultimate fallback if extraction fails
                skills_list = [{"name": "Technical Match", "weight": 100}]

        structured_llm = heavy_llm.with_structured_output(JDFitResult)
        
        candidate_details = (
            f"Education details:\n{json.dumps(state.get('education', []), indent=2)}\n\n"
            f"Experience/Internship details:\n{json.dumps(state.get('experience', []), indent=2)}\n\n"
            f"Projects details:\n{json.dumps(state.get('projects', []), indent=2)}\n\n"
            f"Skills:\n{json.dumps(state.get('skills', []), indent=2)}\n\n"
            f"Certifications:\n{json.dumps(state.get('certifications', []), indent=2)}\n\n"
            f"Miscellaneous/Other details:\n{state.get('miscellaneous_details', 'None')}"
        )
        
        verification_string = ""
        if state.get("project_verification"):
            verification_string = f"\n\nLive GitHub Project Cross-Verification Audit:\n{state['project_verification']}"
            
        skills_instruction = "\n".join(f"- {s['name']}" for s in skills_list)

        messages = [
            SystemMessage(content=f"""You are an Expert Technical Hiring Manager. 
            Evaluate how well the candidate's skills and projects match this Job Description. Use the project verification audit to assess whether the claims are genuine.
            
            NOTE: The current local simulation time is May 30, 2026. Therefore, dates in 2025 and 2026 are valid recent historical dates, not future dates.
            
            JOB DESCRIPTION:
            {state['jd_text']}
 
            You MUST evaluate and score the candidate on exactly these technical skills:
            {skills_instruction}
            
            Provide a match score out of 100 for each of these skills in the structured output. Make sure the names of the skills match exactly as listed above.
            """),
            HumanMessage(content=f"""Candidate Name: {state['name']}
            Candidate Details:
            {candidate_details}{verification_string}
            Candidate GitHub Data: {state['github_data']}
            
            Provide a detailed match analysis, the individual scores for the requested skills, and a brief reasoning summarizing the candidate's overall fit.""")
        ]
        
        result = structured_llm.invoke(messages)
        
        # Calculate programmatic weighted score
        score_lookup = {}
        for s in result.skills_scores:
            score_lookup[s.name.strip().lower()] = s.score
            
        weighted_sum = 0.0
        details_breakdown = []
        
        for skill in skills_list:
            name = skill["name"]
            weight = skill["weight"]
            name_lower = name.strip().lower()
            score = 0
            if name_lower in score_lookup:
                score = score_lookup[name_lower]
            else:
                matched = False
                for k, v in score_lookup.items():
                    if k in name_lower or name_lower in k:
                        score = v
                        matched = True
                        break
                if not matched:
                    print(f"Warning: Skill '{name}' not found in LLM evaluation scores.")
                    score = 0
            
            weighted_sum += score * (weight / 100.0)
            details_breakdown.append(f"- {name} (Weight: {weight}%): {score}/100")
            
        jd_score = int(round(weighted_sum))
        
        base_score = state.get("score")
        if base_score is None:
            base_score = 0
        final_score = (base_score * 0.3) + (jd_score * 0.7)
        
        decision = "shortlisted" if final_score >= 60.0 else "rejected"
        
        formatted_jd_reasoning = (
            f"{result.reasoning}\n\n"
            f"=== INDIVIDUAL SKILL EVALUATIONS ===\n"
            + "\n".join(details_breakdown) + "\n\n"
            f"=== DETAILED JD MATCH ANALYSIS ===\n"
            f"{result.detailed_match_analysis}"
        )
        
        return {
            "jd_score": jd_score,
            "jd_reasoning": formatted_jd_reasoning,
            "jd_reasoning_summary": result.jd_reasoning_summary,
            "final_weighted_score": final_score,
            "final_decision": decision
        }
    except Exception as e:
        print(f"Error during JD evaluation: {str(e)}")
        return {
            "jd_score": 0,
            "jd_reasoning": f"JD evaluation failed: {str(e)}",
            "jd_reasoning_summary": "JD evaluation failed.",
            "final_weighted_score": 0.0,
            "final_decision": "rejected"
        }

def communicator_node(state: ATS_State):
    time.sleep(3)
    print("Synthesizing final HR deliverables...")
    try:
        structured_llm = fast_llm.with_structured_output(FinalDeliverables)
        
        messages = [
            SystemMessage(content="""You are an Expert HR Communicator and Technical Recruiter. 
            Your job is to synthesize the candidate's evaluation data into actionable deliverables.
            If their Final Weighted Score is below 60, draft a polite, constructive rejection email. 
            If it is 60 or above, draft an enthusiastic next-steps email referencing their specific projects."""),
            
            HumanMessage(content=f"""
            Candidate Name: {state['name']}
            Base Matrix Score: {state['score']} (Reasoning: {state['reasoning']})
            JD Fit Score: {state['jd_score']} (Reasoning: {state['jd_reasoning']})
            Final Weighted Score: {state['final_weighted_score']}
            
            Job Description Context: {state['jd_text']}
            
            Generate the final deliverables (email, HR brief, and interview questions).""")
        ]
        
        result = structured_llm.invoke(messages)
        
        score = state.get("final_weighted_score", 0)
        final_decision = "shortlisted" if score >= 60 else "rejected"
        
        return {
            "final_decision": final_decision,
            "candidate_email": result.candidate_email,
            "hiring_manager_brief": result.hiring_manager_brief,
            "interview_questions": result.interview_questions
        }
    except Exception as e:
        print(f"Error during HR communication synthesis: {str(e)}")
        return {
            "candidate_email": f"Error generating outreach: {str(e)}",
            "hiring_manager_brief": f"Outreach generation failed: {str(e)}",
            "interview_questions": ["Verification interview needed to assess raw skills."]
        }

# StateGraph compilation
workflow = StateGraph(ATS_State)
workflow.add_node("extractor", extractor_node)
workflow.add_node("github", github_node)
workflow.add_node("project_verification", project_verification_node)
workflow.add_node("student", student_node)
workflow.add_node("experienced", experienced_node)
workflow.add_node("jd_evaluator", jd_evaluator_node)
workflow.add_node("communicator", communicator_node)

workflow.add_edge(START, "extractor")
workflow.add_edge("extractor", "github")
workflow.add_edge("github", "project_verification")
workflow.add_conditional_edges(
    "project_verification",
    route_candidate,
    ["student", "experienced"]
)
workflow.add_edge("student", "jd_evaluator")
workflow.add_edge("experienced", "jd_evaluator")
workflow.add_edge("jd_evaluator", "communicator")
workflow.add_edge("communicator", END)

ats_workflow = workflow.compile()

def process_candidate_pipeline(resume_path: str, jd_path: str, job_id: Optional[str] = None, resume_gcs_uri: Optional[str] = None):
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
                    "ats_reasoning_summary": "Failed basic eligibility pre-screening.",
                    "jd_score": 0,
                    "jd_reasoning": f"AUTOMATIC PRE-SCREENING REJECTION:\n\nCandidate failed eligibility rules:\n{eligibility.reason}",
                    "jd_reasoning_summary": "Failed basic eligibility pre-screening.",
                    "final_weighted_score": 0.0,
                    "final_decision": "rejected",
                    "candidate_email": f"Dear {candidate_name},\n\nThank you for your interest in our job role. After reviewing your profile, we have determined that you do not meet the minimum eligibility requirements specified for this position. Therefore, we will not be moving forward with your application at this time.\n\nBest regards,\nHR Recruiting Team",
                    "hiring_manager_brief": f"Candidate failed eligibility check: {eligibility.reason}. Evaluation bypassed to save pipeline usage.",
                    "interview_questions": [],
                    "job_id": job_id,
                    "resume_gcs_uri": resume_gcs_uri
                }
                
                inserted_doc = candidates_collection.insert_one(final_state)
                final_state["_id"] = str(inserted_doc.inserted_id)
                return final_state
        except Exception as filter_err:
            print(f"Error during eligibility screening, continuing with full pipeline: {filter_err}")

    state: ATS_State = {
        "raw_resume": resume_text,
        "jd_text": jd_text,
        "matrix_path": os.path.join("data", "Profile Completion&Strength.xlsx"), 
        "job_id": job_id,
        "name": None, "github_username": None, "email": None, "phone": None,
        "category": None, "education": None, "experience": None, "projects": None,
        "skills": None, "certifications": None, "miscellaneous_details": None,
        "github_data": None, "project_verification": None, "score": None,
        "reasoning": None, "ats_reasoning_summary": None, "jd_score": None, "jd_reasoning": None, "jd_reasoning_summary": None,
        "final_weighted_score": None, "final_decision": None,
        "candidate_email": None, "hiring_manager_brief": None, "interview_questions": None,
        "resume_gcs_uri": resume_gcs_uri
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
