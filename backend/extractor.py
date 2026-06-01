from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from typing import Literal, Optional, List
import io
import fitz  # PyMuPDF
import base64

class JDSkillInfo(BaseModel):
    name: str = Field(description="The name of the core technical skill, tool, or framework.")
    weight: int = Field(description="Initial default weight (an integer out of 100). The sum of all skills must equal 100.")

class JDExtractionData(BaseModel):
    skills: List[JDSkillInfo] = Field(description="A list of 4 to 8 primary technical skills extracted from the job description.")
    required_graduation_years: List[int] = Field(default_factory=list, description="A list of integer graduation years explicitly required or preferred for the candidate (e.g., [2025, 2026] if it explicitly says 'graduating in 2025 or 2026' or 'class of 2026'). CRITICAL: Do NOT infer graduation years from the internship start date or calendar year of the posting (e.g., if it says 'starts in July 2026', do NOT assume required graduation year is 2026). Only populate this if candidate graduation/batch years are explicitly specified in the text. Otherwise, return an empty list.")
    minimum_gpa: Optional[float] = Field(None, description="Minimum GPA required. If none, return null.")
    other_eligibility_criteria: Optional[str] = Field(None, description="Any other strict eligibility criteria mentioned in the JD. If none, return null.")

class EligibilityCheck(BaseModel):
    is_eligible: bool = Field(description="True if the candidate meets the strict requirements (graduation years, GPA, other eligibility criteria) specified in the eligibility rules. False otherwise.")
    reason: str = Field(description="Detailed explanation of why the candidate is eligible or ineligible.")

def extract_jd_data(llm, jd_text: str) -> JDExtractionData:
    structured_llm = llm.with_structured_output(JDExtractionData)
    messages = [
        SystemMessage(content="You are an expert technical recruiter. Extract structured skill and eligibility rules from this Job Description."),
        HumanMessage(content=jd_text)
    ]
    return structured_llm.invoke(messages)

def check_candidate_eligibility(llm, resume_text: str, criteria: dict) -> EligibilityCheck:
    structured_llm = llm.with_structured_output(EligibilityCheck)
    
    grad_years = criteria.get("required_graduation_years", [])
    min_gpa = criteria.get("minimum_gpa")
    other_crit = criteria.get("other_eligibility_criteria")
    
    rules = []
    if grad_years:
        rules.append(f"- Candidate must be graduating in one of these years: {', '.join(map(str, grad_years))}")
    if min_gpa is not None:
        rules.append(f"- Candidate must have a minimum GPA of: {min_gpa}")
    if other_crit:
        rules.append(f"- Candidate must meet this requirement: {other_crit}")
        
    rules_str = "\n".join(rules)
    
    messages = [
        SystemMessage(content=f"""You are a strict, highly professional Recruitment Auditor.
        Verify if the candidate meets the following strict eligibility requirements from the Job Description:
        
        {rules_str}
        
        Analyze the candidate's resume text carefully. Note:
        - Check graduation year (e.g. if they mention "2023 - 2026", their graduation year is 2026. If they are expected to graduate in 2025, it matches 2025).
        - Check GPA (if mentioned, compare with the minimum GPA).
        - Check other eligibility requirements.
        - If the resume does not specify a graduation year or GPA and these are required, but there are no negative contradictions, look for indicators or default to eligible unless there's a clear mismatch. However, be strict on explicit mismatches (e.g. graduation in 2023 when 2025/2026 is required).
        
        Provide a boolean outcome and a clear, professional reason for your decision.
        """),
        HumanMessage(content=f"Candidate Resume Text:\n\n{resume_text}")
    ]
    return structured_llm.invoke(messages)

class ProjectResumeInfo(BaseModel):
    title: str = Field(description="Title of the project")
    description: str = Field(description="Summary of what was built and candidate's contributions")
    technologies: List[str] = Field(description="List of tools, languages, and frameworks used")

class EducationInfo(BaseModel):
    institution: str = Field(description="Name of university or school")
    degree: Optional[str] = Field(None, description="Degree or program name")
    gpa: Optional[str] = Field(None, description="GPA or grades obtained")
    duration: Optional[str] = Field(None, description="Years attended, e.g., 2023 - 2027")

