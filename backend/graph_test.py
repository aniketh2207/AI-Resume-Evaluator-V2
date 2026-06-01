from typing import TypedDict
from langgraph.graph import StateGraph,START,END

class CandidateState(TypedDict):
    candidate_name : str
    status : str 
    category: str


def extractor_node(state : CandidateState):
    return {
        "category" : "experienced",
        "candidate_name":"Aniketh"
    }
    
def investigator_node(state: CandidateState):
    print("Investigating Github....")
    return {
        "status": "approved"
    }
def judge_node(state: CandidateState):
    print("Judging Candidate....")
    if state["status"] == "approved":
        return{
            "status" : "approved"
        }
    else:
        return{
            "status" : "rejected"
        }


def route_candidate(state:CandidateState):
    if state['category'] == "student":
        return "judge"
    else:
        return "investigator"

workflow = StateGraph(CandidateState)
workflow.add_node("extractor",extractor_node)
workflow.add_node("investigator",investigator_node)
workflow.add_node("judge",judge_node)

workflow.add_edge(START, "extractor")
workflow.add_conditional_edges(
    "extractor",
    route_candidate,
    ["judge", "investigator"]
)
workflow.add_edge("investigator","judge")
workflow.add_edge("judge",END)

app = workflow.compile()

input = CandidateState(candidate_name="", status="")
result = app.invoke(input)
print(result)

