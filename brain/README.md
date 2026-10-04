# Brain

Single source of truth for the plan, architecture, and conventions.

**Read [RULES.md](RULES.md) before any task.**

## Reading order

1. [RULES.md](RULES.md): mandatory rulebook (anti-hallucination and coding)
2. [vision.md](vision.md): goal, scope, non-goals, V1 definition
3. [architecture.md](architecture.md): components, data flow, boundaries, stack, provider rule
4. [roadmap.md](roadmap.md): build order and status
5. [agents.md](agents.md): one spec per agent
6. [state.md](state.md): shared LangGraph state
7. [conventions.md](conventions.md): coding, layout, naming, testing, logging, config
8. [security-and-approvals.md](security-and-approvals.md): secrets, untrusted content, tool permissions, human approval
9. [agent-instructions.md](agent-instructions.md): pointer to RULES.md for coding agents
10. [progress.md](progress.md): done, in progress, blocked, next step
11. [decisions/stack.md](decisions/stack.md): stack choice
12. [decisions/template.md](decisions/template.md): template for new decision records

Add a decision record only after a choice is accepted. Use the template. Leave open points as `TBD` in the file that owns them.
