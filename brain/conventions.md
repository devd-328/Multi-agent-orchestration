# Conventions

Coding agents also follow [agent-instructions.md](agent-instructions.md).

## Code

- Python.
- One agent per module. Agent ids: `supervisor`, `research`, `content`, `marketing`, `events`, `coding`, `ad`, `reviewer`.
- Agents call the shared model interface. No Ollama- or vLLM-specific branches in agent code. See [architecture.md](architecture.md).
- Implement the failure cases in architecture.md. Bounded retries. No silent failures.
- Keep changes small. Reuse an existing module before adding one.

## Layout

Plan only. These folders are not created yet. Python package name: TBD.

```text
brain/            this documentation
<package>/        TBD
  api/            FastAPI entry
  graph/          LangGraph workflow
  agents/         one module per agent
  tools/          tool adapters
  providers/      model provider adapters
  state.py        shared state schema
  config.py       environment-based settings
tests/
```

A new agent adds one module under `agents/`, one spec in [agents.md](agents.md), and one graph entry. A new tool is registered on one agent only.

## Naming

- Files, modules, and functions: `snake_case`.
- Agent ids match [agents.md](agents.md).
- Tools are named by action, not by vendor.

## Testing

- Cover routing, state updates, approve/reject, and bounded failure paths.
- Fake model and tool calls in unit tests.
- Test runner: TBD.

## Logging

- Log agent id, task id, status, and error type.
- Never log secrets, tokens, or environment values. See [security-and-approvals.md](security-and-approvals.md).
- Log format: TBD.

## Config

- Read settings from environment variables.
- Provider name, model name, and endpoints are config.
- Settings loader: TBD.
- Retry limit: TBD. Retries stay finite.
