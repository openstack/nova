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

`nova-network` is a server daemon that serves the Nova Network service, which
is responsible for allocating IPs and setting up the network

.. warning::

   `nova-network` is deprecated and will be removed in an upcoming release. Use
   `neutron` or another networking solution instead.

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
