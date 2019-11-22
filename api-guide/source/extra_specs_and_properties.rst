=======================================
Flavor Extra Specs and Image Properties
=======================================

Flavor extra specs and image properties are used to control certain aspects
or scheduling behavior for a server.

The flavor of a server can be changed during a
:nova-doc:`resize </user/resize>` operation.

The image of a server can be changed during a
:nova-doc:`rebuild </contributor/evacuate-vs-rebuild>` operation.

By default, flavor extra specs are controlled by administrators of the cloud.
If users are authorized to upload their own images to the image service, they
may be able to specify their own image property requirements.

There are many cases of flavor extra specs and image properties that are for
the same functionality. In many cases the image property takes precedence over
the flavor extra spec if both are used in the same server.

Flavor Extra Specs
==================

Refer to the :nova-doc:`user guide </user/flavors.html#extra-specs>` for a
list of official extra specs.

While there are standard extra specs, deployments can define their own extra
specs to be used with host aggregates and custom scheduler filters as
necessary. See the
:nova-doc:`reference guide </reference/scheduler-hints-vs-flavor-extra-specs>`
for more details.

Image Properties
================

Refer to the image service documentation for a list of official
:glance-doc:`image properties </admin/useful-image-properties>` and
:glance-doc:`metadata definition concepts </user/metadefs-concepts>`.

Unlike flavor extra specs, image properties are standardized in the compute
service and thus they must be `registered`_ within the compute service before
they can be used.

.. _registered: https://opendev.org/openstack/nova/src/branch/master/nova/objects/image_meta.py
