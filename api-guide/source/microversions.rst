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

=============
Microversions
=============

API v2.1 supports microversions: small, documented changes to the API. A user
can use microversions to discover the latest API microversion supported in
their cloud. A cloud that is upgraded to support newer microversions will still
support all older microversions to maintain the backward compatibility for
those users who depend on older microversions. Users can also discover new
features easily with microversions, so that they can benefit from all the
advantages and improvements of the current cloud.

There are multiple cases which you can resolve with microversions:

Older clients with new cloud
============================

Before using an old client to talk to a newer cloud, the old client can check
the minimum version of microversions to verify whether the cloud is compatible
with the old API. This prevents the old client from breaking with backwards
incompatible API changes.

Currently the minimum version of microversions is `2.1`, which is a
microversion compatible with the legacy v2 API. That means the legacy v2 API
user doesn't need to worry that their older client software will be broken when
their cloud is upgraded with new versions. And the cloud operator doesn't need
to worry that upgrading their cloud to newer versions will break any user with
older clients that don't expect these changes.

User discovery of available features between clouds
===================================================

The new features can be discovered by microversions. The user client should
check the microversions firstly, and new features are only enabled when clouds
support. In this way, the user client can work with clouds that have deployed
different microversions simultaneously.
