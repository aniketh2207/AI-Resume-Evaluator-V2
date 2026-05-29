from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from typing import Literal
import io
import fitz  # PyMuPDF
import base64

# Define the structured output schema
class CandidateInfo(BaseModel):
    name: str = Field(description="The full name of the candidate")
    github_username: str = Field(description="The candidate's GitHub username")
    category: Literal["student", "experienced"] = Field(description="If they mention college or studying, they are a student. Otherwise, experienced.")

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