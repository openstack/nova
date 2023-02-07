============
nova-compute
============

.. program:: nova-compute

Synopsis
========

::

  nova-compute [<options>...]

Description
===========

:program:`nova-compute` is a server daemon that serves the Nova Compute
service, which is responsible for building a disk image, launching an instance
via the underlying virtualization driver, responding to calls to check the
instance's state, attaching persistent storage, and terminating the instance.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Files
=====

.. todo: We shouldn't have policy configuration in this non-API service, but
   bug #1675486 means we do have one

* ``/etc/nova/nova.conf``
* ``/etc/nova/policy.yaml``
* ``/etc/nova/policy.d/``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``
* ``/etc/nova/compute_id``
* ``/var/lib/nova/compute_id``

See Also
========

:doc:`nova-conductor(1) <nova-conductor>`,
:doc:`nova-manage(1) <nova-manage>`,
:doc:`nova-rootwrap(1) <nova-rootwrap>`,
:doc:`nova-scheduler(1) <nova-scheduler>`,
:doc:`nova-status(1) <nova-status>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
