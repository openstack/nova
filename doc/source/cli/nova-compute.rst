============
nova-compute
============

-------------------
Nova Compute Server
-------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-compute [options]

Description
===========

`nova-compute` is a server daemon that serves the Nova Compute service, which
is responsible for building a disk image, launching an instance via the
underlying virtualization driver, responding to calls to check the instance's
state, attaching persistent storage, and terminating the instance.

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
