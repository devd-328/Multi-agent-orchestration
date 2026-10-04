# Stack

- **Date:** 2026-10-04
- **Status:** accepted

## Context

The system is an open-source, modular multi-agent workflow. V1 is defined in [vision.md](../vision.md).

## Decision

- Python
- FastAPI
- LangGraph
- Model provider: Ollama now, vLLM later, selected by config
- Qdrant
- PostgreSQL
- MCP (V1 non-goal; roadmap step 14)
- Langfuse (roadmap step 8; not part of the V1 workflow)

Agent code stays provider-agnostic. See [architecture.md](../architecture.md).

## Why

- LangGraph runs the goal -> supervisor -> specialists -> reviewer flow.
- Ollama is the current local model provider. vLLM is the later provider. Agents must not branch on either one.
- Langfuse is reserved for observability (roadmap step 8).
- MCP is reserved for later tool integration (roadmap step 14).

Why FastAPI, Qdrant, and PostgreSQL were chosen over alternatives: TBD. Their roles beyond "part of the stack" are TBD for Qdrant and PostgreSQL.

## Consequences

- V1 does not implement memory, MCP, or the planned specialist agents. Langfuse is later (roadmap step 8).
- A provider change is a config and adapter change, not an agent rewrite.
