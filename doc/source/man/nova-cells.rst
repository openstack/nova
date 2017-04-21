==========
nova-cells
==========

--------------------------------
Server for the Nova Cells
--------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-cells [options]

DESCRIPTION
===========

Starts the nova-cells service.

The nova-cells service handles communication between cells and selects cells
for new instances.

.. warning:: Everything in this document is referring to Cells v1, which is
    not recommended for new deployments. For information about commands to use
    with Cells v2, see the man page for :ref:`man-page-cells-v2`.

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
