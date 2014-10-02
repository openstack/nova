===========
nova-manage
===========

------------------------------------------------------
control and manage cloud computer instances and images
------------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-04-05
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-manage <category> <action> [<args>]

DESCRIPTION
===========

nova-manage controls cloud computing instances by managing shell selection, vpn connections, and floating IP address configuration. More information about OpenStack Nova is at http://nova.openstack.org.

OPTIONS
=======

The standard pattern for executing a nova-manage command is:
``nova-manage <category> <command> [<args>]``

Run without arguments to see a list of available command categories:
``nova-manage``

Categories are project, shell, vpn, and floating. Detailed descriptions are below.

You can also run with a category argument such as user to see a list of all commands in that category:
``nova-manage floating``

These sections describe the available categories and arguments for nova-manage.

Nova Db
~~~~~~~

``nova-manage db version``

    Print the current database version.

``nova-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

Nova Logs
~~~~~~~~~

``nova-manage logs errors``

    Displays nova errors from log files.

``nova-manage logs syslog <number>``

    Displays nova alerts from syslog.

Nova Shell
~~~~~~~~~~

``nova-manage shell bpython``

    Starts a new bpython shell.

``nova-manage shell ipython``

    Starts a new ipython shell.

``nova-manage shell python``

    Starts a new python shell.

``nova-manage shell run``

    Starts a new shell using python.

``nova-manage shell script <path/scriptname>``

    Runs the named script from the specified path with flags set.

Nova VPN
~~~~~~~~

``nova-manage vpn list``

    Displays a list of projects, their IP port numbers, and what state they're in.

``nova-manage vpn run <projectname>``

    Starts the VPN for the named project.

``nova-manage vpn spawn``

    Runs all VPNs.

Nova Floating IPs
~~~~~~~~~~~~~~~~~

``nova-manage floating create <ip_range> [--pool <pool>] [--interface <interface>]``

    Creates floating IP addresses for the given range, optionally specifying
    a floating pool and a network interface.

``nova-manage floating delete <ip_range>``

    Deletes floating IP addresses in the range given.

``nova-manage floating list``

    Displays a list of all floating IP addresses.

Nova Images
~~~~~~~~~~~

``nova-manage image image_register <path> <owner>``

    Registers an image with the image service.

``nova-manage image kernel_register <path> <owner>``

    Registers a kernel with the image service.

``nova-manage image ramdisk_register <path> <owner>``

    Registers a ramdisk with the image service.

``nova-manage image all_register <image_path> <kernel_path> <ramdisk_path> <owner>``

    Registers an image kernel and ramdisk with the image service.

``nova-manage image convert <directory>``

    Converts all images in directory from the old (Bexar) format to the new format.

Nova VM
~~~~~~~~~~~

``nova-manage vm list [host]``
    Show a list of all instances. Accepts optional hostname (to show only instances on specific host).

``nova-manage live-migration <ec2_id> <destination host name>``
    Live migrate instance from current host to destination host. Requires instance id (which comes from euca-describe-instance) and destination host name (which can be found from nova-manage service list).


SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__



