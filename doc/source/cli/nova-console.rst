============
nova-console
============

-------------------
Nova Console Server
-------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-console [options]

Description
===========

:program:`nova-console` is a server daemon that serves the Nova Console
service, which is a console proxy to set up multi-tenant VM console access,
e.g. with *XVP*.

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
