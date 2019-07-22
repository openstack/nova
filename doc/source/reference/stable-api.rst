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
of the Pike release -- and also attempts to describe how the Nova team
evolved the REST API's implementation over time and removed some of the
cruft that has crept in over the years.

Background
----------

Nova used to include two distinct frameworks for exposing REST API
functionality. Older code is called the "v2 API" and existed in the
/nova/api/openstack/compute/legacy_v2/ directory. This code tree was totally
removed during Netwon release time frame (14.0.0 and later).
Newer code is called the "v2.1 API" and exists in the
/nova/api/openstack/compute directory.

The v2 API is the old Nova REST API. It is mostly replaced by v2.1 API.

The v2.1 API is the new Nova REST API with a set of improvements which
includes `Microversion <https://docs.openstack.org/api-guide/compute/microversions.html>`_
and standardized validation of inputs using JSON-Schema.
Also the v2.1 API is totally backwards compatible with the v2 API (That is the
reason we call it as v2.1 API).

Current Stable API
------------------

* Nova v2.1 API + Microversion (v2.1 APIs are backward-compatible with
  v2 API, but more strict validation)
* /v2 & /v2.1 endpoint supported
* v2 compatible mode for old v2 users

Evolution of Nova REST API
--------------------------

.. image:: /_static/images/evolution-of-api.png

Nova v2 API + Extensions
************************

Nova used to have v2 API. In v2 API, there was a concept called 'extension'.
An operator can use it to enable/disable part of Nova REST API based on requirements.
An end user may query the '/extensions' API to discover what *API functionality* is
supported by the Nova deployment.

Unfortunately, because v2 API extensions could be enabled or disabled
from one deployment to another -- as well as custom API extensions added
to one deployment and not another -- it was impossible for an end user to
know what the OpenStack Compute API actually included. No two OpenStack
deployments were consistent, which made cloud interoperability impossible.

In the Newton release, stevedore loading of API extension plugins was
deprecated and marked for removal.

In the Newton release, v2 API code base has been removed and /v2 endpoints were
directed to v2.1 code base.


v2 API compatibility mode based on v2.1 API
*******************************************
v2.1 API is exactly same as v2 API except strong input validation with no additional
request parameter allowed and Microversion feature.
Since Newton, '/v2' endpoint also started using v2.1 API implementation. But to keep the
backward compatibility of v2 API, '/v2' endpoint should not return error on additional
request parameter or any new headers for Microversion. v2 API must be same as it has
been since starting.

To achieve that behavior legacy v2 compatibility mode has been introduced. v2 compatibility
mode is based on v2.1 implementation with below difference:

* Skip additionalProperties checks in request body
* Ignore Microversion headers in request
* No Microversion headers in response

Nova v2.1 API + Microversion
****************************

In the Kilo release, nova v2.1 API has been released. v2.1 API
is supposed to be backward compatible with v2 API with strong
input validation using JSON Schema.

v2.1 API comes up with microversion concept which is a way to version
the API changes. Each new feature or modification in API has to done
via microversion bump.

API extensions concept was deprecated from the v2.1 API, are no longer
needed to evolve the REST API, and no new API functionality should use
the API extension classes to implement new functionality. Instead, new
API functionality should be added via microversion concept and use the
microversioning decorators to add or change the REST API.

v2.1 API had plugin framework which was using stevedore to load Nova REST
API extensions instead of old V2 handcrafted extension load mechanism.
There was an argument that the plugin framework supported extensibility in
the Nova API to allow deployers to publish custom API resources.

In the Newton release, config options of blacklist and whitelist extensions and
stevedore things were deprecated and marked for removal.

In Pike, stevedore based plugin framework has been removed and url mapping
is done with plain router list. There is no more dynamic magic of detecting API
implementation for url. See :doc:`Extending the API </contributor/api>`
for more information.

The '/extensions' API exposed the list of enabled API functions to users
by GET method. However as the above, new API extensions should not be added
to the list of this API. The '/extensions' API is frozen in Nova V2.1 API and
is `deprecated <https://docs.openstack.org/api-ref/compute/#extensions-extensions-deprecated>`_.

Things which are History now
****************************

As of the Pike release, many deprecated things have been removed and became
history in Nova API world:

* v2 legacy framework
* API extensions concept
* stevedore magic to load the extension/plugin dynamically
* Configurable way to enable/disable APIs extensions
