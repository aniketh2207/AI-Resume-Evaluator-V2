import os
import sys
import json
from typing import TypedDict, Optional
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
    name: Optional[str]
    github_username: Optional[str]
    category: Optional[str]
    github_data: Optional[dict]
    score: Optional[int]          # The Excel Matrix Base Score
    reasoning: Optional[str]
    jd_score: Optional[int]       # The JD Fit Score
    jd_reasoning: Optional[str]
    final_weighted_score: Optional[float] # The combined math
    final_decision: Optional[str]
    candidate_email: Optional[str]
    hiring_manager_brief: Optional[str]
    interview_questions: Optional[list[str]]

class JDFitResult(BaseModel):
    detailed_match_analysis: str = Field(description="Step-by-step detailed matching analysis comparing the candidate's skills, experience, and projects against each specific JD requirement (mandatory, good-to-have, and responsibilities). Identify exact matches, partial matches, and gaps first.")
    score: int = Field(description="The fit score out of 100 based strictly on the matching analysis.")
    reasoning: str = Field(description="Concise reasoning for the JD fit score.")

class FinalDeliverables(BaseModel):
    candidate_email: str = Field(description="A personalized email to the candidate regarding the next steps or rejection.")
    hiring_manager_brief: str = Field(description="A concise summary for the HR team detailing their technical strengths and JD alignment.")
    interview_questions: list[str] = Field(description="3 custom technical interview questions based on their projects and the JD.")

llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0)

def route_candidate(state: ATS_State):
    if state['category'] == "student":
        return "student"
    else:
        return "experienced"

def extractor_node(state: ATS_State):
    print("Extracting Candidate Info...")
    info: CandidateInfo = extract_candidate_info(llm, state["raw_resume"])
    return {
        "name": info.name,
        "github_username": info.github_username,
        "category": info.category
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
    # Calling the tools.py agent
    github_report: GitHubReport = run_github_agent(username)
    # Convert Pydantic object to plain dictionary for state serialization
    return {
        "github_data": github_report.model_dump()
    }

# these are the nodes that goes through the RAG pipeline for the scoring logic
def student_node(state: ATS_State):
    print("Candidate is a student, evaluating against Student Matrix...")
    excel_path = "Profile Completion&Strength.xlsx"
    
    # Pass the exact name of the student sheet
    matrix = load_scoring_matrix(excel_path, sheet_name="Student_CareerScapeScore")
    
    result = evaluate_candidate(llm, state["name"], state["github_data"], matrix, resume_text=state["raw_resume"])
    
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

def experienced_node(state: ATS_State):
    print("Candidate is experienced, evaluating against Experienced Matrix...")
    excel_path = "Profile Completion&Strength.xlsx"
    
    # Pass the exact name of the experienced sheet
    matrix = load_scoring_matrix(excel_path, sheet_name="Expereinced Candidate")
    
    result = evaluate_candidate(llm, state["name"], state["github_data"], matrix, resume_text=state["raw_resume"])
    
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

def jd_evaluator_node(state: ATS_State):
    print("Evaluating candidate against Job Description...")
    structured_llm = llm.with_structured_output(JDFitResult)
    
    messages = [
        SystemMessage(content=f"""You are an Expert Technical Hiring Manager. 
        Evaluate how well the candidate's skills and projects match this Job Description.
        
        JOB DESCRIPTION:
        {state['jd_text']}
        """),
        HumanMessage(content=f"""Candidate Name: {state['name']}
        Candidate Resume Data: {state['raw_resume']}
        Candidate GitHub Data: {state['github_data']}
        
        Provide a fit score out of 100 and brief reasoning.""")
    ]
    
    result = structured_llm.invoke(messages)
    
    # Apply the Two-Tier Weighted Math (e.g., 30% Base, 70% JD)
    base_score = state.get("score", 0)
    jd_score = result.score
    final_score = (base_score * 0.3) + (jd_score * 0.7)
    
    # Re-calculate the final combined decision based on the weighted score
    decision = "approved" if final_score >= 60.0 else "rejected"
    
    formatted_jd_reasoning = (
        f"{result.reasoning}\n\n"
        f"=== DETAILED JD MATCH ANALYSIS ===\n"
        f"{result.detailed_match_analysis}"
    )
    
    return {
        "jd_score": jd_score,
        "jd_reasoning": formatted_jd_reasoning,
        "final_weighted_score": final_score,
        "final_decision": decision
    }

def communicator_node(state: ATS_State):
    print("Synthesizing final HR deliverables...")
    structured_llm = llm.with_structured_output(FinalDeliverables)
    
    # We pass all the accumulated context from the previous agents to Agent 4
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
    
    # Make the final binary decision based on the combined threshold
    final_decision = "approved" if state.get("final_weighted_score", 0) >= 60 else "rejected"
    
    return {
        "final_decision": final_decision,
        "candidate_email": result.candidate_email,
        "hiring_manager_brief": result.hiring_manager_brief,
        "interview_questions": result.interview_questions
    }

# from here starts the langgraph routing logic 
workflow = StateGraph(ATS_State)
workflow.add_node("extractor", extractor_node)
workflow.add_node("student", student_node)
workflow.add_node("experienced", experienced_node)
workflow.add_node("github", github_node)
workflow.add_node("jd_evaluator", jd_evaluator_node)
workflow.add_node("communicator",communicator_node)

workflow.add_edge(START, "extractor")
workflow.add_edge("extractor", "github")
workflow.add_conditional_edges(
    "github",
    route_candidate,
    ["student", "experienced"]
)
workflow.add_edge("student", "jd_evaluator")
workflow.add_edge("experienced", "jd_evaluator")
workflow.add_edge("jd_evaluator", "communicator")
workflow.add_edge("communicator",END)

app = workflow.compile()

if __name__ == "__main__":
    pdf_path = "2022B3A40527H_Bigbasket.pdf"
    jd_path = "bigbasket_Product_Internship_JD.pdf"
    test_resume = read_document_content(llm, pdf_path)
    test_jd = read_document_content(llm, jd_path)
    state: ATS_State = {
        "raw_resume": test_resume,
        "jd_text": test_jd,
        "name": None,
        "github_username": None,
        "category": None,
        "github_data": None,
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
    print(json.dumps(final_state, indent=4, ensure_ascii=False))
    
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(final_state, f, indent=4, ensure_ascii=False)
    print("\nPipeline execution complete. Output saved to 'output.json'.")


