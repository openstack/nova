================
nova-xvpvncproxy
================

----------------------------
XVP VNC Console Proxy Server
----------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-xvpvncproxy  [options]

Description
===========

:program:`nova-xvpvncproxy` is a server daemon that serves the Nova XVP VNC
Console Proxy service, which provides an XVP-based VNC Console Proxy for use
with the Xen hypervisor.

.. deprecated:: 19.0.0

   :program:`nova-xvpvnxproxy` is deprecated since 19.0.0 (Stein) and will be
   removed in an upcoming release.

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
