Managing Users
==============

.. todo:: is itsec a valid nova user role?

.. todo:: need samples of adding/removing user roles

Role-based access control (RBAC) is an approach to restricting system access to authorized users based on an individual’s role within an organization.  Various employee functions require certain levels of system access in order to be successful.  These functions are mapped to defined roles and individuals are categorized accordingly.  Since users are not assigned permissions directly, but only acquire them through their role (or roles), management of individual user rights becomes a matter of assigning appropriate roles to the user.  This simplifies common operations, such as adding a user, or changing a user's department.

Nova’s rights management system employs the RBAC model and currently supports the following five roles:

* **Cloud Administrator.**  (admin) Users of this class enjoy complete system access.
* **IT Security.** (itsec) This role is limited to IT security personnel.  It permits role holders to quarantine instances.
* **Project Manager.** (projectmanager)The default for project owners, this role affords users the ability to add other users to a project, interact with project images, and launch and terminate instances.
* **Network Administrator.** (netadmin) Users with this role are permitted to allocate and assign publicly accessible IP addresses as well as create and modify firewall rules.
* **Developer.**  This is a general purpose role that is assigned to users by default.

RBAC management is exposed through the dashboard for simplified user management.

Nova Administrators
-------------------
Personnel tasked with user and project administration have access to an additional suite of administrative tools that enable:

* Adding and Removing Users
* Managing user roles
* Adding and Removing Projects
* Controlling project VPNs
* Sending user credentials, including VPN certifications, configuration, and a file useful for command line API access. [#f92]_


User Maintenance
~~~~~~~~~~~~~~~~

Users, including admins, are created through the ``user`` commands.

* user admin: creates a new admin and prints exports
    * arguments: name [access] [secret]
* user create: creates a new user and prints exports
    * arguments: name [access] [secret]
* user delete: deletes an existing user
    * arguments: name
* user exports: prints access and secrets for user in export format
    * arguments: name
* user list: lists all users
    * arguments: none
* user modify: update a users keys & admin flag
    *  arguments: accesskey secretkey admin
    *  leave any field blank to ignore it, admin should be 'T', 'F', or blank


User Role Management
~~~~~~~~~~~~~~~~~~~~

* role add: adds role to user
    * if project is specified, adds project specific role
    * arguments: user, role [project]
* role has: checks to see if user has role
    * if project is specified, returns True if user has
      the global role and the project role
    * arguments: user, role [project]
* role remove: removes role from user
    * if project is specified, removes project specific role
    * arguments: user, role [project]
