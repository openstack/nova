==========
nova-cells
==========

-------------------------
Server for the Nova Cells
-------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-cells [options]

Description
===========

:program:`nova-cells` is a server daemon that serves the Nova Cells service,
which handles communication between cells and selects cells for new instances.

.. deprecated:: 16.0.0
    Everything in this document is referring to Cells v1, which is
    not recommended for new deployments and is deprecated in favor of Cells v2
    as of the 16.0.0 Pike release. For information about commands to use
    with Cells v2, see the man page for :ref:`man-page-cells-v2`.

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
