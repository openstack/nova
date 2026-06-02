.. _agentic-coding:

==============
Agentic Coding
==============

This document covers Nova's conventions for AI-assisted development: how
shared project guidance is structured, what belongs in ``AGENTS.md``, and how
contributors should configure local tooling.

Philosophy
==========

Nova's approach to agentic coding is minimal scaffolding and native
discovery: if a convention must be followed it is documented in human-readable
prose that agents can find via normal file exploration. Agent context files
are kept short so they route rather than encode knowledge.

Principles
==========

Tool-neutral documentation
--------------------------

Nova contributor documentation is written for contributors first. Mention
specific AI coding tools only when documenting tool-specific behavior or local
configuration examples. Prefer general wording such as "contributors" and
"readers" when the guidance applies to everyone.

Canonical human-readable docs
-----------------------------

Project rules and conventions belong in human-readable documentation,
``HACKING.rst``, or deterministic tooling. Avoid adding agent-only project
rules. If a rule matters for the project, document it where contributors can
find it and let agents discover the same source.

Deterministic enforcement
-------------------------

Prefer deterministic checks over prose-only instructions. When a convention can
be enforced by a hacking check, linter, test fixture, or validation script, use
that mechanism instead of relying on a person or an agent to remember prose.

Minimal routing
---------------

Root ``AGENTS.md`` is a compact routing layer plus high-signal guardrails. It is
not a tutorial, not a contributor guide, and not a replacement for the project
documentation it links to. Keep it short enough that tools will read it and
then follow its pointers to authoritative sources.

AGENTS.md
=========

``AGENTS.md`` at the repository root provides terse routing pointers and a
small set of guardrails for common incorrect actions. It should contain only
information that is difficult for an agent to discover from source, config, or
existing docs, and that is likely to prevent an incorrect action.

Appropriate content includes:

* pointers to authoritative contributor, testing, and subsystem docs;
* guardrails for common incorrect actions not obvious from source or config;

Avoid adding:

* long-form explanations;
* summaries of docs that may drift from the source of truth;
* rules already enforced by ``tox -e pep8`` or other validation;
* personal preferences or in-progress notes.

When ``AGENTS.md`` approaches 100 lines, prune existing content before adding
more, consolidating into contributor docs as required.

Local scratch files
===================

Use ``.tmp/`` for local plans, scratch notes, generated prompts, and other
ephemeral output from coding tools. The directory is gitignored and should not
appear in upstream review history.

Local tool configuration
========================

Local override files are tool-specific preferences. There is currently no
standard format or name for a project-local override file. Some tools support
files such as ``CLAUDE.local.md`` or ``AGENTS.override.md``; others use
different names or do not support local instruction files. Configure these
locally according to the tool being used.

Do not assume another contributor's tool will read the same local files or use
the same precedence rules. Shared project guidance belongs in the checked-in
Nova docs and root ``AGENTS.md`` routing layer.

Some tools do not natively support ``AGENTS.md`` and instead look for a
tool-specific file at the repository root. For these tools, the recommended
approach is a local symlink so that checked-in project guidance remains in
``AGENTS.md`` without duplicating it.

``CLAUDE.md`` is gitignored so contributors can maintain a personal file
without it appearing in upstream review history. If a tool expects
``CLAUDE.md`` at the root, create a local symlink::

    ln -s AGENTS.md CLAUDE.md

Tool invocation
===============

Assume project tools are installed and available on ``$PATH``. Invoke them
directly in examples and automation, for example::

    tox -e pep8

Do not install tools system-wide with a package manager or ``pip`` (``apt
install``, ``dnf install``, ``pip install``, ``pip install --user``, and
similar). If a required Python tool is not on ``$PATH``, ``uvx`` or ``pipx
run`` are acceptable ephemeral fallbacks. Do not use those wrappers as the
primary invocation for project commands.

Commit messages
===============

See :doc:`/contributor/commit-messages` for Nova commit message guidance,
including Developer Certificate of Origin sign-off, Gerrit ``Change-Id``
footers, and AI attribution trailers.
