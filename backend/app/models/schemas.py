from typing import TypedDict, Optional, List
from pydantic import BaseModel, Field

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
    github_project_links: Optional[list]
    miscellaneous_details: Optional[str]
    
    # Live data & verification
    github_data: Optional[dict]
    project_verification: Optional[str]
    
    # Score reports
    score: Optional[int]          # The Excel Matrix Base Score
    reasoning: Optional[str]
    ats_reasoning_summary: Optional[str]
    jd_score: Optional[int]       # The JD Fit Score
    jd_reasoning: Optional[str]
    jd_reasoning_summary: Optional[str]
    final_weighted_score: Optional[float] # The combined math
    final_decision: Optional[str]
    candidate_email: Optional[str]
    hiring_manager_brief: Optional[str]
    interview_questions: Optional[list[str]]
    resume_filename: Optional[str]
    resume_gcs_uri: Optional[str]

class SkillScore(BaseModel):
    name: str = Field(description="The name of the core technical skill being evaluated.")
    score: int = Field(description="The match score out of 100 for this specific skill (0-100).")

class JDFitResult(BaseModel):
    detailed_match_analysis: str = Field(description="Step-by-step detailed matching analysis comparing the candidate's skills, experience, and projects against each specific JD requirement (mandatory, good-to-have, and responsibilities). Identify exact matches, partial matches, and gaps first.")
    skills_scores: List[SkillScore] = Field(description="The match score out of 100 for each of the requested job skills.")
    reasoning: str = Field(description="Concise reasoning for the scores.")
    jd_reasoning_summary: str = Field(description="A concise, 1-2 sentence high-level summary explaining precisely why the candidate received this JD fit score based on their tech stack match. This will be shown on hover.")

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
