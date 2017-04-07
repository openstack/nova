..
      Copyright 2015 Intel
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.


Nova Stable REST API
====================

This document describes both the current state of the Nova REST API -- as
of the Newton release -- and also attempts to describe how the Nova team intends
to evolve the REST API's implementation over time and remove some of the
cruft that has crept in over the years.

Background
----------

Nova used to include two distinct frameworks for exposing REST API
functionality. Older code is called the "V2 API" and existed in the
/nova/api/openstack/compute/legacy_v2/ directory. This code tree was totally
removed during Netwon release time frame (14.0.0 and later).
Newer code is called the "v2.1 API" and exists in the 
/nova/api/openstack/compute directory.

The V2 API is the old Nova REST API. It is mostly replaced by V2.1 API.

The V2.1 API is the new Nova REST API with a set of improvements which
includes Microversion and standardized validation of inputs using JSON-Schema.
Also the V2.1 API is totally backwards compatible with the V2 API (That is the
reason we call it as V2.1 API).

Stable API
----------

In the V2 API, there is a concept called 'extension'. An operator can use it
to enable/disable part of Nova REST API based on requirements. An end user
may query the '/extensions' API to discover what *API functionality* is
supported by the Nova deployment.

Unfortunately, because V2 API extensions could be enabled or disabled
from one deployment to another -- as well as custom API extensions added
to one deployment and not another -- it was impossible for an end user to
know what the OpenStack Compute API actually included. No two OpenStack
deployments were consistent, which made cloud interoperability impossible.

API extensions, being removed from the v2.1 API, are no longer
needed to evolve the REST API, and no new API functionality should use
the API extension classes to implement new functionality. Instead, new
API functionality should use the microversioning decorators to add or change
the REST API.

The extension is considered as two things in the Nova V2.1 API:

* The '/extensions' API

  This API exposed the list of enabled API functions to users
  by GET method. However as the above, new API extensions
  should not be added to the list of this API.

  The '/extensions' API is frozen in Nova V2.1 API and is deprecated.

* The plugin framework

  One of the improvements in the V2.1 API was using stevedore to load
  Nova REST API extensions instead of old V2 handcrafted extension load
  mechanism.

  There was an argument that the plugin framework supported extensibility in
  the Nova API to allow deployers to publish custom API resources.

From Nove V2.1 REST API, the concept of core API and extension API is
eliminated also. There is no difference between Nova V2.1 REST API,
all of them are part of Nova stable REST API.
