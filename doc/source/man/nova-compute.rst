============
nova-compute
============

---------------------
Nova Compute Server
---------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-compute [options]

DESCRIPTION
===========

Handles all processes relating to instances (guest vms).  nova-compute is
responsible for building a disk image, launching it via the
underlying virtualization driver, responding to calls to check its state,
attaching persistent storage, and terminating it.

OPTIONS
=======

 **General options**

FILES
========

* /etc/nova/nova.conf
* /etc/nova/policy.json
* /etc/nova/rootwrap.conf
* /etc/nova/rootwrap.d/

SEE ALSO
========

* `OpenStack Nova <https://docs.openstack.org/developer/nova>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__
