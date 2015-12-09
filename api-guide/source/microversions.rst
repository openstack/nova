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

API v2.1 supports Microversions: small, documented changes to the API. A user
can use Microversions to discover the latest API version supported in their
cloud. A cloud that is upgraded to support newer versions will still support
all older versions to maintain the backward compatibility for those users who
depend on older versions. Users can also discover new features easily with
Microversions, so that they can benefit from all the advantages and
improvements of the current cloud.

There are multiple cases which you can resolve with Microversions:

Legacy v2 API user with new cloud
=================================

The minimum version of Microversions is `2.1`, which is a version compatible
with the legacy v2 API. The legacy v2 API user doesn't need to worry that their
older client software will be broken when their cloud is upgraded with new
versions. And the cloud operator doesn't need to worry that upgrading their
cloud to newer versions will break any user with older clients that don't
expect these changes.

TODO: add more use-cases for Microversions
