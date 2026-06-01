import os
import sys
import json
from typing import TypedDict, Optional, List
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from extractor import extract_candidate_info, CandidateInfo, read_document_content
from langgraph.graph import StateGraph, START, END
from tools import run_github_agent, GitHubReport
from assessor import load_scoring_matrix, evaluate_candidate

# Force Windows stdout to handle UTF-8 and Emojis without crashing
sys.stdout.reconfigure(encoding='utf-8')

# Boot-time configuration check
load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("GOOGLE_API_KEY is not set in environment variables.")

# Main State Definition
class ATS_State(TypedDict):
    raw_resume: str
    jd_text: str                  # The extracted JD text
    matrix_path: Optional[str]    # Path to Excel scoring sheet
    job_id: Optional[str]         # Associated Job ID for custom weights
    
    # Structured Candidate Profile
    name: Optional[str]
    github_username: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    category: Optional[str]
    education: Optional[list]
    experience: Optional[list]
    projects: Optional[list]
    skills: Optional[list]
    certifications: Optional[list]
    miscellaneous_details: Optional[str]
    
    # Live data & verification
    github_data: Optional[dict]
    project_verification: Optional[str]
    
    # Score reports
    score: Optional[int]          # The Excel Matrix Base Score
    reasoning: Optional[str]
    jd_score: Optional[int]       # The JD Fit Score
    jd_reasoning: Optional[str]
    final_weighted_score: Optional[float] # The combined math
    final_decision: Optional[str]
    candidate_email: Optional[str]
    hiring_manager_brief: Optional[str]
    interview_questions: Optional[list[str]]

class SkillScore(BaseModel):
    name: str = Field(description="The name of the core technical skill being evaluated.")
    score: int = Field(description="The match score out of 100 for this specific skill (0-100).")

class JDFitResult(BaseModel):
    detailed_match_analysis: str = Field(description="Step-by-step detailed matching analysis comparing the candidate's skills, experience, and projects against each specific JD requirement (mandatory, good-to-have, and responsibilities). Identify exact matches, partial matches, and gaps first.")
    skills_scores: List[SkillScore] = Field(description="The match score out of 100 for each of the requested job skills.")
    reasoning: str = Field(description="Concise reasoning for the scores.")

class FinalDeliverables(BaseModel):
    candidate_email: str = Field(description="A personalized email to the candidate regarding the next steps or rejection.")
    hiring_manager_brief: str = Field(description="A concise summary for the HR team detailing their technical strengths and JD alignment.")
    interview_questions: list[str] = Field(description="3 custom technical interview questions based on their projects and the JD.")

class ProjectVerificationResult(BaseModel):
    verification_report: str = Field(description="Detailed verification report in markdown format comparing resume projects against actual GitHub repositories.")

class ExtractedSkill(BaseModel):
    name: str = Field(description="The name of the core technical skill, tool, or framework.")
    weight: int = Field(description="Initial default weight (an integer out of 100). The sum of all skills must equal 100.")

class JDSkillsExtraction(BaseModel):
    skills: List[ExtractedSkill] = Field(description="A list of 4 to 8 primary technical skills extracted from the job description.")

# Model Tiering Setup
fast_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0)
heavy_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0) # Changed from gemini-3.5-flash (quota exceeded 21/20 daily limit)

# Backward compatibility binding
llm = fast_llm

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
            "miscellaneous_details": f"Extraction failed: {str(e)}"
        }
    
