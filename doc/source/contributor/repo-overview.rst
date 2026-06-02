.. _repo-overview:

=============
Repo Overview
=============

A terse map of the Nova repository for contributor orientation.

Root Files
==========

``HACKING.rst``
    Nova coding style rules and N-check descriptions.
``AGENTS.md``
    Agent routing index and policy.
``.tmp/``
    Gitignored local scratch directory for notes, plans, and ephemeral output.
``tox.ini``
    Test environments, commands, and environment variables.
``pyproject.toml``
    Build system (pbr), mypy configuration, optional dependency groups.
``.pre-commit-config.yaml``
    Linting hooks: hacking/flake8, mypy, codespell, sphinx-lint.
``requirements.txt`` / ``test-requirements.txt``
    Runtime and test dependencies (pinned via OpenStack constraints).

nova/ Package
=============

``nova/api/``
    REST API layer: WSGI, routing, controllers, policy enforcement.
``nova/compute/``
    Compute manager and resource tracker; runs on hypervisor hosts.
``nova/conductor/``
    Conductor manager: cross-service orchestration and DB operations.
``nova/scheduler/``
    Scheduler, filters, and weighers for instance placement decisions.
``nova/virt/``
    Hypervisor driver interface and per-driver implementations.
``nova/db/``
    Database API abstraction layer (SQLAlchemy models and API).
``nova/objects/``
    Versioned objects: the canonical data model for RPC payloads.
``nova/image/``
    Glance integration: image metadata and download for provisioning.
``nova/volume/``
    Cinder integration: volume attachment and detachment operations.
``nova/network/``
    Neutron integration; no in-tree networking logic.
``nova/cmd/``
    Entry points for Nova services (``nova-api``, ``nova-compute``,
    ``nova-conductor``, ``nova-scheduler``, etc.).
``nova/conf/``
    oslo.config option declarations, one file per subsystem.
``nova/policies/``
    oslo.policy rule definitions for API access control.
``nova/tests/``
    Unit (``unit/``) and functional (``functional/``) test suites.

doc/ Structure
==============

``doc/source/admin/``
    Operator guides: deployment, configuration, architecture.
``doc/source/contributor/``
    Developer guides: process, testing, APIs, agentic coding.
``doc/source/reference/``
    Internal reference: threading model, RPC, scheduling, VM states.
``doc/source/user/``
    End-user guides and feature documentation.
``doc/source/cli/``
    nova-manage and nova-status CLI reference.
``releasenotes/``
    Reno release notes (``notes/`` source files + rendered output).

API Docs
========

These live at the repository root, separate from ``doc/``.

``api-ref/``
    REST API reference: per-resource ``.inc`` files and an index. Built and
    published to docs.openstack.org.
``api-guide/``
    API usage guide covering authentication, faults, links, and general
    concepts for API consumers.
