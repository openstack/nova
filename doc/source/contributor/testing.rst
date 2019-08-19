..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

==============
Test Strategy
==============

A key part of the "four opens" is ensuring the OpenStack delivers well-tested
and usable software. For more details see:
http://docs.openstack.org/project-team-guide/introduction.html#the-four-opens

Experience has shown that untested features are frequently broken, in part
due to the velocity of upstream changes. As we aim to ensure we keep all
features working across upgrades, we must aim to test all features.

Reporting Test Coverage
=======================

For details on plans to report the current test coverage, refer to
:doc:`/user/feature-classification`.

Running tests and reporting results
===================================

Voting in Gerrit
----------------

On every review in gerrit, check tests are run on very patch set, and are
able to report a +1 or -1 vote.
For more details, please see:
http://docs.openstack.org/infra/manual/developers.html#automated-testing

Before merging any code, there is an integrate gate test queue, to ensure
master is always passing all tests.
For more details, please see:
http://docs.openstack.org/infra/zuul/user/gating.html

Infra vs Third-Party
--------------------

Tests that use fully open source components are generally run by the
OpenStack Infra teams. Test setups that use non-open technology must
be run outside of that infrastructure, but should still report their
results upstream.

For more details, please see:
http://docs.openstack.org/infra/system-config/third_party.html

Ad-hoc testing
--------------

It is particularly common for people to run ad-hoc tests on each released
milestone, such as RC1, to stop regressions.
While these efforts can help stabilize the release, as a community we have a
much stronger preference for continuous integration testing. Partly this is
because we encourage users to deploy master, and we generally have to assume
that any upstream commit may already been deployed in production.

Types of tests
==============

Unit tests
----------

Unit tests help document and enforce the contract for each component.
Without good unit test coverage it is hard to continue to quickly evolve the
codebase.
The correct level of unit test coverage is very subjective, and as such we are
not aiming for a particular percentage of coverage, rather we are aiming for
good coverage.
Generally, every code change should have a related unit test:
https://opendev.org/openstack/nova/src/branch/master/HACKING.rst#creating-unit-tests

Integration tests
-----------------

Today, our integration tests involve running the Tempest test suite on a
variety of Nova deployment scenarios. The integration job setup is defined
in the ``.zuul.yaml`` file in the root of the nova repository. Jobs are
restricted by queue:

* ``check``: jobs in this queue automatically run on all proposed changes even
  with non-voting jobs
* ``gate``: jobs in this queue automatically run on all approved changes
  (voting jobs only)
* ``experimental``: jobs in this queue are non-voting and run on-demand by
  leaving a review comment on the change of "check experimental"

In addition, we have third parties running the tests on their preferred Nova
deployment scenario.

Functional tests
----------------

Nova has a set of in-tree functional tests that focus on things that are out
of scope for tempest testing and unit testing.
Tempest tests run against a full live OpenStack deployment, generally deployed
using devstack. At the other extreme, unit tests typically use mock to test a
unit of code in isolation.
Functional tests don't run an entire stack, they are isolated to nova code,
and have no reliance on external services. They do have a WSGI app, nova
services and a database, with minimal stubbing of nova internals.

Interoperability tests
-----------------------

The DefCore committee maintains a list that contains a subset of Tempest tests.
These are used to verify if a particular Nova deployment's API responds as
expected. For more details, see: https://opendev.org/openstack/interop
