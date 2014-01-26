=====================
nova-baremetal-manage
=====================

------------------------------------------------------
Manage bare-metal DB in OpenStack Nova
------------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-10-17
:Copyright: OpenStack Foundation
:Version: 2013.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-baremetal-manage <category> <action> [<args>]

DESCRIPTION
===========

nova-baremetal-manage manages bare-metal DB schema.

OPTIONS
=======

The standard pattern for executing a nova-baremetal-manage command is:
``nova-baremetal-manage <category> <command> [<args>]``

Run without arguments to see a list of available command categories:
``nova-baremetal-manage``

Categories are db. Detailed descriptions are below.

You can also run with a category argument such as "db" to see a list of all commands in that category:
``nova-baremetal-manage db``

These sections describe the available categories and arguments for nova-baremetal-manage.

Bare-Metal DB
~~~~~~~~~~~~~

``nova-baremetal-manage db version``

    Print the current database version.

``nova-baremetal-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

FILES
========

/etc/nova/nova.conf: get location of bare-metal DB

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__

