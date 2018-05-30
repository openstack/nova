============
nova-compute
============

-------------------
Nova Compute Server
-------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-compute [options]

Description
===========

:program:`nova-compute` is a server daemon that serves the Nova Compute
service, which is responsible for building a disk image, launching an instance
via the underlying virtualization driver, responding to calls to check the
instance's state, attaching persistent storage, and terminating the instance.

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
