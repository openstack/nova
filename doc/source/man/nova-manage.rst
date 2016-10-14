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
``nova-manage db``

These sections describe the available categories and arguments for nova-manage.

Nova Db
~~~~~~~

``nova-manage db version``

    Print the current main database version.

``nova-manage db sync``

    Sync the main database up to the most recent version. This is the standard way to create the db as well.

``nova-manage db archive_deleted_rows [--max_rows <number>] [--verbose]``

    Move deleted rows from production tables to shadow tables. Specifying
    --verbose will print the results of the archive operation for any tables
    that were changed.

``nova-manage db null_instance_uuid_scan [--delete]``

    Lists and optionally deletes database records where instance_uuid is NULL.

Nova ApiDb
~~~~~~~~~~

``nova-manage api_db version``

    Print the current cells api database version.

``nova-manage api_db sync``

    Sync the api cells database up to the most recent version. This is the standard way to create the db as well.

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

Nova Project
~~~~~~~~~~~~

``nova-manage project quota <project_id> [--user <user_id>] [--key <key>] [--value <value>]``

    Create, update or display quotas for project/user.  If a key is
    not specified then the current usages are displayed.

``nova-manage project quota_usage_refresh <project_id> [--user <user_id>] [--key <key>]``

    Refresh the quota usages for the project/user so that the
    usage record matches the actual used.  If a key is not specified
    then all quota usages relevant to the project/user are refreshed.

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

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__



