.. _service_user_token:

===================
Service User Tokens
===================

.. note::

   Configuration of service user tokens is **required** for every Nova service
   for security reasons. See https://bugs.launchpad.net/nova/+bug/2004555 for
   details.

Configure Nova to send service user tokens alongside regular user tokens when
making REST API calls to other services. The identity service (Keystone) will
authenticate a request using the service user token if the regular user token
has expired.

This is important when long-running operations such as live migration or
snapshot take long enough to exceed the expiry of the user token. Without the
service token, if a long-running operation exceeds the expiry of the user
token, post operations such as cleanup after a live migration could fail when
Nova calls other service APIs like block-storage (Cinder) or networking
(Neutron).

The service token is also used by services to validate whether the API caller
is a service. Some service APIs are restricted to service users only.

To set up service tokens, create a ``nova`` service user and ``service`` role
in the identity service (Keystone) and assign the ``service`` role to the
``nova`` service user.

Then, configure the :oslo.config:group:`service_user` section of the Nova
configuration file, for example:

.. code-block:: ini

   [service_user]
   send_service_user_token = true
   auth_url = https://104.130.216.102/identity
   auth_strategy = keystone
   auth_type = password
   project_domain_name = Default
   project_name = service
   user_domain_name = Default
   username = nova
   password = secretservice
   ...

And configure the other identity options as necessary for the service user,
much like you would configure nova to work with the image service (Glance) or
networking service (Neutron).

.. note::

   Please note that the role assigned to the :oslo.config:group:`service_user`
   needs to be in the configured
   :oslo.config:option:`keystone_authtoken.service_token_roles` of other
   services such as block-storage (Cinder), image (Glance), and networking
   (Neutron).
