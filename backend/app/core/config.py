import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai import ChatVertexAI

# Force Windows stdout to handle UTF-8 and Emojis without crashing
sys.stdout.reconfigure(encoding='utf-8')

# Ensure the backend directory is in sys.path so root modules (tools, extractor, assessor) can be imported
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Boot-time configuration check
load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("GOOGLE_API_KEY is not set in environment variables.")

# GCP Configuration
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "E:/AI-Resume-Evaluator-V2/backend/ai-resume-evaluator-498012-305d5547940c.json"
PROJECT_ID = "ai-resume-evaluator-498012"
LOCATION = "us-central1"
SUBSCRIPTION_ID = "ats-gmail-listener"

# Model names
fast_llm_model = os.getenv("FAST_LLM_MODEL", "gemini-2.5-flash")
heavy_llm_model = os.getenv("HEAVY_LLM_MODEL", "gemini-2.5-pro")

print(f"[DEBUG config] Initializing fast_llm (Vertex AI) with model: {fast_llm_model}")
fast_llm = ChatVertexAI(
    model=fast_llm_model,
    temperature=0,
    timeout=120,
    max_retries=1,
    transport='rest'
)

print(f"[DEBUG config] Initializing heavy_llm (Vertex AI) with model: {heavy_llm_model}")
heavy_llm = ChatVertexAI(
    model_name=heavy_llm_model,
    project=PROJECT_ID,
    location=LOCATION,
    temperature=0,
    timeout=120,
    max_retries=1,
    transport='rest'
)

# Initialize MongoDB
cloud_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
db_client = MongoClient(cloud_url)
db = db_client.ats_database
candidates_collection = db.candidates
jobs_collection = db.jobs