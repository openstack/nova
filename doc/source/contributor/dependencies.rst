.. _dependencies:

============
Dependencies
============

Nova uses the standard OpenStack dependency management model. Keep dependency
changes in the file that matches how the dependency is used so that local
development, packaging, and CI jobs install the same inputs.

Python dependencies
===================

Runtime Python dependencies belong in ``requirements.txt``. These are packages
needed when Nova services or libraries run.

Test-only Python dependencies belong in ``test-requirements.txt``. These are
packages needed by unit, functional, and validation jobs but not by a deployed
Nova service.

Documentation-only Python dependencies belong in ``doc/requirements.txt``.
These are packages needed to build or validate the documentation, such as
Sphinx extensions, documentation themes, release note tooling, and redirect
test tools.

System packages
===============

Binary and operating-system package dependencies belong in ``bindep.txt``.
Use bindep profiles such as ``test``, ``doc``, or ``pdf-docs`` when a package
is only needed by a specific class of jobs. For example, a library or command
needed only when building documentation should be listed in ``bindep.txt`` with
the ``doc`` profile rather than documented as a manual setup step.

Packaging metadata
==================

Nova uses ``pbr`` for Python packaging metadata. Do not introduce alternative
version or dependency management systems such as ``setuptools-scm``. Keep
package dependencies in the requirement files above so OpenStack constraints
and CI can manage them consistently.

``pyproject.toml`` is present and records static package metadata per
`PEP 621`_, such as the project name, classifiers, and entry points. The
version and main Python dependency list are dynamic and managed by ``pbr``;
they are not edited in the ``dependencies`` table.

Runtime, test, and documentation Python dependencies must continue to be
declared in ``requirements.txt``, ``test-requirements.txt``, and
``doc/requirements.txt`` as described above.

Nova also defines a small set of setuptools extra groups in the
``[project.optional-dependencies]`` table (for example ``osprofiler``,
``zvm``, and ``vmware``). Use those only for the same driver or tooling
extras already represented there. Do not add new general runtime or test
dependencies via ``optional-dependencies``; add them to the appropriate
requirement file instead.

.. _PEP 621: https://peps.python.org/pep-0621/
