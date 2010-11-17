===========
nova-manage
===========

------------------------------------------------------
control and manage cloud computer instances and images
------------------------------------------------------

:Author: nova@lists.launchpad.net
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

Run without arguments to see a list of available command categories. Categories are user, project, role, shell, vpn, and floating. Detailed descriptions are below.
::
nova-manage

You can also run with a category argument such as user to see a list of all commands in that category. 
::
nova-manage user

Here are the available categories and arguments for nova-manage: 

nova-manage user <action> [<argument>] 
	user admin <username>		Create an admin user with the name <username>.
	user create <username>		Create a normal user with the name <username>.
	user delete <username>		Delete the user with the name <username>.
	user exports <username>		Outputs a list of access key and secret keys for user to the screen
	user list 					Outputs a list of all the user names to the screen.
	user modify <accesskey> <secretkey> <admin?T/F>		Updates the indicated user keys, indicating with T or F if the user is an admin user. Leave any argument blank if you do not want to update it.
	
nova-manage project <action> [<argument>] 
	project	add <projectname>	Add a nova project with the name <projectname> to the database.
	project create <projectname>	Create a new nova project with the name <projectname> (you still need to do nova-manage project add <projectname> to add it to the database).
	project delete 				Delete a nova project with the name <projectname>.
	project environment <projectname> <username>		Exports environment variables for the named project to a file named novarc.
	project list 				Outputs a list of all the projects to the screen.
	project quota <projectname>		Outputs the size and specs of the project's instances including gigabytes, instances, floating IPs, volumes, and cores.
	project remove <projectname>	Deletes the project with the name <projectname>.
	project zipfile					Compresses all related files for a created project into a zip file nova.zip.
	
nova-manage role <action> [<argument>] 
	role add <username> <rolename> <(optional) projectname>			Add a user to either a global or project-based role with the indicated <rolename> assigned to the named user. Role names can be one of the following five roles: admin, itsec, projectmanager, netadmin, developer. If you add the project name as the last argument then the role is assigned just for that project, otherwise the user is assigned the named role for all projects. 
	role has <username> <projectname>		Checks the user or project and responds with True if the user has a global role with a particular project.
	role remove <username> <rolename>			Remove the indicated role from the user. 
	
nova-manage shell <action> [<argument>] 
	shell bpython		Starts a new bpython shell. 
	shell ipython		Starts a new ipython shell.
	shell python		Starts a new python shell.
	shell run			Starts a new shell using python.
	shell script <path/scriptname>	Runs the named script from the specified path with flags set.
	
nova-manage vpn <action> [<argument>]  
	vpn list		Displays a list of projects, their IP prot numbers, and what state they're in.
	vpn run	<projectname> 	Starts the VPN for the named project.		
	vpn spawn				Runs all VPNs.
	
nova-manage floating <action> [<argument>] 
	floating create <host> <ip_range>	Creates floating IP addresses for the named host by the given range.
	floating delete <ip_range>	Deletes floating IP addresses in the range given.
	floating list 			Displays a list of all floating IP addresses.
	
--help, -h              Show this help message and exit.

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



