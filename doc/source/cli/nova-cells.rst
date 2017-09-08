==========
nova-cells
==========

-------------------------
Server for the Nova Cells
-------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-cells [options]

Description
===========

Starts the `nova-cells` service.

The `nova-cells` service handles communication between cells and selects cells
for new instances.

.. warning:: Everything in this document is referring to Cells v1, which is
    not recommended for new deployments and is deprecated in favor of Cells v2
    as of the 16.0.0 Pike release. For information about commands to use
    with Cells v2, see the man page for :ref:`man-page-cells-v2`.

Options
=======

 **General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/policy.json``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* `OpenStack Nova <https://docs.openstack.org/nova/latest/>`__

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
