import os
import asyncio
import httpx
from typing import List, Optional
from dotenv import load_dotenv
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

# Boot-time configuration check
load_dotenv()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "E:/AI-Resume-Evaluator-V2/backend/ai-resume-evaluator-498012-305d5547940c.json"

# Setting up the LLM using Vertex AI
llm = ChatVertexAI(
    model_name="gemini-2.5-flash",
    project="ai-resume-evaluator-498012",
    location="us-central1",
    temperature=0
)

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
def parse_github_repo_url(url: str) -> Optional[tuple[str, str]]:
    if not url:
        return None
    url = url.strip()
    if url.lower().endswith(".git"):
        url = url[:-4]
    if url.endswith("/"):
        url = url[:-1]
    parts = url.split("github.com/")
    if len(parts) > 1:
        path = parts[1]
        path_parts = path.split("/")
        if len(path_parts) >= 2:
            owner = path_parts[0]
            repo = path_parts[1]
            return owner, repo
    return None

async def _fetch_single_repo_details(client: httpx.AsyncClient, owner: str, repo_name: str, project_name: Optional[str], headers: dict) -> Optional[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo_name}"
    langs_url = f"https://api.github.com/repos/{owner}/{repo_name}/languages"
    try:
        res = await client.get(url, headers=headers, timeout=5.0)
        if res.status_code != 200:
            return None
        repo_data = res.json()
        langs_res = await client.get(langs_url, headers=headers, timeout=5.0)
        languages = []
        if langs_res.status_code == 200:
            languages = list(langs_res.json().keys())
        repo_data["languages_list"] = languages
        repo_data["mapped_project_name"] = project_name
        return repo_data
    except Exception:
        return None

async def _fetch_languages_async(client: httpx.AsyncClient, username: str, repo_name: str, headers: dict) -> tuple:
    url = f"https://api.github.com/repos/{username}/{repo_name}/languages"
    try:
        response = await client.get(url, headers=headers, timeout=5.0)
        if response.status_code == 200:
            return repo_name, list(response.json().keys())
    except Exception:
        pass
    return repo_name, []

def is_project_match(repo_name: str, projects_to_verify: Optional[List[str]]) -> bool:
    if not projects_to_verify:
        return False
    repo_clean = repo_name.lower().replace("-", "").replace("_", "")
    for title in projects_to_verify:
        if not title:
            continue
        # Split title by common delimiters and then into words
        base_title = title.split("—")[0].split("-")[0].split(":")[0].split("|")[0].strip()
        words = [w.lower().strip() for w in base_title.split() if w.strip()]
        for word in words:
            if len(word) >= 3:
                word_clean = word.replace("-", "").replace("_", "")
                if word_clean in repo_clean or repo_clean in word_clean:
                    return True
    return False

