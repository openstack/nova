# AGENTS.md — agent routing index

Agents: explore the repo directly; this file is a routing index, not a contributor guide.

## Workflow

**Session memory:** Write plans, notes, and ephemeral files to `.tmp/`
(gitignored) rather than the system temporary directory.

**For non-trivial planning**, inspect deps and tooling:
`pyproject.toml` · `tox.ini` · `.pre-commit-config.yaml` ·
`requirements.txt` · `test-requirements.txt`

**Tests**: Use `tox` or `stestr`; never use `pytest`.
  Invoke them directly, for example `tox -e pep8`.
  Assume project tools are installed and available on `$PATH`.

**Routing:**
- Repo layout: [doc/source/contributor/repo-overview.rst](doc/source/contributor/repo-overview.rst)
- Style, hacking, checks: [HACKING.rst](HACKING.rst)
- RPC: [rpc.rst](doc/source/reference/rpc.rst)
- Conductor: [conductor.rst](doc/source/reference/conductor.rst)
- REST API: [api.rst](doc/source/contributor/api.rst)
- Microversions: [microversions.rst](doc/source/contributor/microversions.rst) / [api-microversion-history.rst](doc/source/reference/api-microversion-history.rst)
- Concurrency/threading: [threading.rst](doc/source/reference/threading.rst) / [concurrency.rst](doc/source/admin/concurrency.rst)
- Test conventions, fixtures: [HACKING.rst](HACKING.rst) / [testing.rst](doc/source/contributor/testing.rst)
- Dependencies and packaging: [dependencies.rst](doc/source/contributor/dependencies.rst)
- Documentation: [documentation.rst](doc/source/contributor/documentation.rst)
- Commit messages: [commit-messages.rst](doc/source/contributor/commit-messages.rst)
- Agentic coding conventions: [agentic-coding.rst](doc/source/contributor/agentic-coding.rst)

## Guardrails

- **Tools:** Do not install missing tools with a package manager or `pip`
- **Concurrency**: Do not introduce asyncio or new eventlet usage. Review the
  threading and concurrency docs when changing concurrent code.
- **Review**: Nova uses Gerrit, not GitHub PRs. Series are always unsquashed;
  each commit must be independently testable and correct.
- **Git**: Read-only operations (`git log`, `git diff`, `git status`) are fine.
  Do not run mutating operations (`add`, `commit`, `reset`, `checkout`, `push`,
  `stash`, `merge`, `rebase`, etc.) unless explicitly instructed to do so.
