import os
import time
import base64
import zipfile
import xml.etree.ElementTree as ET
from typing import Literal, Optional, List
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
import fitz  # PyMuPDF

# ==========================================
# 1. Pydantic Schemas for JD Extraction
# ==========================================
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

# ==========================================
# 2. Pydantic Schemas for Resume Extraction
# ==========================================
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

class GitHubRepoLink(BaseModel):
    project_name: str = Field(description="The name of the project this GitHub repository link belongs to. If not explicitly mapped, use a key representing the project or the repository name.")
    repo_url: str = Field(description="The direct URL of the GitHub repository (e.g. https://github.com/username/repo)")

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
    github_project_links: List[GitHubRepoLink] = Field(default_factory=list, description="A list of direct GitHub repository links found in the resume mapped to their respective project names.")
    miscellaneous_details: Optional[str] = Field(None, description="Any other details, achievements, interests, test scores, honours, activities, or general info found in the resume that do not fit the fields above.")

# ==========================================
# 3. Extraction Agent Functions
# ==========================================
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

def extract_candidate_info(llm, resume_text: str) -> CandidateInfo:
    structured_llm = llm.with_structured_output(CandidateInfo)
    messages = [
        SystemMessage(content="You are a highly professional AI assistant."),
        HumanMessage(content=resume_text)
    ]
    return structured_llm.invoke(messages)

# ==========================================
# 4. File Reading & Fallback Logic
# ==========================================
def read_pdf_content(llm, pdf_path: str) -> str:
    """Extracts text natively, with a Vertex AI Vision fallback for scanned images."""
    print(f"[DEBUG read_pdf_content] Opening PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    
    all_pages_text = []
    
    for i, page in enumerate(doc):
        # 1. Try Native Extraction first (Fast & Free)
        page_text = page.get_text().strip()
        
        # 2. Extract Hidden URLs
        links = page.get_links()
        urls = [link.get('uri') for link in links if link.get('uri')]
        if urls:
            urls_str = "\n".join(urls)
            page_text += f"\n\n--- Embedded URLs found on this page ---\n{urls_str}"
            
        # 3. The Smart Fallback (For Scanned PDFs / Images)
        if len(page_text) < 50:
            print(f"⚠️ Page {i+1} appears to be a scanned image. Triggering Vertex AI Vision OCR...")
            
            time.sleep(3) # Sleep briefly to respect the 15 RPM free tier limit
            
            pix = page.get_pixmap()
            image_bytes = pix.tobytes("jpeg")
            code = base64.b64encode(image_bytes).decode("utf-8")
            
            messages = [
                SystemMessage(content="You are a highly professional AI assistant. Read the document page image and transcribe its full content exactly as written."),
                HumanMessage(content=[
                    {"type": "text", "text": "Please read this document image and extract its complete contents."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{code}"}}
                ])
            ]
            
            try:
                response = llm.invoke(messages)
                if isinstance(response.content, list):
                    ocr_text = "".join([part.get("text", "") for part in response.content if isinstance(part, dict)])
                else:
                    ocr_text = response.content
                
                page_text += f"\n\n{ocr_text}"
            except Exception as e:
                print(f"❌ Vision OCR failed on page {i+1}: {e}")

        all_pages_text.append(page_text)
            
    return "\n\n--- PAGE BREAK ---\n\n".join(all_pages_text)

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

def read_document_content(llm, file_path: str, force_ocr: bool = True) -> str:
    print(f"[DEBUG read_document_content] Entering with file_path: {file_path}, force_ocr: {force_ocr}")
    if not file_path:
        print(f"[DEBUG read_document_content] Empty file path")
        return ""
    if file_path.lower().endswith(".docx"):
        print(f"[DEBUG read_document_content] Identified as DOCX")
        res = read_docx_content(file_path)
        print(f"[DEBUG read_document_content] DOCX read complete. Result length: {len(res)}")
        return res
    elif file_path.lower().endswith(".pdf"):
        print(f"[DEBUG read_document_content] Identified as PDF")
        res = read_pdf_content(llm, file_path)
        print(f"[DEBUG read_document_content] PDF read complete. Result length: {len(res)}")
        return res
    else:
        print(f"[DEBUG read_document_content] Identified as other file type (reading text)")
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            res = f.read()
        print(f"[DEBUG read_document_content] Text read complete. Result length: {len(res)}")
        return res

if __name__ == "__main__":
    from langchain_google_vertexai import ChatVertexAI
    from dotenv import load_dotenv
    
    load_dotenv()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "E:/AI-Resume-Evaluator-V2/backend/ai-resume-evaluator-498012-305d5547940c.json"
    
    # Initialize the LLM with the correct Vertex AI class
    llm = ChatVertexAI(
        model_name="gemini-2.5-flash",
        project="ai-resume-evaluator-498012",
        location="us-central1",
        temperature=0
    )
    
    pdf_path = os.path.join("data", "2023A7PS0123H_ Earn In.pdf")
    print(f"Reading and transcribing complete content from {pdf_path}...")
    
    try:
        full_content = read_pdf_content(llm, pdf_path)
        print("\n--- FULL EXTRACTED CONTENT ---")
        print(full_content)
    except Exception as e:
        print(f"Testing failed (Make sure the file exists!): {e}")