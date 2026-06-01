from pydantic import BaseModel, Field
from typing import Literal, Optional
import pandas as pd
import json
from langchain_core.messages import SystemMessage, HumanMessage

# 1. Fixed Pydantic syntax
class EvaluationResult(BaseModel):
    detailed_calculations: str = Field(description="Step-by-step lookup and mathematical calculations for each component, matching the candidate's resume and GitHub data against the spreadsheet rules word-by-word. Show the exact weights and multipliers used for every evaluated component.")
    scoring_breakdown: dict = Field(description="Key-value breakdown of scores awarded for each main component in the matrix (e.g. GPA, Certifications, Projects, etc.), where values are the raw decimals before multiplying by 100.")
    score: int = Field(description="The overall score of the candidate, calculated as the sum of all elements in scoring_breakdown multiplied by 100 (rounded to the nearest integer out of 100).")
    reasoning: str = Field(description="A brief summary explanation of the final decision and score.")
    decision: Literal["approved", "rejected"] = Field(description="The final decision based on the score. If score >= 60, 'approved', else 'rejected'.")

# 2. Fixed Data Loader to be dynamic and support sheets
def load_scoring_matrix(file_path: str, sheet_name: str = None) -> str:
    if sheet_name:
        data = pd.read_excel(file_path, sheet_name=sheet_name)
    else:
        data = pd.read_excel(file_path)
    
    # Clean up the matrix columns to only include the components, measures, multipliers, and weights
    cleaned_data = data.iloc[1:, [0, 5, 6, 7]]
    cleaned_data.columns = ['Component', 'Measure', 'Score Multiplier', 'Alloted Weightage']
    cleaned_data = cleaned_data.fillna('')
    return cleaned_data.to_markdown(index=False)

