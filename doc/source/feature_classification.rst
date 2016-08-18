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

.. warning:: Please note: this is a work in progress!

Aims
====

Our users want the features they rely on to be reliable and always continue
to solve for their use case.
The feature classification matrix should help identify which features are
complete and ready to use, and which should be used with caution.

An additional benefit, is we have a clear list of things where we need help
to complete the feature, its testing and its documentation.

Below is a matrix for a selection of important verticals:

* :ref:`matrix-gp`
* :ref:`matrix-nfv`
* :ref:`matrix-hpc`

For more details on the concepts in each matrix,
please see :ref:`notes-on-concepts`.

.. _matrix-gp:

General Purpose Cloud Features
===============================

This is a summary of the key features dev/test clouds, and other similar
general purpose clouds need, and it describes their current state.

Below there are sections on NFV and HPC specific features. These look at
specific features and scenarios that are important to those more specific
sets of use cases.

.. feature_matrix:: feature_matrix_gp.ini

.. _matrix-nfv:

NFV Cloud Features
==================

Network Function Virtualization (NFV) is about virtualizing network node
functions into building blocks that may connect, or chain together to
create a particular service. It is common for this workloads needing
bare metal like performance, i.e. low latency and close to line speed
performance.

.. feature_matrix:: feature_matrix_nfv.ini

.. _matrix-hpc:

HPC Cloud Features
==================

High Performance Compute (HPC) cloud have some specific needs that are covered
in this set of features.

.. feature_matrix:: feature_matrix_hpc.ini

.. _notes-on-concepts:

Notes on Concepts
=================

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
* Complete Administrator docs
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
