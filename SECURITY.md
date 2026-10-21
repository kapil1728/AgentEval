# Security Policy

## Intended use

AgentEval is an evaluation harness for trusted operators running agent and task code in disposable Docker containers. The local Compose configuration is not a multi-user or production deployment:

- The API has no authentication and mounts the host Docker socket.
- The API and dashboard bind to loopback by default. Do not publish these ports or expose the services to untrusted networks.
- Task manifests and configured commands are trusted operator input. Review them before running.
- Docker isolation is defense in depth, not a VM-grade boundary. See [docs/DESIGN.md](docs/DESIGN.md) for the threat model and operational limitations.

## Reporting a vulnerability

Please do not report a suspected vulnerability in a public issue. Use GitHub's **Report a vulnerability** feature on the repository's Security tab when private vulnerability reporting is enabled. If that option is unavailable, contact the maintainer privately at [Kapil.Krishnan@gmail.com](mailto:Kapil.Krishnan@gmail.com) before disclosing details publicly.

Include the affected version or commit, impact, reproduction steps, and any relevant logs with secrets removed.
