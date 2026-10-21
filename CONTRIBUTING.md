# Contributing

Thank you for helping improve AgentEval. Bug reports, focused fixes, documentation improvements, and reproducible test cases are welcome.

## Before opening an issue

- Search existing issues to avoid duplicates.
- Include the AgentEval version or commit, operating system, Docker version, and relevant command output.
- Remove credentials, tokens, private task data, and other sensitive information from logs.
- Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

## Development setup

Requirements:

- Python 3.12 or 3.13
- Node.js 20 and npm
- Docker Desktop or Docker Engine with Compose v2 and a running Linux-container daemon for end-to-end sandbox checks

Install the backend development dependencies from the repository root:

```sh
python -m pip install -e "backend[dev]"
```

Install the dashboard dependencies:

```sh
cd dashboard
npm ci
```

## Checks before submitting

From `backend/`:

```sh
pytest
ruff check .
ruff format --check .
mypy src/agenteval
```

From `dashboard/`:

```sh
npm test
npm run build
npm audit
```

For changes to the Docker workflow, also build and exercise the local stack using the commands in [README.md](README.md).

## Pull request guidance

- Keep changes focused and explain the user-visible behavior or rationale.
- Add or update tests for behavior changes.
- Update relevant documentation, including [docs/DESIGN.md](docs/DESIGN.md) for architecture, security boundaries, storage, or execution trade-offs.
- Never execute task or agent code directly on the host. Use the Docker sandbox workflow; do not add a host execution fallback.
- Do not include local databases, secrets, generated build output, or unrelated formatting changes.
- Describe the checks you ran and any limitations that remain.
