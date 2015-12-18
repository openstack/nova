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

======================
Feature Classification
======================

This document aims to define how we describe features listed in the
:doc:`support-matrix`.

Aims
====

Our users want the features they rely on to be reliable and always continue
to solve for their use case.
When things break, users request that we solve their issues quickly.
It would be better if we never had those regressions in the first place.

We are taking a two-pronged approach:

* Tell our users what features are complete, well-documented, and are kept
  stable by good tests. They will get a good experience if they stick to
  using those features.
  Please note that the tests are specific to particular combinations of
  technologies. A deployment's choice of storage, networking and
  hypervisor makes a big difference to what features will work.

* Get help for the features that are not in the above state, and warn our
  users about the risks of using those features before they are ready.
  It should make it much clearer how to help improve the feature.

Concepts
========

Some definitions to help understand the later part of the document.

Users
-----

These are the users we will talk about in this document:

* application deployer: creates/deletes servers, directly or indirect via API
* application developer: creates images and apps that run on the cloud
* cloud operator: administers the cloud
* self service administrator: both runs and uses the cloud

Now in reality the picture is way more complex. Specifically, there are
likely to be different roles for observer, creator and admin roles for
the application developer. Similarly, there are likely to be various
levels of cloud operator permissions, some read only, see a subset of
tenants, etc.

Note: this is not attempting to be an exhaustive set of personas that consider
various facets of the different users, but instead aims to be a minimal set of
users, such that we use a consistent terminology throughout this document.

Feature Group
-------------

To reduce the size of the matrix, we organize the features into groups.
Each group maps to a set of user stories, that can be validated by a set
of scenarios, tests. Typically, this means a set of tempest tests.

This list focuses on API concepts like attach and detach volumes, rather
than deployment specific concepts like attach iSCSI volume to KVM based VM.

Deployment
----------

A deployment maps to a specific test environment. A full description of the
environment should be provided, so its possible to reproduce the test results
that are reported for each of the Feature Groups.

Note: this description includes all aspects of the deployment:
the hypervisor, the number of nova-compute services, the storage being used,
the network driver being used, the types of images being tested, etc.

Feature Group Maturity
-----------------------

The Feature Group Maturity rating is specific to the API concepts, rather than
specific to a particular deployment. That detail is covered in the deployment
rating for each feature group.

We are starting out these Feature Group ratings:

* Incomplete
* Experimental
* Complete
* Complete and Required
* Deprecated (scheduled to be removed in a future release)

Incomplete features are those that don't have enough functionality to satisfy
real world use cases.

Experimental features should be used with extreme caution.
They are likely to have little or no upstream testing.
With little testing there are likely to be many unknown bugs.

For a feature to be considered complete, we must have:

* Complete API docs (concept and REST call definition)
* Complete Adminstrator docs
* Tempest tests that define if the feature works correctly
* Has enough functionality, and works reliably enough to be useful
  in real world scenarios
* Unlikely to ever have a reason to drop support for the feature

There are various reasons why a feature, once complete, becomes required, but
currently its largely when a feature is supported by all drivers. Note that
any new drivers need to prove they support all required features before it
would be allowed in upstream Nova.
Please note that this list is technically unrelated to the DefCore
effort, despite there being obvious parallels that could be drawn.

Required features are those that any new technology must support before
being allowed into tree. The larger the list, the more features can be
expected to be available on all Nova based clouds.

Deprecated features are those that are scheduled to be removed in a future
major release of Nova. If a feature is marked as complete, it should
never be deprecated.
If a feature is incomplete or experimental for several releases,
it runs the risk of being deprecated, and later removed from the code base.

Deployment Rating for a Feature Group
--------------------------------------

The deployment rating is purely about the state of the tests for each
Feature Group on a particular deployment.

There will the following ratings:

* unknown
* not implemented
* implemented: self declare the tempest tests pass
* regularly tested: tested by third party CI
* checked: Tested as part of the check or gate queue

The eventual goal is to automate this list from some third party CI reporting
system, but so we can make progress, this will be a manual inspection that is
documented by an hand written ini file. Ideally, this will be reviewed every
milestone.

Feature Group Definitions
=========================

This is a look at features targeted at application developers, and the current
state of each feature, independent of the specific deployment.

Please note: this is still a work in progress!

Key TODOs:

* use new API docs as a template for the feature groups, into ini file
* add lists of tempest UUIDs for each group
* link from hypervisor support matrix into feature group maturity ratings
* add maturity rating into the feature groups, with a justification, which
  is likely to include lints to API docs, etc
* replace tick and cross in support matrix with "deployment ratings"
* eventually generate the tick and cross from live, historical, CI results

