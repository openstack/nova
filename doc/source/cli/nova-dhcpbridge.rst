===============
nova-dhcpbridge
===============

------------------------------------------------
Handles Lease Database updates from DHCP servers
------------------------------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-dhcpbridge [options]

Description
===========

:program:`nova-dhcpbridge` is an application that handles lease database
updates from DHCP servers. :program:`nova-dhcpbridge` is used whenever nova is
managing DHCP (vlan and flatDHCP). :program:`nova-dhcpbridge` should not be run
as a daemon.

.. warning::

   This application is only for use with ``nova-network``, which is not
   recommended for new deployments.

Options
=======

**General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/api-paste.ini``
* ``/etc/nova/policy.json``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
