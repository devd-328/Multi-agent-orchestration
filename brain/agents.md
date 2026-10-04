# Agents

Eight agents. Each has one narrow job and a short tool list. No agent does another agent's work.

V1: Supervisor, Research, Reviewer. All others are planned. Workflow: [vision.md](vision.md). Failure rules: [architecture.md](architecture.md). Approval rules: [security-and-approvals.md](security-and-approvals.md).

## Supervisor

Status: V1

- **Role:** Orchestrate. Turn the user goal into a task plan and route work to specialists. Do not research, draft, code, or review.
- **Inputs:** user goal; shared state.
- **Outputs:** task plan; next agent; updated state.
- **Tools:** planning and routing only. No specialist tools. Exact tool names: TBD.
- **Failure:** If the goal is missing or a plan cannot be formed, write an error and stop. Do not call a specialist. Bounded retries (limit TBD).

## Research

Status: V1

- **Role:** Gather information for the assigned task and return findings with sources.
- **Inputs:** assigned task; shared state.
- **Outputs:** findings with sources, or a partial result plus an error.
- **Tools:** read-only retrieval. Exact tools: TBD. No publish, send, or spend tools.
- **Failure:** On tool failure, timeout, or missing information, keep what was found and record the error. Do not invent sources. Bounded retries (limit TBD).

## Content

Status: planned

- **Role:** Draft content for an assigned task. Do not publish.
- **Inputs:** TBD.
- **Outputs:** content draft. Shape TBD.
- **Tools:** TBD. No publishing tools.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Marketing

Status: planned

- **Role:** Draft marketing material for an assigned task. Do not send or publish it.
- **Inputs:** TBD.
- **Outputs:** marketing draft. Shape TBD.
- **Tools:** TBD. No send or publish tools.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Events

Status: planned

- **Role:** Event specialist for an assigned task. V1 research about events stays with the Research Agent.
- **Inputs:** TBD.
- **Outputs:** TBD.
- **Tools:** TBD. No send or publish tools.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Coding

Status: planned

- **Role:** Carry out an assigned coding task. Do not deploy and do not push to main.
- **Inputs:** TBD.
- **Outputs:** TBD.
- **Tools:** TBD. Production deploy and push to main require human approval.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Ad

Status: planned

- **Role:** Draft ad material for an assigned task. Do not spend money and do not publish ads.
- **Inputs:** TBD.
- **Outputs:** ad draft. Shape TBD.
- **Tools:** TBD. Paid ads require human approval.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Reviewer

Status: V1

- **Role:** Check specialist output against the user goal. Approve or reject with notes. Do not redo the specialist work.
- **Inputs:** user goal; specialist output; shared state.
- **Outputs:** `approved` or `rejected`, plus notes.
- **Tools:** read-only. Exact tools: TBD. No side-effect tools.
- **Failure:** Missing or invalid output is a rejection with notes. Rejection returns to the Supervisor. Retries are bounded (limit TBD). Do not loop without a bound.
