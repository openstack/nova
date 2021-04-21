========
nova-api
========

.. program:: nova-api

Synopsis
========

::

  nova-api [<options>...]

Description
===========

:program:`nova-api` is a server daemon that serves the metadata and compute
APIs in separate greenthreads.

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

:doc:`nova-api-metadata(1) <nova-api-metadata>`,
:doc:`nova-api-os-compute(1) <nova-api-os-compute>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
