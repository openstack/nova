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

* `Testing default policies`_
* `Mismatched authorization`_
* `Inconsistent naming`_
* `Incorporating default roles`_
* `Compartmentalized policy enforcement`_
* `Refactoring hard-coded permission checks`_
* `Granular policy checks`_

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

Testing default policies
------------------------

Testing default policies is important in protecting against authoritative
regression. Authoritative regression is when a change accidentally allows
someone to do something or see something they shouldn't. It can also be when a
change accidentally restricts a user from doing something they used to have the
authorization to perform. This testing is especially useful prior to
refactoring large parts of the policy system. For example, this level of
testing would be invaluable prior to pulling policy enforcement logic from the
database layer up to the API layer.

`Testing documentation`_ exists that describes the process for developing these
types of tests.

.. _Testing documentation: https://docs.openstack.org/keystone/latest/contributor/services.html#ruthless-testing

Mismatched authorization
------------------------

The compute API is rich in functionality and has grown to manage both physical
and virtual hardware. Some APIs were meant to assist operators while others
were specific to end users. Historically, nova used project-scoped tokens to
protect almost every API, regardless of the intended user. Using project-scoped
tokens to authorize requests for system-level APIs makes for undesirable
user-experience and is prone to overloading roles. For example, to prevent
every user from accessing hardware level APIs that would otherwise violate
tenancy requires operators to create a ``system-admin`` or ``super-admin``
role, then rewrite those system-level policies to incorporate that role. This
means users with that special role on a project could access system-level
resources that aren't even tracked against projects (hypervisor information is
an example of system-specific information.)

As of the Queens release, keystone supports a scope type dedicated to easing
this problem, called system scope. Consuming system scope across the compute
API results in fewer overloaded roles, less specialized authorization logic in
code, and simpler policies that expose more functionality to users without
violating tenancy. Please refer to keystone's `authorization scopes
documentation`_ to learn more about scopes and how to use them effectively.

.. _authorization scopes documentation: https://docs.openstack.org/keystone/latest/contributor/services.html#authorization-scopes

Inconsistent naming
-------------------

Inconsistent conventions for policy names are scattered across most OpenStack
services, nova included. Recently, there was an effort that introduced a
convention that factored in service names, resources, and use cases. This new
convention is applicable to nova policy names. The convention is formally
`documented`_ in oslo.policy and we can use policy `deprecation tooling`_ to
gracefully rename policies.

.. _documented: https://docs.openstack.org/oslo.policy/latest/user/usage.html#naming-policies
.. _deprecation tooling: https://docs.openstack.org/oslo.policy/latest/reference/api/oslo_policy.policy.html#oslo_policy.policy.DeprecatedRule

Incorporating default roles
---------------------------

Up until the Rocky release, keystone only ensured a single role called
``admin``
was available to the deployment upon installation. In Rocky, this support was
expanded to include ``member`` and ``reader`` roles as first-class citizens during
keystone's installation. This allows service developers to rely on these roles
and include them in their default policy definitions. Standardizing on a set of
role names for default policies increases interoperability between deployments
and decreases operator overhead.

You can find more information on default roles in the keystone `specification`_
or `developer documentation`_.

.. _specification: http://specs.openstack.org/openstack/keystone-specs/specs/keystone/rocky/define-default-roles.html
.. _developer documentation: https://docs.openstack.org/keystone/latest/contributor/services.html#reusable-default-roles

Compartmentalized policy enforcement
------------------------------------

Policy logic and processing is inherently sensitive and often complicated. It
is sensitive in that coding mistakes can lead to security vulnerabilities. It
is complicated in the resources and APIs it needs to protect and the vast
number of use cases it needs to support. These reasons make a case for
isolating policy enforcement and processing into a compartmentalized space, as
opposed to policy logic bleeding through to different layers of nova. Not
having all policy logic in a single place makes evolving the policy enforcement
system arduous and makes the policy system itself fragile.

Currently, the database and API components of nova contain policy logic. At
some point, we should refactor these systems into a single component that is
easier to maintain. Before we do this, we should consider approaches for
bolstering testing coverage, which ensures we are aware of or prevent policy
regressions. There are examples and documentation in API protection `testing
guides`_.

.. _testing guides: https://docs.openstack.org/keystone/latest/contributor/services.html#ruthless-testing

Refactoring hard-coded permission checks
----------------------------------------

The policy system in nova is designed to be configurable. Despite this design,
there are some APIs that have hard-coded checks for specific roles. This makes
configuration impossible, misleading, and frustrating for operators. Instead,
we can remove hard-coded policies and ensure a configuration-driven approach,
which reduces technical debt, increases consistency, and provides better
user-experience for operators. Additionally, moving hard-coded checks into
first-class policy rules let us use existing policy tooling to deprecate,
document, and evolve policies.

Granular policy checks
----------------------

Policies should be as granular as possible to ensure consistency and reasonable
defaults. Using a single policy to protect CRUD for an entire API is
restrictive because it prevents us from using default roles to make delegation
to that API flexible. For example, a policy for ``compute:foobar`` could be
broken into ``compute:foobar:create``, ``compute:foobar:update``,
``compute:foobar:list``, ``compute:foobar:get``, and ``compute:foobar:delete``.
Breaking policies down this way allows us to set read-only policies for
readable operations or use another default role for creation and management of
`foobar` resources. The oslo.policy library has `examples`_ that show how to do
this using deprecated policy rules.

.. _examples: https://docs.openstack.org/oslo.policy/latest/reference/api/oslo_policy.policy.html#oslo_policy.policy.DeprecatedRule
