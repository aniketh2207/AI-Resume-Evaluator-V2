import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv() # this loads the API key

#setting up Agent 1 
# temperature is set to 0 as we dont want any creative answers
llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)

#creating the payload messages
messages = [
    SystemMessage(content="You are a highly professional AI assistant."),
    HumanMessage(content="My name is Aniketh and I am building a Multi-Agent ATS. Say a quick hello!")
]

# firing the google servers 
print("Contacting Gemini...")
response = llm.invoke(messages)     # this loads the AI response into response variable

#printing the response

print("\n--- GEMINI'S RESPONSE ---")
print(response.content)    # this gets the AI response