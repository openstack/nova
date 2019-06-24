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

=========================================
Scheduler hints versus flavor extra specs
=========================================

People deploying and working on Nova often have questions about flavor extra
specs and scheduler hints and what role they play in scheduling decisions, and
which is a better choice for exposing capability to an end user of the cloud.
There are several things to consider and it can get complicated. This document
attempts to explain at a high level some of the major differences and
drawbacks with both flavor extra specs and scheduler hints.

Extra Specs
-----------

In general flavor extra specs are specific to the cloud and how it is
organized for capabilities, and should be abstracted from the end user.
Extra specs are tied to :doc:`host aggregates </admin/aggregates>` and a lot
of them also define how a guest is created in the hypervisor, for example
what the watchdog action is for a VM. Extra specs are also generally
interchangeable with `image properties`_ when it comes to VM behavior, like
the watchdog example. How that is presented to the user is via the name of
the flavor, or documentation specifically for that deployment,
e.g. instructions telling a user how to setup a baremetal instance.

.. _image properties: https://docs.openstack.org/glance/latest/admin/useful-image-properties.html

Scheduler Hints
---------------

Scheduler hints, also known simply as "hints", can be specified during server
creation to influence the placement of the server by the scheduler depending
on which scheduler filters are enabled. Hints are mapped to specific filters.
For example, the ``ServerGroupAntiAffinityFilter`` scheduler filter is used
with the ``group`` scheduler hint to indicate that the server being created
should be a member of the specified anti-affinity group and the filter should
place that server on a compute host which is different from all other current
members of the group.

Hints are not more "dynamic" than flavor extra specs. The end user
specifies a flavor and optionally a hint when creating a server, but
ultimately what they can specify is static and defined by the deployment.

Similarities
------------

* Both scheduler hints and flavor extra specs can be used by
  :doc:`scheduler filters </admin/configuration/schedulers>`.

* Both are totally customizable, meaning there is no whitelist within Nova of
  acceptable hints or extra specs, unlike image properties [1]_.

* An end user cannot achieve a new behavior without deployer consent, i.e.
  even if the end user specifies the ``group`` hint, if the deployer did not
  configure the ``ServerGroupAntiAffinityFilter`` the end user cannot have the
  ``anti-affinity`` behavior.

Differences
-----------

* A server's host location and/or behavior can change when resized with a
  flavor that has different extra specs from those used to create the server.
  Scheduler hints can only be specified during server creation, not during
  resize or any other "move" operation, but the original hints are still
  applied during the move operation.

* The flavor extra specs used to create (or resize) a server can be retrieved
  from the compute API using the `2.47 microversion`_. As of the 19.0.0 Stein
  release, there is currently no way from the compute API to retrieve the
  scheduler hints used to create a server.

  .. note:: Exposing the hints used to create a server has been proposed [2]_.
            Without this, it is possible to workaround the limitation by doing
            things such as including the scheduler hint in the server metadata
            so it can be retrieved via server metadata later.

* In the case of hints the end user can decide not to include a hint. On the
  other hand the end user cannot create a new flavor (by default policy) to
  avoid passing a flavor with an extra spec - the deployer controls the
  flavors.

.. _2.47 microversion: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id42

Discoverability
---------------

When it comes to discoverability, by the default
``os_compute_api:os-flavor-extra-specs:index`` policy rule, flavor extra
specs are more "discoverable" by the end user since they can list them for a
flavor. However, one should not expect an average end user to understand what
different extra specs mean as they are just a key/value pair. There is some
documentation for some "standard" extra specs though [3]_. However, that is
not an exhaustive list and it does not include anything that different
deployments would define for things like linking a flavor to a set of
:doc:`host aggregates </admin/aggregates>`, for example, when creating flavors
for baremetal instances, or what the chosen
:doc:`hypervisor driver </admin/configuration/hypervisors>` might support for
flavor extra specs.

Scheduler hints are less discoverable from an end user perspective than
extra specs. There are some standard hints defined in the API request
schema [4]_. However:

1. Those hints are tied to scheduler filters and the scheduler filters are
   configurable per deployment, so for example the ``JsonFilter`` might not be
   enabled (it is not enabled by default), so the ``query`` hint would not do
   anything.
2. Scheduler hints are not restricted to just what is in that schema in the
   upstream nova code because of the ``additionalProperties: True`` entry in
   the schema. This allows deployments to define their own hints outside of
   that API request schema for their own
   :ref:`custom scheduler filters <custom-scheduler-filters>` which are not
   part of the upstream nova code.

Interoperability
----------------

The only way an end user can really use scheduler hints is based
on documentation (or GUIs/SDKs) that a specific cloud deployment provides for
their setup. So if **CloudA** defines a custom scheduler filter X and a hint
for that filter in their documentation, an end user application can only run
with that hint on that cloud and expect it to work as documented. If the user
moves their application to **CloudB** which does not have that scheduler
filter or hint, they will get different behavior.

So obviously both flavor extra specs and scheduler hints are not interoperable.

Which to use?
-------------

When it comes to defining a custom scheduler filter, you could use a hint or
an extra spec. If you need a flavor extra spec anyway for some behavior in the
hypervisor when creating the guest, or to be able to retrieve the original
flavor extra specs used to create a guest later, then you might as well just
use the extra spec. If you do not need that, then a scheduler hint may be an
obvious choice, from an end user perspective, for exposing a certain scheduling
behavior but it must be well documented and the end user should realize that
hint might not be available in other clouds, and they do not have a good way
of finding that out either. Long-term, flavor extra specs are likely to be
more standardized than hints so ultimately extra specs are the recommended
choice.

Footnotes
---------

.. [1] https://opendev.org/openstack/nova/src/commit/fbe6f77bc1cb41f5d6cfc24ece54d3413f997aab/nova/objects/image_meta.py#L225
.. [2] https://review.opendev.org/#/c/440580/
.. [3] https://docs.openstack.org/nova/latest/user/flavors.html#extra-specs
.. [4] https://opendev.org/openstack/nova/src/commit/fbe6f77bc1cb41f5d6cfc24ece54d3413f997aab/nova/api/openstack/compute/schemas/scheduler_hints.py
