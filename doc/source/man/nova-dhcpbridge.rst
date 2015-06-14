===============
nova-dhcpbridge
===============

--------------------------------------------------
Handles Lease Database updates from DHCP servers
--------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-dhcpbridge [options]

DESCRIPTION
===========

Handles lease database updates from DHCP servers. Used whenever nova is
managing DHCP (vlan and flatDHCP). nova-dhcpbridge should not be run as a daemon.

OPTIONS
=======

 **General options**

FILES
========

* /etc/nova/nova.conf
* /etc/nova/api-paste.ini
* /etc/nova/policy.json
* /etc/nova/rootwrap.conf
* /etc/nova/rootwrap.d/

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__
