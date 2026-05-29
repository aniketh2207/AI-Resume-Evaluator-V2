from pydantic import BaseModel, Field
from typing import Literal  
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
def evaluate_candidate(llm, candidate_name: str, github_data: dict, scoring_markdown: str, resume_text: str = "") -> EvaluationResult:
    structured_llm = llm.with_structured_output(EvaluationResult)
    github_string = json.dumps(github_data, indent=2)

    messages = [
        SystemMessage(content=f"""You are a strict, highly professional technical recruiter and AI Assessor.
    Your job is to evaluate a candidate's GitHub profile and resume content against a specific scoring matrix sheet.

    Here is the exact scoring matrix you MUST follow word-by-word to calculate their score:
    {scoring_markdown}

    INSTRUCTIONS:
    1. Match the candidate's attributes (GPA, certifications, work experience, projects, technical skills, interests, etc. from BOTH their resume and GitHub data) against the exact components, measures, and weights in the matrix.
    2. For each component:
       - Identify the candidate's matching row/measure.
       - Use the specified 'Score Multiplier' and 'Alloted Weightage' to calculate the score: Score = Multiplier * Weightage.
       - If a component is not mentioned, not completed, or not applicable (e.g. psychometric assessments like Attitude/RIASEC/Work Style since they haven't taken the tests, or Patents if they have none), it MUST score 0.
    3. Sum all calculated component scores to get the total score (as a fraction of 1.0).
    4. Multiply the total sum by 100 to scale the score out of 100 (e.g. if sum is 0.645, final score is 65).
    5. Write down the detailed lookup and step-by-step mathematical calculations for EVERY component in the 'detailed_calculations' field first.
    6. Ensure that the values in the 'scoring_breakdown' dictionary match the calculations exactly, and the 'score' is the sum of these values multiplied by 100 (rounded to the nearest integer).
    7. If score >= 60, decision is 'approved', else 'rejected'."""),

        HumanMessage(content=f"""Candidate Name: {candidate_name}

    GitHub Profile Data:
    {github_string}

    Resume Content:
    {resume_text}

    Please perform the lookup and calculations, and fill in the structured response.""")
    ]

    response = structured_llm.invoke(messages)
    
    # Recalculate score and decision in Python to ensure 100% mathematical consistency
    score_sum = sum(response.scoring_breakdown.values())
    response.score = int(round(score_sum * 100))
    response.decision = "approved" if response.score >= 60 else "rejected"
    
    return response