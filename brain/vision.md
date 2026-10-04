# Vision

## Goal

An open-source, modular multi-agent system. A user states a goal. The system plans the work, runs specialist agents, reviews the result, and returns a final answer.

## V1

Workflow:

User Goal -> Supervisor -> Research Agent -> Reviewer -> Final Answer

Example goal: "Research upcoming technology events and summarize the useful findings with sources."

V1 agents are Supervisor, Research, and Reviewer. Specs: [agents.md](agents.md).

## Scope

V1 returns sourced research findings for one user goal. The system stays modular so a later agent or tool can be added without a redesign. Components and rules: [architecture.md](architecture.md).

## Non-goals for V1

- Content, Marketing, Events, Coding, and Ad agents
- Memory
- MCP
- Image/video

Those items are later roadmap steps. See [roadmap.md](roadmap.md).
