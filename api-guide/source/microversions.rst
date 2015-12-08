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

API v2.1 supports Microversions. User uses Microversions to discover the
supported API version in the cloud. If cloud is upgraded to support newer
versions, it will still support all older versions to maintain the backward
compatibility for users using older versions. Also user can discover new
features easily with Microversions, then user can take all the advantages of
current cloud.

There are multiple cases which you can resolve with Microversions:

Legacy v2 API user with new cloud
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The minimum version of Microversions is `2.1`, this is a version compatible
with legacy v2 API. The legacy v2 API user don't need to worry about that his
old client is broken with new cloud deployment. Cloud operator don't need to
worry that upgrading cloud to newer versions will break any user with old
client.

TODO: add more use-cases for Microversions
