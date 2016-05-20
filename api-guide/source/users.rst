..
      Copyright 2015 OpenStack Foundation

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

=====
Users
=====

The Compute API includes all end user and administrator API calls.

Role based access control
=========================

Keystone middleware is used to authenticate users and identify their roles.

The Compute API uses these roles, along with oslo.policy, to decide
what the user is authorized to do.

TODO - link to compute admin guide for details.

Personas used in this guide
===========================

While the policy can be configured in many ways, to make it easy to understand
the most common use cases the API have been designed for, we should
standardize on the following types of user:

* application deployer: creates/deletes servers, directly or indirectly via API
* application developer: creates images and applications that run on the cloud
* cloud administrator: deploys, operates and maintains the cloud

Now in reality the picture is much more complex. Specifically, there are
likely to be different roles for observer, creator and administrator roles for
the application developer. Similarly, there are likely to be various levels of
cloud administrator permissions, such as a read-only role that is able to view
a lists of servers for a specific tenant but is not able to perform any
actions on any of them.

Note: this is not attempting to be an exhaustive set of personas that consider
various facets of the different users but instead aims to be a minimal set of
users such that we use a consistent terminology throughout this document.

TODO - could assign names to these users, or similar, to make it more "real".

Discovering Policy
==================

An API to discover what actions you are authorized to perform is still a work
in progress. Currently this reported by a HTTP 403 error.

TODO - link to the doc on errors.