# 3. Fixed Variable Names in the F-String and added Resume support
def evaluate_candidate(
    llm, 
    candidate_name: str, 
    github_data: dict, 
    scoring_markdown: str, 
    resume_text: str = "",
    structured_resume: Optional[dict] = None,
    project_verification: Optional[str] = None
) -> EvaluationResult:
    from typing import Optional
    structured_llm = llm.with_structured_output(EvaluationResult)
    github_string = json.dumps(github_data, indent=2)

    # Build candidate representation from structured data or raw text
    if structured_resume:
        candidate_details = (
            f"Candidate Name: {structured_resume.get('name', 'N/A')}\n"
            f"GitHub Username: {structured_resume.get('github_username', 'N/A')}\n"
            f"Email: {structured_resume.get('email', 'N/A')}\n"
            f"Phone: {structured_resume.get('phone', 'N/A')}\n\n"
            f"Education details:\n{json.dumps(structured_resume.get('education', []), indent=2)}\n\n"
            f"Experience/Internship details:\n{json.dumps(structured_resume.get('experience', []), indent=2)}\n\n"
            f"Projects details:\n{json.dumps(structured_resume.get('projects', []), indent=2)}\n\n"
            f"Skills:\n{json.dumps(structured_resume.get('skills', []), indent=2)}\n\n"
            f"Certifications:\n{json.dumps(structured_resume.get('certifications', []), indent=2)}\n\n"
            f"Miscellaneous/Other details:\n{structured_resume.get('miscellaneous_details', 'None')}"
        )
    else:
        candidate_details = resume_text

    verification_string = ""
    if project_verification:
        verification_string = f"\n\nLive GitHub Project Cross-Verification Audit:\n{project_verification}"

    messages = [
        SystemMessage(content=f"""You are a strict, highly professional technical recruiter and AI Assessor.
    Your job is to evaluate a candidate's GitHub profile, resume details, and project verification audits against a specific scoring matrix sheet.
    
    NOTE: The current local simulation time is May 30, 2026. Therefore, dates in 2025 and 2026 are valid recent historical dates, not future dates.

    Here is the exact scoring matrix you MUST follow word-by-word to calculate their score:
    {scoring_markdown}

    INSTRUCTIONS:
    1. Match the candidate's attributes (GPA, certifications, work experience, projects, technical skills, interests, etc. from both their resume and GitHub data) against the exact components, measures, and weights in the matrix.
    2. Use the Live GitHub Project Cross-Verification Audit to verify project authenticity. If a project is flagged as cloned, copied, or mismatched, dock points from the 'Projects' and 'Technical Skills' categories accordingly based on the matrix rules.
    3. For each component:
       - Identify the candidate's matching row/measure.
       - Use the specified 'Score Multiplier' and 'Alloted Weightage' to calculate the score: Score = Multiplier * Weightage.
       - If a component is not mentioned or not completed (e.g. psychometric assessments or patents if they have none), it MUST score 0.
    4. STRICT RULES TO PREVENT ASSUMPTIONS & HALLUCINATIONS:
       - DO NOT make assumptions for missing fields. Any component not explicitly written in the resume (such as 10th-grade scores, language skills, publications, etc.) MUST be scored 0.
       - DO NOT double-count. If an experience is classified as an internship, score it under the 'Internship' component. The 'Work Experience' component (which represents full-time post-graduate employment) MUST be scored 0.
       - DO NOT infer implied sections. If there is no explicit introduction/profile summary text or future plans section in the resume, they MUST be scored 0.
       - Consistency scoring is strict: Average of Graduation GPA, 12th%, and 10th%. If ANY of these three scores is missing from the resume, the Consistency component CANNOT be calculated and MUST score 0.
    5. Default Assumptions & Clarifications:
       - For the 'About Me' -> 'Profile Completion' (Weightage: 0.05): If the candidate has provided comprehensive details of education, projects, skills, and experiences in their resume, consider the profile complete and award a Score Multiplier of 1 (Score: 0.05). Do not penalize with 0 for a missing GitHub bio if the resume itself is complete.
       - For the 'Personal' -> 'Identification' (Weightage: 0.03): If the candidate's name, email, or phone number are provided (either in the resume details or top section), consider the Identity/Personal details complete and award a Score Multiplier of 1 (Score: 0.03).
       - For 'Current Backlogs' (Weightage: 0.05): Since candidates typically do not list '0 backlogs' or 'No backlogs' on their resume, if there is no mention of any backlogs, assume 'Never' and award a Score Multiplier of 1 (Score: 0.05).
       - For 'Technical Skills' (Weightage: 0.05): If the candidate lists a comprehensive set of technical skills and demonstrates their application through complex projects or internships (such as building full-stack applications or RAG systems), infer their proficiency level based on this practical complexity (e.g., if they built RAG systems and full-stack websites, their proficiency is '> 8', awarding a Score Multiplier of 1).
       - For 'Certifications' (Weightage: 0.05): If the duration of certifications is not explicitly listed, infer a reasonable duration based on the certification title (e.g., university credentials like 'IIT Madras — Foundation in Data Science' or 'Diploma in Programming' take '> 6 months' (multiplier 1.0); professional training certifications like 'AI Engineering Professional (IBM)' represent '3-6 months' (multiplier 0.75)).
    6. Sum all calculated component scores to get the total score (as a fraction of 1.0).
    7. Multiply the total sum by 100 to scale the score out of 100.
    8. Write down the detailed lookup and step-by-step mathematical calculations for EVERY component in the 'detailed_calculations' field first.
    9. Ensure that the values in the 'scoring_breakdown' dictionary match the calculations exactly, and the 'score' is the sum of these values multiplied by 100 (rounded to the nearest integer).
    10. If score >= 60, decision is 'approved', else 'rejected'."""),

        HumanMessage(content=f"""Candidate Name: {candidate_name}

    GitHub Profile Data:
    {github_string}

    Resume Candidate Details:
    {candidate_details}{verification_string}

    Please perform the lookup and calculations, and fill in the structured response.""")
    ]

    response = structured_llm.invoke(messages)
    
    # Recalculate score and decision in Python to ensure 100% mathematical consistency
    score_sum = sum(response.scoring_breakdown.values())
    response.score = int(round(score_sum * 100))
    response.decision = "approved" if response.score >= 60 else "rejected"
    
    return response