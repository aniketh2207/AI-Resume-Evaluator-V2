# AI Resume Evaluator (Version 2) - Multi-Agent Architecture

## Overview
This repository contains the V2 architecture for an Applicant Tracking System (ATS) Evaluator. Moving away from the deterministic NLP heuristics of V1, this system leverages a **Multi-Agent LLM architecture** orchestrated by LangGraph to semantically read, verify, and score candidate resumes against dynamic Job Descriptions.

## The Tech Stack
* **Orchestration:** LangChain & LangGraph
* **LLM Engine:** Google Gemini Ecosystem (`gemini-2.5-flash` for vision/tools, `gemini-2.5-pro` for deep reasoning)
* **Vision/Extraction:** Native LLM Multimodality (Bypassing standard PDF text extraction)
* **Backend:** Python

## The Multi-Agent Pipeline (The Committee)
The system operates using a state machine where a single `CandidateState` dictionary is passed through four specialized AI nodes:

1. **Agent 1: The Gatekeeper (Vision & Extraction)**
   * **Role:** Reads the raw resume image to bypass formatting/column bugs.
   * **Task:** Extracts candidate details, URLs, and categorizes the candidate (e.g., Student vs. >1 Year Experience) to determine the downstream scoring matrix.
   
2. **Agent 2: The Investigator (External Verification)**
   * **Role:** The fact-checker utilizing LangChain Tool Calling.
   * **Task:** Triggers Python `requests` to hit the public GitHub API, pulling live repository data, primary languages, and commit statistics to verify project legitimacy.

3. **Agent 3: The Technical Assessor (Semantic Scoring)**
   * **Role:** The heavy reasoning engine.
   * **Task:** Cross-references extracted skills against project descriptions to penalize keyword-stuffing. Applies dynamic Excel-based scoring matrices via RAG to calculate precise scores based on the candidate's experience level.

4. **Agent 4: The Judge (Final Synthesis)**
   * **Role:** The communicator.
   * **Task:** Aggregates findings from the Assessor and Investigator to calculate the final numerical score and write a crisp, actionable justification for the Hiring Manager dashboard.

## Local Setup & Installation

1. **Clone the repository and create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate