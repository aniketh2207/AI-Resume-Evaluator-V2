import os
from dotenv import load_dotenv
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv() # this loads the API key

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "E:/AI-Resume-Evaluator-V2/backend/ai-resume-evaluator-498012-305d5547940c.json"

# setting up Agent 1 using ChatVertexAI
# temperature is set to 0 as we dont want any creative answers
llm = ChatVertexAI(
    model_name="gemini-2.5-flash",
    project="ai-resume-evaluator-498012",
    location="us-central1",
    temperature=0
)

# creating the payload messages
messages = [
    SystemMessage(content="You are a highly professional AI assistant."),
    HumanMessage(content="My name is Aniketh and I am building a Multi-Agent ATS. Say a quick hello!")
]

# firing the google servers 
print("Contacting Gemini...")
response = llm.invoke(messages)     # this loads the AI response into response variable

# printing the response
print("\n--- GEMINI'S RESPONSE ---")
print(response.content)    # this gets the AI response