import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
load_dotenv() # this loads the API key


# setting up the LLM
# temperature is set to 0 as we dont want any creative answers
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

@tool
def check_github(username:str):
    """ So this tool checks the github of the provided username and checks the validty of the user and returns the response """
    # this is a test for the llm to call the method
    return f"""
    Valid Github username : {username}. You have 12 public repositories and a total of 100 followers.
    """

#binding the tool to the llm agent 
tools = [check_github]
llm_with_tools = llm.bind_tools(tools)

# now we Invoke the tools 
messages = [
    SystemMessage(content="You are a highly professional AI assistant."),
    HumanMessage(content="Check the github status of Aniketh, username - aniketh2207 and return the function message")
]

print("Contacting Gemini...")
response = llm_with_tools.invoke(messages)
print(response.tool_calls)

#getting the content of the response 

tool_call = response.tool_calls[0]
if tool_call['name'] == 'check_github':
    result = check_github.invoke(tool_call['args'])

messages.append(response)# this logs the AI tool request AIMessage
messages.append(ToolMessage(content=result, tool_call_id=tool_call['id']))# this logs the tool response

response2 = llm_with_tools.invoke(messages) # this invokes the function call


print("\n--- GEMINI'S RESPONSE ---")
print(response2.content)

