from enum import StrEnum


class AgentId(StrEnum):
    """Agents that can appear in state. V1 registers three ids.

    Add a member here when a later step introduces an agent. Task and result
    fields use this type, so the state schema stays unchanged.
    """

    SUPERVISOR = "supervisor"
    RESEARCH = "research"
    REVIEWER = "reviewer"


def known_agent_ids() -> frozenset[str]:
    return frozenset(agent.value for agent in AgentId)
