..
      Copyright 2009-2015 OpenStack Foundation

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

===========
Compute API
===========

The nova project has a RESTful HTTP service called the OpenStack Compute API.
Through this API, the service provides massively scalable, on demand,
self-service access to compute resources. Depending on the deployment those
compute resources might be Virtual Machines, Physical Machines or Containers.

This guide covers the concepts in the OpenStack Compute API.
For a full reference listing, please see:
`Compute API Reference <https://docs.openstack.org/api-ref/compute/#compute-api>`__.

We welcome feedback, comments, and bug reports at
`bugs.launchpad.net/nova <https://bugs.launchpad.net/nova>`__.

Intended audience
=================

This guide assists software developers who want to develop applications
using the OpenStack Compute API. To use this information, you should
have access to an account from an OpenStack Compute provider, or have
access to your own deployment, and you should also be familiar with the
following concepts:

*  OpenStack Compute service
*  RESTful HTTP services
*  HTTP/1.1
*  JSON data serialization formats

End User and Operator APIs
==========================

The Compute API includes all end user and operator API calls.
The API works with keystone and oslo.policy to deliver RBAC (Role-based access
control).
The default policy file gives suggestions on what APIs should not
be made available to most end users but this is fully configurable.

API Versions
============

Following the Mitaka release, every Nova deployment should have
the following endpoints:

* / - list of available versions
* /v2 - the first version of the Compute API, uses extensions
  (we call this Compute API v2.0)
* /v2.1 - same API, except uses microversions

While this guide concentrates on documenting the v2.1 API,
please note that the v2.0 is (almost) identical to first microversion of
the v2.1 API and are also covered by this guide.

Contents
========

.. toctree::
    :maxdepth: 2

    users
    versions
    microversions
    general_info
    server_concepts
    authentication
    extra_specs_and_properties
    faults
    limits
    links_and_references
    paginated_collections
    polling_changes
    request_and_response_formats
    down_cells
    port_with_resource_request
    accelerator-support
