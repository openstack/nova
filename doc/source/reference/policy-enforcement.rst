..
      Copyright 2014 Intel
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


Rest API Policy Enforcement
===========================

Here is a vision of how we want policy to be enforced in nova.

Problems with current system
----------------------------

There are several problems for current API policy.

* The permission checking is spread through the various levels of the nova
  code, also there are some hard-coded permission checks that make some
  policies not enforceable.

* API policy rules need better granularity. Some of extensions just use one
  rule for all the APIs. Deployer can't get better granularity control for
  the APIs.

* More easy way to override default policy settings for deployer. And
  Currently all the API(EC2, V2, V2.1) rules mix in one policy.json file.

These are the kinds of things we need to make easier:

1. Operator wants to enable a specific role to access the service API which
is not possible because there is currently a hard coded admin check.

2. One policy rule per API action. Having a check in the REST API and a
redundant check in the compute API can confuse developers and deployers.

3. Operator can specify different rules for APIs that in same extension.

4. Operator can override the default policy rule easily without mixing his own
config and default config in one policy.json file.

Future of policy enforcement
----------------------------

The generic rule for all the improvement is keep V2 API back-compatible.
Because V2 API may be deprecated after V2.1 parity with V2. This can reduce
the risk we take. The improvement just for EC2 and V2.1 API. There isn't
any user for V2.1, as it isn't ready yet. We have to do change for EC2 API.
EC2 API won't be removed like v2 API. If we keep back-compatible for EC2 API
also, the old compute api layer checks won't be removed forever. EC2 API is
really small than Nova API. It's about 29 APIs without volume and image
related(those policy check done by cinder and glance). So it will affect user
less.

Enforcement policy at REST API layer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The policy should be only enforced at REST API layer. This is clear for user
to know where the policy will be enforced. If the policy spread into multiple
layer of nova code, user won't know when and where the policy will be enforced
if they didn't have knowledge about nova code.

Remove all the permission checking under REST API layer. Policy will only be
enforced at REST API layer.

This will affect the EC2 API and V2.1 API, there are some API just have policy
enforcement at Compute/Network API layer, those policy will be move to API
layer and renamed.

Removes hard-code permission checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Hard-coded permission checks make it impossible to supply a configurable
policy. They should be removed in order to make nova auth completely
configurable.

This will affect EC2 API and Nova V2.1 API. User need update their policy
rule to match the old hard-code permission.

For Nova V2 API, the hard-code permission checks will be moved to REST API
layer to guarantee it won't break the back-compatibility. That may ugly
some hard-code permission check in API layer, but V2 API will be removed
once V2.1 API ready, so our choice will reduce the risk.

Port policy.d into nova
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This feature make deployer can override default policy rule easily. And
When nova default policy config changed, deployer only need replace default
policy config files with new one. It won't affect his own policy config in
other files.

Use different prefix in policy rule name for EC2/V2/V2.1 API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently all the APIs(Nova v2/v2.1 API, EC2 API) use same set of policy
rules. Especially there isn't obvious mapping between those policy rules
and EC2 API. User can know clearly which policy should be configured for
specific API.

Nova should provide different prefix for policy rule name that used to
group them, and put them in different policy configure file in policy.d

* EC2 API: Use prefix "ec2_api". The rule looks like "ec2_api:[action]"

* Nova V2 API: After we move to V2.1, we needn't spend time to change V2
  api rule, and needn't to bother deployer upgrade their policy config. So
  just keep V2 API policy rule named as before.

* Nova V2.1 API: We name the policy rule as
  "os_compute_api:[extension]:[action]". The core API may be changed in
  the future, so we needn't name them as "compute" or "compute_extension"
  to distinguish the core or extension API.

This will affect EC2 API and V2.1 API. For EC2 API, it need deployer update
their policy config. For V2.1 API, there isn't any user yet, so there won't
any effect.


Group the policy rules into different policy files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After group the policy rules for different API, we can separate them into
different files. Then deployer will more clear for which rule he can set for
specific API. The rules can be grouped as below:

* policy.json: It only contains the generic rule, like: ::

  "context_is_admin":  "role:admin",
  "admin_or_owner":  "is_admin:True or project_id:%(project_id)s",
  "default": "rule:admin_or_owner",

* policy.d/00-ec2-api.conf: It contains all the policy rules for EC2 API.

* policy.d/00-v2-api.conf: It contains all the policy rules for nova V2 API.

* policy.d/00-v2.1-api.conf: It contains all the policy rules for nova v2.1
  API.

The prefix '00-' is used to order the configure file. All the files in
policy.d will be loaded by alphabetical order. '00-' means those files will
be loaded very early.

Existed Nova API being restricted
---------------------------------

Nova provide default policy rules for all the APIs. Operator should only make
the policy rule more permissive. If the Operator make the API to be restricted
that make break the existed API user or application. That's kind of
back-incompatible. SO Operator can free to add additional permission to the
existed API.

Policy Enforcement by user_id
-----------------------------

In the legacy v2 API, the policy enforces with target object, and some operators
implement user-based authorization based on that. Actually only project-based
authorization is well tested, the user based authorization is untested and
isn't supported by Nova. In the future, the nova will remove all the supports
for user-based authorization.
