===================
nova-api-os-compute
===================

.. program:: nova-api-os-compute

Synopsis
========

::

  nova-api-os-compute [<options>...]

Description
===========

:program:`nova-api-os-compute` is a server daemon that serves the Nova
OpenStack Compute API.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/api-paste.ini``
* ``/etc/nova/policy.yaml``
* ``/etc/nova/policy.d/``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

:doc:`nova-api(1) <nova-api>`,
:doc:`nova-api-metadata(1) <nova-api-metadata>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
