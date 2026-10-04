from orchestration.state import AgentId, Task, known_agent_ids


def test_v1_agents_are_the_registry() -> None:
    assert known_agent_ids() == {"supervisor", "research", "reviewer"}
    assert Task.model_fields["assigned_agent"].annotation is AgentId
    assert Task.model_fields["assigned_agent"].annotation is type(AgentId.RESEARCH)