async def _check_github_async(
    username: Optional[str], 
    projects_to_verify: Optional[List[str]] = None,
    github_project_links: Optional[List[dict]] = None
) -> str:
    print(f"\n[TOOL TRIGGERED] Fetching live GitHub data. Username: {username}, Links Count: {len(github_project_links) if github_project_links else 0}...")
    
    # Optional GITHUB_TOKEN support
    token = os.getenv("GITHUB_TOKEN")
    headers = {"User-Agent": "AI-ATS-Evaluator"}
    if token:
        headers["Authorization"] = f"token {token}"
        
    name = "N/A"
    bio = "No profile found or rate limits hit"
    public_repos = 0
    created_at = "Unknown"
    
    repos_data = []
    languages_map = {}
    
    async with httpx.AsyncClient() as client:
        # Fetch user profile if username is provided
        if username and str(username).strip().lower() not in ["null", "none", "na", "n/a", ""]:
            profile_url = f"https://api.github.com/users/{username}"
            try:
                profile_response = await client.get(profile_url, headers=headers, timeout=5.0)
                if profile_response.status_code == 200:
                    profile_data = profile_response.json()
                    name = profile_data.get('name') or username
                    bio = profile_data.get('bio') or 'No bio provided'
                    public_repos = profile_data.get('public_repos', 0)
                    created_at = profile_data.get('created_at', 'Unknown')
                    
                    # Fetch repositories (up to 15 recent projects)
                    repos_url = f"https://api.github.com/users/{username}/repos?per_page=15&sort=updated"
                    repos_response = await client.get(repos_url, headers=headers, timeout=5.0)
                    if repos_response.status_code == 200:
                        repos_data = repos_response.json()
                        
                        # Determine which repos require detailed language breakdowns
                        matched_repos = []
                        other_repos = []
                        for repo in repos_data:
                            repo_name = repo.get('name', '')
                            if is_project_match(repo_name, projects_to_verify):
                                matched_repos.append(repo)
                            else:
                                other_repos.append(repo)
                        
                        # Query detailed languages for matched repos, plus up to top 3 active unmatched repos
                        repos_to_query_languages = matched_repos + other_repos[:3]
                        tasks = [_fetch_languages_async(client, username, repo.get('name'), headers) for repo in repos_to_query_languages]
                        languages_results = await asyncio.gather(*tasks)
                        languages_map = dict(languages_results)
            except Exception as e:
                print(f"Error fetching profile/repos for {username}: {e}")

        # Keep track of fetched repo keys as (owner.lower(), repo_name.lower())
        fetched_keys = set()
        if username:
            username_lower = username.lower()
            for repo in repos_data:
                repo_name = repo.get('name', '').lower()
                fetched_keys.add((username_lower, repo_name))

        # Explicitly fetch details for direct repository URLs from resume projects
        extra_repos_data = []
        if github_project_links:
            parsed_repos = []
            for link_obj in github_project_links:
                url = link_obj.get("repo_url")
                parsed = parse_github_repo_url(url)
                if parsed:
                    parsed_repos.append((parsed[0], parsed[1], link_obj.get("project_name")))
            
            repo_tasks = []
            for owner, repo_name, proj_name in parsed_repos:
                key = (owner.lower(), repo_name.lower())
                if key not in fetched_keys:
                    repo_tasks.append(_fetch_single_repo_details(client, owner, repo_name, proj_name, headers))
                    fetched_keys.add(key)
            
            if repo_tasks:
                extra_results = await asyncio.gather(*repo_tasks)
                extra_repos_data = [r for r in extra_results if r is not None]

        # Construct repo summary
        repo_summary = "\nProjects & Details (including forks):\n"
        
        # 1. Output profile repos (if any)
        for repo in repos_data:
            repo_name = repo.get('name', 'Unknown')
            description = repo.get('description') or 'No description provided'
            stars = repo.get('stargazers_count', 0)
            last_pushed = repo.get('pushed_at', 'Unknown')
            is_fork = repo.get('fork', False)
            fork_status = " (Forked Repository)" if is_fork else ""
            
            associated_proj = "N/A"
            if github_project_links:
                for link_obj in github_project_links:
                    parsed = parse_github_repo_url(link_obj.get("repo_url"))
                    if parsed and parsed[1].lower() == repo_name.lower():
                        associated_proj = link_obj.get("project_name")
                        break

            if repo_name in languages_map:
                langs = languages_map[repo_name]
                lang_str = ", ".join(langs) if langs else repo.get('language') or 'N/A'
            else:
                primary_lang = repo.get('language')
                lang_str = primary_lang if primary_lang else 'N/A'
            
            repo_summary += (
                f"- {repo_name}{fork_status}:\n"
                f"  Description: {description}\n"
                f"  Languages: {lang_str}\n"
                f"  Stars: {stars}\n"
                f"  Last Active: {last_pushed}\n"
            )
            if associated_proj != "N/A":
                repo_summary += f"  Associated Resume Project: {associated_proj}\n"

        # 2. Output extra explicitly linked repos (if any)
        if extra_repos_data:
            repo_summary += "\nExplicitly Linked Repositories in Projects:\n"
            for repo in extra_repos_data:
                repo_name = repo.get('name', 'Unknown')
                owner = repo.get('owner', {}).get('login', 'Unknown')
                full_name = f"{owner}/{repo_name}"
                description = repo.get('description') or 'No description provided'
                stars = repo.get('stargazers_count', 0)
                last_pushed = repo.get('pushed_at', 'Unknown')
                is_fork = repo.get('fork', False)
                fork_status = " (Forked Repository)" if is_fork else ""
                
                langs = repo.get("languages_list", [])
                lang_str = ", ".join(langs) if langs else repo.get('language') or 'N/A'
                proj_name = repo.get("mapped_project_name") or "Unknown Project"
                
                repo_summary += (
                    f"- {full_name}{fork_status}:\n"
                    f"  Description: {description}\n"
                    f"  Languages: {lang_str}\n"
                    f"  Stars: {stars}\n"
                    f"  Last Active: {last_pushed}\n"
                    f"  Associated Resume Project: {proj_name}\n"
                )

    final_report = (
        f"GitHub Profile for {name} ({username or 'N/A'}):\n"
        f"Account Created: {created_at}\n"
        f"Bio: {bio}\n"
        f"Total Public Repositories: {public_repos}\n"
        f"{repo_summary}"
    )
    
    return final_report

@tool
def check_github(
    username: Optional[str] = None, 
    projects_to_verify: Optional[List[str]] = None,
    github_project_links: Optional[List[dict]] = None
) -> str:
    """Fetches comprehensive GitHub profile statistics, and detailed repository information for specified project links or candidate's public repositories."""
    import threading
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
        
    if loop and loop.is_running():
        # Spin up a thread to run the async task with its own event loop to avoid event loop conflicts in FastAPI/Uvicorn
        result = None
        exception = None
        def target():
            nonlocal result, exception
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                result = new_loop.run_until_complete(_check_github_async(username, projects_to_verify, github_project_links))
            except Exception as e:
                exception = e
            finally:
                new_loop.close()
        
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()
        if exception:
            raise exception
        return result
    else:
        return asyncio.run(_check_github_async(username, projects_to_verify, github_project_links))

# Binding the tool to the LLM
tools = [check_github]
llm_with_tools = llm.bind_tools(tools)

# The GitHub Agent returning structured output
def run_github_agent(
    username: Optional[str] = None, 
    projects_to_verify: Optional[List[str]] = None,
    github_project_links: Optional[List[dict]] = None
) -> GitHubReport:
    context = ""
    import json
    if projects_to_verify:
        context += f" Here are the candidate's resume projects to verify: {', '.join(projects_to_verify)}."
    if github_project_links:
        context += f" Here are the candidate's specific GitHub repository links to verify: {json.dumps(github_project_links)}."

    messages = [
        SystemMessage(content="You are a highly professional AI assistant. Fetch the candidate's GitHub details and return a structured JSON report containing their name, total public repositories, and all listed recent projects. Pass projects_to_verify and github_project_links to the check_github tool if available."),
        HumanMessage(content=f"Check the github status of the candidate, username - {username or 'N/A'}.{context} Return the function message.")
    ]
    
    print(f"Contacting Gemini (GitHub Agent) for username: {username or 'N/A'}...")
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
        name=username or "N/A",
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
