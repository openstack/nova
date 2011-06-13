===========
nova-manage
===========

------------------------------------------------------
control and manage cloud computer instances and images
------------------------------------------------------

:Author: openstack@lists.launchpad.net
:Date:   2010-11-16
:Copyright: OpenStack LLC
:Version: 0.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-manage <category> <action> [<args>]

DESCRIPTION
===========

nova-manage controls cloud computing instances by managing nova users, nova projects, nova roles, shell selection, vpn connections, and floating IP address configuration. More information about OpenStack Nova is at http://nova.openstack.org.

OPTIONS
=======

The standard pattern for executing a nova-manage command is:
``nova-manage <category> <command> [<args>]``

For example, to obtain a list of all projects:
``nova-manage project list``

Run without arguments to see a list of available command categories:
``nova-manage``

Categories are user, project, role, shell, vpn, and floating. Detailed descriptions are below.

You can also run with a category argument such as user to see a list of all commands in that category:
``nova-manage user``

These sections describe the available categories and arguments for nova-manage.

Nova Db
~~~~~~~

``nova-manage db version``

    Print the current database version.

``nova-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

Nova User
~~~~~~~~~

``nova-manage user admin <username>``

    Create an admin user with the name <username>.

``nova-manage user create <username>``

    Create a normal user with the name <username>.

``nova-manage user delete <username>``

    Delete the user with the name <username>.

``nova-manage user exports <username>``

    Outputs a list of access key and secret keys for user to the screen

``nova-manage user list``

    Outputs a list of all the user names to the screen.

``nova-manage user modify <accesskey> <secretkey> <admin?T/F>``

    Updates the indicated user keys, indicating with T or F if the user is an admin user. Leave any argument blank if you do not want to update it.

Nova Project
~~~~~~~~~~~~

``nova-manage project add <projectname>``

    Add a nova project with the name <projectname> to the database.

``nova-manage project create <projectname>``

    Create a new nova project with the name <projectname> (you still need to do nova-manage project add <projectname> to add it to the database).

``nova-manage project delete <projectname>``

    Delete a nova project with the name <projectname>.

``nova-manage project environment <projectname> <username>``

    Exports environment variables for the named project to a file named novarc.

``nova-manage project list``

    Outputs a list of all the projects to the screen.

``nova-manage project quota <projectname>``

    Outputs the size and specs of the project's instances including gigabytes, instances, floating IPs, volumes, and cores.

``nova-manage project remove <projectname>``

    Deletes the project with the name <projectname>.

``nova-manage project zipfile``

    Compresses all related files for a created project into a zip file nova.zip.

Nova Role
~~~~~~~~~

nova-manage role <action> [<argument>]
``nova-manage role add <username> <rolename> <(optional) projectname>``

    Add a user to either a global or project-based role with the indicated <rolename> assigned to the named user. Role names can be one of the following five roles: cloudadmin, itsec, sysadmin, netadmin, developer. If you add the project name as the last argument then the role is assigned just for that project, otherwise the user is assigned the named role for all projects.

``nova-manage role has <username> <projectname>``
    Checks the user or project and responds with True if the user has a global role with a particular project.

``nova-manage role remove <username> <rolename>``
    Remove the indicated role from the user.

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

    Displays a list of projects, their IP prot numbers, and what state they're in.

``nova-manage vpn run <projectname>``

    Starts the VPN for the named project.

``nova-manage vpn spawn``

    Runs all VPNs.

Nova Floating IPs
~~~~~~~~~~~~~~~~~

``nova-manage floating create <host> <ip_range>``

    Creates floating IP addresses for the named host by the given range.

``nova-manage floating delete <ip_range>``

    Deletes floating IP addresses in the range given.

``nova-manage floating list``

    Displays a list of all floating IP addresses.

Nova Flavor
~~~~~~~~~~~

``nova-manage flavor list``

    Outputs a list of all active flavors to the screen.

``nova-manage flavor list --all``

    Outputs a list of all flavors (active and inactive) to the screen.

``nova-manage flavor create <name> <memory> <vCPU> <local_storage> <flavorID> <(optional) swap> <(optional) RXTX Quota> <(optional) RXTX Cap>``

    creates a flavor with the following positional arguments:
     * memory (expressed in megabytes)
     * vcpu(s) (integer)
     * local storage (expressed in gigabytes)
     * flavorid (unique integer)
     * swap space (expressed in megabytes, defaults to zero, optional)
     * RXTX quotas (expressed in gigabytes, defaults to zero, optional)
     * RXTX cap (expressed in gigabytes, defaults to zero, optional)

``nova-manage flavor delete <name>``

    Delete the flavor with the name <name>. This marks the flavor as inactive and cannot be launched. However, the record stays in the database for archival and billing purposes.

``nova-manage flavor delete <name> --purge``

    Purges the flavor with the name <name>. This removes this flavor from the database.

Nova Instance_type
~~~~~~~~~~~~~~~~~~

The instance_type command is provided as an alias for the flavor command. All the same subcommands and arguments from nova-manage flavor can be used.

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


FILES
========

The nova-manage.conf file contains configuration information in the form of python-gflags.

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__
* `OpenStack Swift <http://swift.openstack.org>`__

BUGS
====

* Nova is sourced in Launchpad so you can view current bugs at `OpenStack Nova <http://nova.openstack.org>`__



