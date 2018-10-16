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

This document presents a matrix that describes which features are ready to be
used and which features are works in progress. It includes links to relevant
documentation and functional tests.

.. warning:: Please note: this is a work in progress!

Aims
====

Users want reliable, long-term solutions for their use cases.
The feature classification matrix identifies which features are
complete and ready to use, and which should be used with caution.

The matrix also benefits developers by providing a list of features that
require further work to be considered complete.

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

.. feature_matrix:: feature-matrix-gp.ini

.. _matrix-nfv:

NFV Cloud Features
==================

Network Function Virtualization (NFV) is about virtualizing network node
functions into building blocks that may connect, or chain together to
create a particular service. It is common for this workloads needing
bare metal like performance, i.e. low latency and close to line speed
performance.

.. include:: /common/numa-live-migration-warning.txt

.. feature_matrix:: feature-matrix-nfv.ini

.. _matrix-hpc:

HPC Cloud Features
==================

High Performance Compute (HPC) cloud have some specific needs that are covered
in this set of features.

.. feature_matrix:: feature-matrix-hpc.ini

.. _notes-on-concepts:

Notes on Concepts
=================

This document uses the following terminology.

Users
-----

These are the users we talk about in this document:

application deployer
   creates and deletes servers, directly or indirectly using an API

application developer
   creates images and apps that run on the cloud

cloud operator
   administers the cloud

self service administrator
   runs and uses the cloud

.. note::

   This is not an exhaustive list of personas, but rather an indicative set of
   users.

Feature Group
-------------

To reduce the size of the matrix, we organize the features into groups.
Each group maps to a set of user stories that can be validated by a set
of scenarios and tests. Typically, this means a set of tempest tests.

This list focuses on API concepts like attach and detach volumes, rather than
deployment specific concepts like attach an iSCSI volume to a KVM based VM.

Deployment
----------

A deployment maps to a specific test environment. We provide a full description
of the environment, so it is possible to reproduce the reported test results
for each of the Feature Groups.

This description includes all aspects of the deployment, for example
the hypervisor, number of nova-compute services, storage, network driver,
and types of images being tested.

Feature Group Maturity
-----------------------

The Feature Group Maturity rating is specific to the API concepts, rather than
specific to a particular deployment. That detail is covered in the deployment
rating for each feature group.

.. note::

   Although having some similarities, this list is not directly related
   to the DefCore effort.

**Feature Group ratings:**

Incomplete
  Incomplete features are those that do not have enough functionality to
  satisfy real world use cases.

Experimental
  Experimental features should be used with extreme caution. They are likely
  to have little or no upstream testing, and are therefore likely to
  contain bugs.

Complete
  For a feature to be considered complete, it must have:

  * complete API docs (concept and REST call definition)
  * complete Administrator docs
  * tempest tests that define if the feature works correctly
  * sufficient functionality and reliability to be useful in real world
    scenarios
  * a reasonable expectation that the feature will be supported long-term

Complete and Required
  There are various reasons why a complete feature may be required, but
  generally it is when all drivers support that feature. New
  drivers need to prove they support all required features before they are
  allowed in upstream Nova.

  Required features are those that any new technology must support before
  being allowed into tree. The larger the list, the more features are
  available on all Nova based clouds.

Deprecated
  Deprecated features are those that are scheduled to be removed in a future
  major release of Nova. If a feature is marked as complete, it should
  never be deprecated.

  If a feature is incomplete or experimental for several releases,
  it runs the risk of being deprecated and later removed from the code base.

Deployment Rating for a Feature Group
--------------------------------------

The deployment rating refers to the state of the tests for each
Feature Group on a particular deployment.

**Deployment ratings:**

Unknown
   No data is available.

Not Implemented
   No tests exist.

Implemented
   Self declared that the tempest tests pass.

Regularly Tested
   Tested by third party CI.

Checked
   Tested as part of the check or gate queue.

The eventual goal is to automate this list from a third party CI reporting
system, but currently we document manual inspections in an ini file.
Ideally, we will review the list at every milestone.
