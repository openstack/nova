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


REST API Policy Enforcement
===========================

The following describes some of the shortcomings in how policy is used and
enforced in nova, along with some benefits of fixing those issues. Each issue
has a section dedicated to describing the underlying cause and historical
context in greater detail.

Problems with current system
----------------------------

The following is a list of issues with the existing policy enforcement system:

* Default policies lack exhaustive testing
* Mismatch between authoritative scope and resources
* Policies are inconsistently named
* Current defaults do not use default roles provided from keystone
* Policy enforcement is spread across multiple levels and components
* Some policies use hard-coded check strings
* Some APIs do not use granular rules

Addressing the list above helps operators by:

1. Providing them with flexible and useful defaults
2. Reducing the likelihood of writing and maintaining custom policies
3. Improving interoperability between deployments
4. Increasing RBAC confidence through first-class testing and verification
5. Reducing complexity by using consistent policy naming conventions
6. Exposing more functionality to end-users, safely, making the entire nova API
   more self-serviceable resulting in less operational overhead for operators
   to do things on behalf of users

Additionally, the following is a list of benefits to contributors:

1. Reduce developer maintenance and cost by isolating policy enforcement into a
   single layer
2. Reduce complexity by using consistent policy naming conventions
3. Increased confidence in RBAC refactoring through exhaustive testing that
   prevents regressions before they merge

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