def github_node(state: ATS_State):
    username = state.get("github_username")
    
    # Guard against missing, null, or placeholder usernames
    if not username or str(username).strip().lower() in ["null", "none", "na", "n/a", ""]:
        print("No GitHub username found or provided. Skipping GitHub investigation.")
        return {
            "github_username": None,
            "github_data": {
                "name": "N/A",
                "total_public_repositories": 0,
                "account_created": "N/A",
                "bio": "No GitHub profile provided",
                "recent_projects": []
            }
        }
        
    print(f"Investigating Github for user {username}....")
    try:
        project_titles = []
        if state.get("projects"):
            project_titles = [proj.get("title", "") for proj in state["projects"] if proj.get("title")]
            
        # Calling the tools.py agent
        github_report: GitHubReport = run_github_agent(username, project_titles)
        return {
            "github_data": github_report.model_dump()
        }
    except Exception as e:
        print(f"Error during GitHub investigation: {str(e)}")
        return {
            "github_data": {
                "name": username,
                "total_public_repositories": 0,
                "account_created": "Unknown",
                "bio": f"Investigation failed: {str(e)}",
                "recent_projects": []
            }
        }

def project_verification_node(state: ATS_State):
    username = state.get("github_username")
    if not username or not state.get("projects") or not state.get("github_data") or not state["github_data"].get("recent_projects"):
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
            GitHub Username: {username}
            
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
    excel_path = state.get("matrix_path") or "Profile Completion&Strength.xlsx"
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
            f"{json.dumps(result.scoring_breakdown, indent=2)}"
        )
        
        return {
            "score": result.score,
            "reasoning": formatted_reasoning,
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
            "final_decision": "rejected",
            "jd_score": None,
            "jd_reasoning": "Assessment failed",
            "final_weighted_score": 0.0
        }

def experienced_node(state: ATS_State):
    print("Candidate is experienced, evaluating against Experienced Matrix...")
    excel_path = state.get("matrix_path") or "Profile Completion&Strength.xlsx"
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
            f"{json.dumps(result.scoring_breakdown, indent=2)}"
        )
        
        return {
            "score": result.score,
            "reasoning": formatted_reasoning,
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
            "final_decision": "rejected",
            "jd_score": None,
            "jd_reasoning": "Assessment failed",
            "final_weighted_score": 0.0
        }

def jd_evaluator_node(state: ATS_State):
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
        
        base_score = state.get("score", 0)
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
            "final_weighted_score": final_score,
            "final_decision": decision
        }
    except Exception as e:
        print(f"Error during JD evaluation: {str(e)}")
        return {
            "jd_score": 0,
            "jd_reasoning": f"JD evaluation failed: {str(e)}",
            "final_weighted_score": 0.0,
            "final_decision": "rejected"
        }

def communicator_node(state: ATS_State):
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

# from here starts the langgraph routing logic 
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

app = workflow.compile()

if __name__ == "__main__":
    pdf_path = "Aniketh__Software_offCampus.pdf"
    jd_path = "JD for Interns 2.docx"
    matrix_path = "Profile Completion&Strength.xlsx"
    
    test_resume = read_document_content(fast_llm, pdf_path)
    test_jd = read_document_content(fast_llm, jd_path)
    state: ATS_State = {
        "raw_resume": test_resume,
        "jd_text": test_jd,
        "matrix_path": matrix_path,
        "name": None,
        "github_username": None,
        "email": None,
        "phone": None,
        "category": None,
        "education": None,
        "experience": None,
        "projects": None,
        "skills": None,
        "certifications": None,
        "miscellaneous_details": None,
        "github_data": None,
        "project_verification": None,
        "score": None,
        "reasoning": None,
        "jd_score": None,
        "jd_reasoning": None,
        "final_weighted_score": None,
        "final_decision": None,
        "candidate_email": None,
        "hiring_manager_brief": None,
        "interview_questions": None
    }
    
    print("Running the full ATS Multi-Agent pipeline...")
    final_state = app.invoke(state)
    
    import json
    print("\n--- FINAL PIPELINE STATE (JSON) ---")
    print_state = final_state.copy()
    if "raw_resume" in print_state:
        print_state["raw_resume"] = print_state["raw_resume"][:100] + "..."
    if "jd_text" in print_state:
        print_state["jd_text"] = print_state["jd_text"][:100] + "..."
    print(json.dumps(print_state, indent=4, ensure_ascii=False))
    
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(final_state, f, indent=4, ensure_ascii=False)
    print("\nPipeline execution complete. Output saved to 'output.json'.")


