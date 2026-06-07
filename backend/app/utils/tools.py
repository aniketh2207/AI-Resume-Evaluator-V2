import os
import asyncio
import httpx
import threading
from typing import List, Optional
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field


from app.core.config import fast_llm, heavy_llm

# ==========================================
# 1. Pydantic Schemas
# ==========================================
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

# ==========================================
# 2. Async GitHub API Helpers
# ==========================================
def parse_github_repo_url(url: str) -> Optional[tuple[str, str]]:
    if not url: return None
    url = url.strip()
    if url.lower().endswith(".git"): url = url[:-4]
    if url.endswith("/"): url = url[:-1]
    parts = url.split("github.com/")
    if len(parts) > 1:
        path = parts[1]
        path_parts = path.split("/")
        if len(path_parts) >= 2:
            return path_parts[0], path_parts[1]
    return None

async def _fetch_single_repo_details(client: httpx.AsyncClient, owner: str, repo_name: str, project_name: Optional[str], headers: dict) -> Optional[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo_name}"
    langs_url = f"https://api.github.com/repos/{owner}/{repo_name}/languages"
    try:
        res = await client.get(url, headers=headers, timeout=5.0)
        if res.status_code != 200: return None
        repo_data = res.json()
        langs_res = await client.get(langs_url, headers=headers, timeout=5.0)
        languages = list(langs_res.json().keys()) if langs_res.status_code == 200 else []
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
    if not projects_to_verify: return False
    repo_clean = repo_name.lower().replace("-", "").replace("_", "")
    for title in projects_to_verify:
        if not title: continue
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
    
    token = os.getenv("GITHUB_TOKEN")
    headers = {"User-Agent": "AI-ATS-Evaluator"}
    if token:
        headers["Authorization"] = f"token {token}"
        
    name, bio, public_repos, created_at = "N/A", "No profile found or rate limits hit", 0, "Unknown"
    repos_data, languages_map = [], {}
    
    async with httpx.AsyncClient() as client:
        if username and str(username).strip().lower() not in ["null", "none", "na", "n/a", ""]:
            try:
                profile_response = await client.get(f"https://api.github.com/users/{username}", headers=headers, timeout=5.0)
                if profile_response.status_code == 200:
                    profile_data = profile_response.json()
                    name = profile_data.get('name') or username
                    bio = profile_data.get('bio') or 'No bio provided'
                    public_repos = profile_data.get('public_repos', 0)
                    created_at = profile_data.get('created_at', 'Unknown')
                    
                    repos_response = await client.get(f"https://api.github.com/users/{username}/repos?per_page=15&sort=updated", headers=headers, timeout=5.0)
                    if repos_response.status_code == 200:
                        repos_data = repos_response.json()
                        matched_repos = [r for r in repos_data if is_project_match(r.get('name', ''), projects_to_verify)]
                        other_repos = [r for r in repos_data if r not in matched_repos]
                        
                        repos_to_query_languages = matched_repos + other_repos[:3]
                        tasks = [_fetch_languages_async(client, username, repo.get('name'), headers) for repo in repos_to_query_languages]
                        languages_map = dict(await asyncio.gather(*tasks))
            except Exception as e:
                print(f"Error fetching profile/repos for {username}: {e}")

        fetched_keys = set()
        if username:
            for repo in repos_data:
                fetched_keys.add((username.lower(), repo.get('name', '').lower()))

        extra_repos_data = []
        if github_project_links:
            repo_tasks = []
            for link_obj in github_project_links:
                parsed = parse_github_repo_url(link_obj.get("repo_url"))
                if parsed:
                    owner, repo_name = parsed
                    key = (owner.lower(), repo_name.lower())
                    if key not in fetched_keys:
                        repo_tasks.append(_fetch_single_repo_details(client, owner, repo_name, link_obj.get("project_name"), headers))
                        fetched_keys.add(key)
            if repo_tasks:
                extra_results = await asyncio.gather(*repo_tasks)
                extra_repos_data = [r for r in extra_results if r is not None]

        repo_summary = "\nProjects & Details (including forks):\n"
        for repo in repos_data:
            repo_name = repo.get('name', 'Unknown')
            description = repo.get('description') or 'No description provided'
            stars = repo.get('stargazers_count', 0)
            last_pushed = repo.get('pushed_at', 'Unknown')
            fork_status = " (Forked Repository)" if repo.get('fork', False) else ""
            
            associated_proj = "N/A"
            if github_project_links:
                for link_obj in github_project_links:
                    parsed = parse_github_repo_url(link_obj.get("repo_url"))
                    if parsed and parsed[1].lower() == repo_name.lower():
                        associated_proj = link_obj.get("project_name")
                        break

            langs = languages_map.get(repo_name, [])
            lang_str = ", ".join(langs) if langs else repo.get('language') or 'N/A'
            
            repo_summary += (f"- {repo_name}{fork_status}:\n  Description: {description}\n  Languages: {lang_str}\n  Stars: {stars}\n  Last Active: {last_pushed}\n")
            if associated_proj != "N/A":
                repo_summary += f"  Associated Resume Project: {associated_proj}\n"

        if extra_repos_data:
            repo_summary += "\nExplicitly Linked Repositories in Projects:\n"
            for repo in extra_repos_data:
                full_name = f"{repo.get('owner', {}).get('login', 'Unknown')}/{repo.get('name', 'Unknown')}"
                fork_status = " (Forked Repository)" if repo.get('fork', False) else ""
                langs = repo.get("languages_list", [])
                lang_str = ", ".join(langs) if langs else repo.get('language') or 'N/A'
                
                repo_summary += (f"- {full_name}{fork_status}:\n  Description: {repo.get('description') or 'No description provided'}\n  Languages: {lang_str}\n  Stars: {repo.get('stargazers_count', 0)}\n  Last Active: {repo.get('pushed_at', 'Unknown')}\n  Associated Resume Project: {repo.get('mapped_project_name', 'Unknown Project')}\n")

    return (f"GitHub Profile for {name} ({username or 'N/A'}):\nAccount Created: {created_at}\nBio: {bio}\nTotal Public Repositories: {public_repos}\n{repo_summary}")

# ==========================================
# 3. LangChain Tool Binding
# ==========================================
@tool
def check_github(
    username: Optional[str] = None, 
    projects_to_verify: Optional[List[str]] = None,
    github_project_links: Optional[List[dict]] = None
) -> str:
    """Fetches comprehensive GitHub profile statistics and detailed repository information."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
        
    if loop and loop.is_running():
        result, exception = None, None
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
        if exception: raise exception
        return result
    else:
        return asyncio.run(_check_github_async(username, projects_to_verify, github_project_links))

# Create the specific LLM instance bound to this tool
github_tools = [check_github]
github_agent_llm = fast_llm.bind_tools(github_tools)

# ==========================================
# 4. Main Agent Function
# ==========================================
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
    response = github_agent_llm.invoke(messages)
    
    if response.tool_calls:
        tool_call = response.tool_calls[0]
        if tool_call['name'] == 'check_github':
            result = check_github.func(**tool_call['args'])
            
            messages.append(response)
            messages.append(ToolMessage(content=result, tool_call_id=tool_call['id']))
            
            # Use fast_llm safely for the structured output formatting
            structured_llm = fast_llm.with_structured_output(GitHubReport)
            return structured_llm.invoke(messages)
            
    return GitHubReport(
        name=username or "N/A",
        total_public_repositories=0,
        account_created="Unknown",
        bio="No profile found or rate limits hit",
        recent_projects=[]
    )