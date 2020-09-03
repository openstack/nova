=================
nova-api-metadata
=================

.. program:: nova-api-metadata

Synopsis
========

::

  nova-api-metadata [<options>...]

Description
===========

:program:`nova-api-metadata` is a server daemon that serves the Nova Metadata
API. This daemon routes database requests via the ``nova-conductor`` service,
so there are some considerations about using this in a
:ref:`multi-cell layout <cells-v2-layout-metadata-api>`.

Options
=======

**General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/api-paste.ini``
* ``/etc/nova/policy.yaml``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* :nova-doc:`OpenStack Nova <>`
* :nova-doc:`Using WSGI with Nova <wsgi.html>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
