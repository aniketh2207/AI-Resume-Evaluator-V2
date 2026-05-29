import os
import asyncio
import httpx
from typing import List, Optional
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

# Boot-time configuration check
load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("GOOGLE_API_KEY is not set in environment variables.")

# Setting up the LLM
llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0)

# Define Structured Output Schemas
class ProjectDetails(BaseModel):
    name: str = Field(description="The name of the project repository")
    languages: List[str] = Field(description="List of programming languages used in the repository")
    stars: int = Field(description="The number of stars of the repository")
    last_active: str = Field(description="The timestamp of the last activity/push to this repository")

class GitHubReport(BaseModel):
    name: str = Field(description="The profile name of the user")
    total_public_repositories: int = Field(description="The total count of public repositories")
    account_created: str = Field(description="The date the GitHub account was created")
    bio: str = Field(description="The candidate's profile bio")
    recent_projects: List[ProjectDetails] = Field(description="Detailed list of project repositories (including forks)")

# Asynchronous helper functions for API calls
async def _fetch_languages_async(client: httpx.AsyncClient, username: str, repo_name: str, headers: dict) -> tuple:
    url = f"https://api.github.com/repos/{username}/{repo_name}/languages"
    try:
        response = await client.get(url, headers=headers, timeout=5.0)
        if response.status_code == 200:
            return repo_name, list(response.json().keys())
    except Exception:
        pass
    return repo_name, []

async def _check_github_async(username: str) -> str:
    print(f"\n[TOOL TRIGGERED] Fetching live GitHub data for: {username}...")
    
    # Optional GITHUB_TOKEN support
    token = os.getenv("GITHUB_TOKEN")
    headers = {"User-Agent": "AI-ATS-Evaluator"}
    if token:
        headers["Authorization"] = f"token {token}"
        
    profile_url = f"https://api.github.com/users/{username}"
    
    async with httpx.AsyncClient() as client:
        # Fetch user profile
        profile_response = await client.get(profile_url, headers=headers, timeout=5.0)
        
        if profile_response.status_code == 404:
            return f"Candidate GitHub profile '{username}' not found."
        elif profile_response.status_code == 403:
            return "GitHub API rate limit exceeded. Please try again later."
        elif profile_response.status_code != 200:
            return f"GitHub API failed with status code: {profile_response.status_code}"
            
        profile_data = profile_response.json() 
        name = profile_data.get('name') or username
        bio = profile_data.get('bio') or 'No bio provided'
        public_repos = profile_data.get('public_repos', 0)
        created_at = profile_data.get('created_at', 'Unknown')
        
        # Fetch repositories (up to 15 recent projects)
        repos_url = f"https://api.github.com/users/{username}/repos?per_page=15&sort=updated"
        repos_response = await client.get(repos_url, headers=headers, timeout=5.0)
        
        if repos_response.status_code == 403:
            return "GitHub API rate limit exceeded while fetching repositories."
        
        repo_summary = ""
        if repos_response.status_code == 200:
            repos_data = repos_response.json()
            
            # Include all public repositories, including forks (which might be team projects)
            top_repos = repos_data
            
            # Asynchronously fetch language breakdowns in parallel
            tasks = [_fetch_languages_async(client, username, repo.get('name'), headers) for repo in top_repos]
            languages_results = await asyncio.gather(*tasks)
            languages_map = dict(languages_results)
            
            repo_summary = "\nProjects & Details (including forks):\n"
            for repo in top_repos:
                repo_name = repo.get('name', 'Unknown')
                description = repo.get('description') or 'No description provided'
                stars = repo.get('stargazers_count', 0)
                last_pushed = repo.get('pushed_at', 'Unknown')
                
                langs = languages_map.get(repo_name, [])
                lang_str = ", ".join(langs) if langs else repo.get('language') or 'N/A'
                
                repo_summary += (
                    f"- {repo_name}:\n"
                    f"  Description: {description}\n"
                    f"  Languages: {lang_str}\n"
                    f"  Stars: {stars}\n"
                    f"  Last Active: {last_pushed}\n"
                )
                
    final_report = (
        f"GitHub Profile for {name} ({username}):\n"
        f"Account Created: {created_at}\n"
        f"Bio: {bio}\n"
        f"Total Public Repositories: {public_repos}\n"
        f"{repo_summary}"
    )
    
    return final_report

@tool
def check_github(username: str) -> str:
    """Fetches comprehensive GitHub profile statistics (including account creation date, bio), and detailed language and star breakdowns for the candidate's public repositories (including forks)."""
    # Execute the async function synchronously using asyncio.run
    return asyncio.run(_check_github_async(username))

# Binding the tool to the LLM
tools = [check_github]
llm_with_tools = llm.bind_tools(tools)

# The GitHub Agent returning structured output
def run_github_agent(username: str) -> GitHubReport:
    messages = [
        SystemMessage(content="You are a highly professional AI assistant. Fetch the candidate's GitHub details and return a structured JSON report containing their name, total public repositories, and all listed recent projects."),
        HumanMessage(content=f"Check the github status of the candidate, username - {username} and return the function message")
    ]
    
    print(f"Contacting Gemini (GitHub Agent) for username: {username}...")
    response = llm_with_tools.invoke(messages)
    
    if response.tool_calls:
        tool_call = response.tool_calls[0]
        if tool_call['name'] == 'check_github':
            # Run tool directly via the underlying function
            result = check_github.func(**tool_call['args'])
            
            messages.append(response)
            messages.append(ToolMessage(content=result, tool_call_id=tool_call['id']))
            
            # Format the output into the GitHubReport Pydantic schema
            structured_llm = llm.with_structured_output(GitHubReport)
            response2 = structured_llm.invoke(messages)
            return response2
            
    return GitHubReport(
        name=username,
        total_public_repositories=0,
        account_created="Unknown",
        bio="No profile found or rate limits hit",
        recent_projects=[]
    )

if __name__ == "__main__":
    # Test the agent directly
    print("Testing GitHub Agent...")
    result = run_github_agent("aniketh2207")
    print("\n--- GEMINI'S RESPONSE ---")
    import pprint
    pprint.pprint(result.model_dump())
