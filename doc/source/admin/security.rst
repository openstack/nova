==================
Security hardening
==================

OpenStack Compute can be integrated with various third-party technologies to
increase security. For more information, see the `OpenStack Security Guide
<https://docs.openstack.org/security-guide/>`_.

Encrypt Compute metadata traffic
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Enabling SSL encryption**

OpenStack supports encrypting Compute metadata traffic with HTTPS.  Enable SSL
encryption in the ``metadata_agent.ini`` file.

#. Enable the HTTPS protocol.

   .. code-block:: ini

      nova_metadata_protocol = https

#. Determine whether insecure SSL connections are accepted for Compute metadata
   server requests. The default value is ``False``.

   .. code-block:: ini

      nova_metadata_insecure = False

#. Specify the path to the client certificate.

   .. code-block:: ini

      nova_client_cert = PATH_TO_CERT

#. Specify the path to the private key.

   .. code-block:: ini

      nova_client_priv_key = PATH_TO_KEY
