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


Securing live migration streams with QEMU-native TLS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It is strongly recommended to secure all the different live migration
streams of a nova instance—i.e. guest RAM, device state, and disks (via
NBD) when using non-shared storage.  For further details on how to set
this up, refer to the
:doc:`secure-live-migration-with-qemu-native-tls` document.


Mitigation for MDS (Microarchitectural Data Sampling) security flaws
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It is strongly recommended to patch all compute nodes and nova instances
against the processor-related security flaws, such as MDS (and other
previous vulnerabilities).  For details on applying mitigation for the
MDS flaws, refer to the :doc:`mitigation-for-Intel-MDS-security-flaws`
document.
