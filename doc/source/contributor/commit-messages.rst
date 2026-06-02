.. _commit-messages:

===============
Commit Messages
===============

Nova follows the OpenStack Gerrit workflow. Commit messages should explain why
the change is needed, be readable in email, and preserve the footers required by
OpenStack tooling.

For general OpenStack guidance, see the `OpenStack contributor guide commit
message documentation`__ and the `OpenStack Git commit message wiki`__.

.. __: https://docs.openstack.org/contributors/common/git.html#commit-messages
.. __: https://wiki.openstack.org/wiki/GitCommitMessages

Message style
=============

Use an imperative subject line, normally around 50 characters, with no trailing
period. Wrap body text at 72 columns and explain why the change is needed, not
just what changed.

Use ASCII-safe printable characters in commit messages. Prefer ``<=``, ``>=``,
``...``, and ``--`` rather than Unicode equivalents such as ``≤``, ``≥``,
``…``, and ``—``. This keeps messages readable across terminals, mail clients,
and review tools used in the OpenStack workflow.

Gerrit Change-Id
================

Nova uses Gerrit. Do not remove existing ``Change-Id:`` footers when amending
or rewording a commit. The ``Change-Id`` links new patch sets to the existing
review.

Developer Certificate of Origin
===============================

Nova follows the Linux Foundation Developer Certificate of Origin (DCO). Every
commit must include a ``Signed-off-by:`` line certifying that the contributor
has the right to submit the contribution::

    Signed-off-by: Jane Smith <jane@example.com>

When creating commits locally, ``git commit -s`` can add this footer.

AI attribution trailers
=======================

When AI coding tools materially contribute to a Nova change, use one of the
following trailers. The tool name is required. The model name or version is
optional but should be included when known. Guidance matches the
`OpenInfra Foundation policy for AI generated content`__.

.. __: https://openinfra.dev/legal/ai-policy

Notation: ``<x>`` = required, ``[x]`` = optional. Do not include the brackets
or angle brackets in the final trailer.

``Generated-By: <tool-name> [model-version]``
    Use when the commit is mostly machine-authored with minimal human revision.

``Assisted-By: <tool-name> [model-version]``
    Use when a human materially revised, amended, or curated the AI-generated
    work.

When multiple AI tools materially contributed, each tool may have its own
``Assisted-By`` or ``Generated-By`` trailer.

Do not use ``Co-Authored-By:`` for AI tools. That trailer identifies human
co-authors and carries a DCO implication; applying it to a language model
misrepresents authorship. Use ``Generated-By`` or ``Assisted-By`` instead.

Do not use ``Made-with:`` in this repository; Nova standardizes on
``Generated-By`` and ``Assisted-By`` as described in that OpenInfra policy.

Example footer block
====================

::

    Assisted-By: my-agent my-model-v1
    Signed-off-by: Jane Smith <jane@example.com>
    Change-Id: I1234567890abcdef1234567890abcdef12345678
