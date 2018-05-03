=========================
Compute API configuration
=========================

The Compute API, is the component of OpenStack Compute that receives and
responds to user requests, whether they be direct API calls, or via the CLI
tools or dashboard.

Configure Compute API password handling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The OpenStack Compute API enables users to specify an administrative password
when they create, rebuild, rescue or evacuate a server instance.
If the user does not specify a password, a random password is generated
and returned in the API response.

In practice, how the admin password is handled depends on the hypervisor in use
and might require additional configuration of the instance.  For example, you
might have to install an agent to handle the password setting. If the
hypervisor and instance configuration do not support setting a password at
server create time, the password that is returned by the create API call is
misleading because it was ignored.

To prevent this confusion, set the ``enable_instance_password`` configuration
to ``False`` to disable the return of the admin password for installations that
do not support setting instance passwords.
