============================
nova-baremetal-deploy-helper
============================

------------------------------------------------------------------
Writes images to a bare-metal node and switch it to instance-mode
------------------------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-10-17
:Copyright: OpenStack Foundation
:Version: 2013.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-baremetal-deploy-helper

DESCRIPTION
===========

This is a service which should run on nova-compute host when using the
baremetal driver. During a baremetal node's first boot, 
nova-baremetal-deploy-helper works in conjunction with diskimage-builder's
"deploy" ramdisk to write an image from glance onto the baremetal node's disks
using iSCSI. After that is complete, nova-baremetal-deploy-helper switches the
PXE config to reference the kernel and ramdisk which correspond to the running
image.

OPTIONS
=======

 **General options**

FILES
========

* /etc/nova/nova.conf
* /etc/nova/rootwrap.conf
* /etc/nova/rootwrap.d/

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova is sourced in Launchpad so you can view current bugs at `OpenStack Nova <http://nova.openstack.org>`__
