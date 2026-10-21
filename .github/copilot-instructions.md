# AgentEval project instructions

- Keep modules small and type-annotated; `mypy src/agenteval` from `backend/` must pass in strict mode.
- Format and lint Python with Ruff. Add focused pytest coverage for each behavioral module.
- Never execute task or agent code on the host. All untrusted commands must go through the hardened Docker runner; do not add a host fallback.
- Keep run records comparable across agent, model, and prompt versions.
- Update `docs/DESIGN.md` when changing architecture, security boundaries, storage, or execution trade-offs.
