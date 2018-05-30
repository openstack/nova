============
nova-network
============

-------------------
Nova Network Server
-------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-network [options]

Description
===========

:program:`nova-network` is a server daemon that serves the Nova Network
service, which is responsible for allocating IPs and setting up the network

.. deprecated:: 14.0.0

   :program:`nova-network` is deprecated and will be removed in an upcoming
   release. Use *neutron* or another networking solution instead.

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

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
