Managing Users
==============


Users and Access Keys
---------------------

Access to the ec2 api is controlled by an access and secret key.  The user's access key needs to be included in the request, and the request must be signed with the secret key.  Upon receipt of api requests, nova will verify the signature and execute commands on behalf of the user.

In order to begin using nova, you will need a to create a user.  This can be easily accomplished using the user create or user admin commands in nova-manage. `user create` will create a regular user, whereas `user admin` will create an admin user. The syntax of the command is nova-manage user create username [access] [secret]. For example::

  nova-manage user create john my-access-key a-super-secret-key

If you do not specify an access or secret key, a random uuid will be created automatically.

Credentials
-----------

Nova can generate a handy set of credentials for a user.  These credentials include a CA for bundling images and a file for setting environment variables to be used by euca2ools.  If you don't need to bundle images, just the environment script is required.  You can export one with the `project environment` command.  The syntax of the command is nova-manage project environment project_id user_id [filename]. If you don't specify a filename, it will be exported as novarc.  After generating the file, you can simply source it in bash to add the variables to your environment::

  nova-manage project environment john_project john
  . novarc

If you do need to bundle images, you will need to get all of the credentials using `project zipfile`. Note that zipfile will give you an error message if networks haven't been created yet.  Otherwise zipfile has the same syntax as environment, only the default file name is nova.zip.  Example usage::

  nova-manage project zipfile john_project john
  unzip nova.zip
  . novarc

Role Based Access Control
-------------------------
Roles control the api actions that a user is allowed to perform.  For example, a user cannot allocate a public ip without the `netadmin` role. It is important to remember that a users de facto permissions in a project is the intersection of user (global) roles and project (local) roles.  So for john to have netadmin permissions in his project, he needs to separate roles specified.  You can add roles with `role add`.  The syntax is nova-manage role add user_id role [project_id]. Let's give john the netadmin role for his project::

  nova-manage role add john netadmin
  nova-manage role add john netadmin john_project

Role-based access control (RBAC) is an approach to restricting system access to authorized users based on an individual’s role within an organization.  Various employee functions require certain levels of system access in order to be successful.  These functions are mapped to defined roles and individuals are categorized accordingly.  Since users are not assigned permissions directly, but only acquire them through their role (or roles), management of individual user rights becomes a matter of assigning appropriate roles to the user.  This simplifies common operations, such as adding a user, or changing a user's department.

Nova’s rights management system employs the RBAC model and currently supports the following five roles:

* **Cloud Administrator.**  (cloudadmin) Users of this class enjoy complete system access.
* **IT Security.** (itsec) This role is limited to IT security personnel.  It permits role holders to quarantine instances.
* **System Administrator.** (sysadmin) The default for project owners, this role affords users the ability to add other users to a project, interact with project images, and launch and terminate instances.
* **Network Administrator.** (netadmin) Users with this role are permitted to allocate and assign publicly accessible IP addresses as well as create and modify firewall rules.
* **Developer.**  (developer) This is a general purpose role that is assigned to users by default.

RBAC management is exposed through the dashboard for simplified user management.


User Commands
~~~~~~~~~~~~

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
