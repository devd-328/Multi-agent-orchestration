from orchestration.state.registry import AgentId

_CONTROL_AGENTS = frozenset({AgentId.SUPERVISOR, AgentId.REVIEWER})


def specialist_agent_ids() -> frozenset[AgentId]:
    """Registered agents that can receive planned tasks.

    The supervisor and the reviewer coordinate work. They are not specialists.
    """

    return frozenset(agent for agent in AgentId if agent not in _CONTROL_AGENTS)
