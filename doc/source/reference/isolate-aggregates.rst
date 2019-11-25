..
      Copyright 2019 NTT DATA

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Filtering hosts by isolating aggregates
=======================================

Background
-----------

I want to set up an aggregate ``ABC`` with hosts that allow you to run only
certain licensed images. I could tag the aggregate with metadata such as
``<LICENSED=WINDOWS>``. Then if I boot an instance with an image containing the
property ``<LICENSED=WINDOWS>``, it will land on one of the hosts in aggregate
``ABC``. But if the user creates a new image which does not include
``<LICENSED=WINDOWS>`` metadata, an instance booted with that image could still
land on a host in aggregate ``ABC`` as reported in launchpad bug `1677217`_.
The :ref:`AggregateImagePropertiesIsolation` scheduler filter passes even
though the aggregate metadata ``<LICENSED=WINDOWS>`` is not present in the
image properties.

.. _1677217: https://bugs.launchpad.net/nova/+bug/1677217

Solution
--------

The above problem is addressed by blueprint
`placement-req-filter-forbidden-aggregates`_ which was implemented in the
20.0.0 Train release.

The following example assumes you have configured aggregate ``ABC`` and added
hosts ``HOST1`` and ``HOST2`` to it in Nova, and that you want to isolate those
hosts to run only instances requiring Windows licensing.

#. Set the :oslo.config:option:`scheduler.enable_isolated_aggregate_filtering`
   config option to ``true`` in nova.conf and restart the nova-scheduler
   service.

#. Add trait ``CUSTOM_LICENSED_WINDOWS`` to the resource providers for
   ``HOST1`` and ``HOST2`` in the Placement service.

   First create the ``CUSTOM_LICENSED_WINDOWS`` trait

   .. code-block:: console

     # openstack --os-placement-api-version 1.6 trait create CUSTOM_LICENSED_WINDOWS

   Assume ``<HOST1_UUID>`` is the UUID of ``HOST1``, which is the same as its resource provider UUID.

   Start to build the command line by first collecting existing traits for ``HOST1``

   .. code-block:: console

     # traits=$(openstack --os-placement-api-version 1.6 resource provider trait list -f value <HOST1_UUID> | sed 's/^/--trait /')

   Replace ``HOST1``\ 's traits, adding ``CUSTOM_LICENSED_WINDOWS``

   .. code-block:: console

     # openstack --os-placement-api-version 1.6 resource provider trait set $traits --trait CUSTOM_LICENSED_WINDOWS <HOST1_UUID>

   Repeat the above steps for ``HOST2``.

#. Add the ``trait:CUSTOM_LICENSED_WINDOWS=required`` metadata property to
   aggregate ``ABC``.

   .. code-block:: console

     # openstack --os-compute-api-version 2.53 aggregate set --property trait:CUSTOM_LICENSED_WINDOWS=required ABC

As before, any instance spawned with a flavor or image containing
``trait:CUSTOM_LICENSED_WINDOWS=required`` will land on ``HOST1`` or ``HOST2``
because those hosts expose that trait.

However, now that the ``isolate_aggregates`` request filter is configured,
any instance whose flavor or image **does not** contain
``trait:CUSTOM_LICENSED_WINDOWS=required`` will **not** land on ``HOST1`` or
``HOST2`` because aggregate ``ABC`` requires that trait.

The above example uses a ``CUSTOM_LICENSED_WINDOWS`` trait, but you can use any
custom or `standard trait`_ in a similar fashion.

The filter supports the use of multiple traits across multiple aggregates. The
combination of flavor and image metadata must require **all** of the traits
configured on the aggregate in order to pass.

.. _placement-req-filter-forbidden-aggregates: https://specs.openstack.org/openstack/nova-specs/specs/train/approved/placement-req-filter-forbidden-aggregates.html
.. _standard trait: https://docs.openstack.org/os-traits/latest/