class WorkExperienceInfo(BaseModel):
    company: str = Field(description="Name of organization")
    role: str = Field(description="Job title")
    duration: str = Field(description="Start and end dates")
    description: str = Field(description="Key responsibilities and achievements")

# Define the structured output schema
class CandidateInfo(BaseModel):
    name: str = Field(description="The full name of the candidate")
    github_username: Optional[str] = Field(None, description="The candidate's GitHub username. If not mentioned or not found in the resume, return null.")
    email: Optional[str] = Field(None, description="The candidate's email address. If not mentioned or not found in the resume, return null.")
    phone: Optional[str] = Field(None, description="The candidate's phone number. If not mentioned or not found in the resume, return null.")
    category: Literal["student", "experienced"] = Field(description="If they mention college or studying, they are a student. Otherwise, experienced.")
    education: List[EducationInfo] = Field(default_factory=list, description="Academic history details")
    experience: List[WorkExperienceInfo] = Field(default_factory=list, description="Work and internship history details")
    projects: List[ProjectResumeInfo] = Field(default_factory=list, description="List of projects built")
    skills: List[str] = Field(default_factory=list, description="Technical skills listed")
    certifications: List[str] = Field(default_factory=list, description="Professional certifications")
    miscellaneous_details: Optional[str] = Field(None, description="Any other details, achievements, interests, test scores, honours, activities, or general info found in the resume that do not fit the fields above.")

# Define the extraction helper function
def extract_candidate_info(llm, resume_text: str) -> CandidateInfo:
    structured_llm = llm.with_structured_output(CandidateInfo)
    messages = [
        SystemMessage(content="You are a highly professional AI assistant."),
        HumanMessage(content=resume_text)
    ]
    return structured_llm.invoke(messages)

# New function for raw content reading/transcription
def read_pdf_content(llm, pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    links = page.get_links()
    urls = [link.get('uri') for link in links if link.get('uri')]
    urls_str = "\n".join(urls)
    pix = page.get_pixmap()
    image_bytes = pix.tobytes("jpeg")
    
    code = base64.b64encode(image_bytes).decode("utf-8")
    
    messages = [
        SystemMessage(content=f"""You are a highly professional AI assistant.
         Read the resume image and transcribe its full content. Preserve the sections, work history, skills, and contact details exactly as written. 
         the urls from the resume are {urls_str}"""),
        HumanMessage(content=[
            {"type": "text", "text": "Please read this resume image and extract its complete contents in detail."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{code}"}}
        ])
    ]
    response = llm.invoke(messages)
    
    if isinstance(response.content, list):
        return "".join([part.get("text", "") for part in response.content if isinstance(part, dict)])
    return response.content

import zipfile
import xml.etree.ElementTree as ET

def read_docx_content(docx_path: str) -> str:
    try:
        with zipfile.ZipFile(docx_path) as docx:
            xml_content = docx.read('word/document.xml')
            root = ET.fromstring(xml_content)
            namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = []
            for p in root.findall('.//w:p', namespaces):
                p_text = "".join([t.text for t in p.findall('.//w:t', namespaces) if t.text])
                if p_text:
                    paragraphs.append(p_text)
            return "\n".join(paragraphs)
    except Exception as e:
        return f"Error reading Word document: {str(e)}"

def read_document_content(llm, file_path: str) -> str:
    if not file_path:
        return ""
    if file_path.lower().endswith(".docx"):
        return read_docx_content(file_path)
    elif file_path.lower().endswith(".pdf"):
        return read_pdf_content(llm, file_path)
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

if __name__ == "__main__":
    from langchain_google_genai import ChatGoogleGenerativeAI
    from dotenv import load_dotenv
    load_dotenv()
    
    # Initialize the LLM with the quota-friendly model
    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0)
    
    pdf_path = "Aniketh__Software_offCampus.pdf"
    print(f"Reading and transcribing complete content from {pdf_path}...")
    full_content = read_pdf_content(llm, pdf_path)
    
    print("\n--- FULL EXTRACTED CONTENT ---")
    print(full_content)