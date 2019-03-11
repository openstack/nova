==========================================
Secure live migration with QEMU-native TLS
==========================================

Context
~~~~~~~

The encryption offered by nova's
:oslo.config:option:`libvirt.live_migration_tunnelled` does not secure
all the different migration streams of a nova instance, namely: guest
RAM, device state, and disks (via NBD) when using non-shared storage.
Further, the "tunnelling via libvirtd" has inherent limitations: (a) it
cannot handle live migration of disks in a non-shared storage setup
(a.k.a. "block migration"); and (b) has a huge performance overhead and
latency, because it burns more CPU and memory bandwidth due to increased
number of data copies on both source and destination hosts.

To solve this existing limitation, QEMU and libvirt have gained (refer
:ref:`below <Prerequisites>` for version details) support for "native
TLS", i.e. TLS built into QEMU.  This will secure all data transports,
including disks that are not on shared storage, without incurring the
limitations of the "tunnelled via libvirtd" transport.

To take advantage of the "native TLS" support in QEMU and libvirt, nova
has introduced new configuration attribute
:oslo.config:option:`libvirt.live_migration_with_native_tls`.


.. _`Prerequisites`:

Prerequisites
~~~~~~~~~~~~~

(1) Version requirement: This feature needs at least libvirt 4.4.0 and
    QEMU 2.11.

(2) A pre-configured TLS environment—i.e. CA, server, and client
    certificates, their file permissions, et al—must be "correctly"
    configured (typically by an installer tool) on all relevant compute
    nodes.  To simplify your PKI (Public Key Infrastructure) setup, use
    deployment tools that take care of handling all the certificate
    lifecycle management.  For example, refer to the "`TLS everywhere
    <https://docs.openstack.org/tripleo-docs/latest/install/advanced_deployment/tls_everywhere.html>`__"
    guide from the TripleO project.

(3) Password-less SSH setup for all relevant compute nodes.

(4) On all relevant compute nodes, ensure the TLS-related config
    attributes in ``/etc/libvirt/qemu.conf`` are in place::

        default_tls_x509_cert_dir = "/etc/pki/qemu"
        default_tls_x509_verify = 1

    If it is not already configured, modify ``/etc/sysconfig/libvirtd``
    on both (ComputeNode1 & ComputeNode2) to listen for TCP/IP
    connections::

        LIBVIRTD_ARGS="--listen"

    Then, restart the libvirt daemon (also on both nodes)::

        $ systemctl restart libvirtd

    Refer to the "`Related information`_" section on a note about the
    other TLS-related configuration attributes in
    ``/etc/libvirt/qemu.conf``.


Validating your TLS environment on compute nodes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Assuming you have two compute hosts (``ComputeNode1``, and
``ComputeNode2``) run the :command:`virt-pki-validate` tool (comes with
the ``libvirt-client`` package on your Linux distribution) on both the
nodes to ensure all the necessary PKI files are configured are
configured::

    [ComputeNode1]$ virt-pki-validate
    Found /usr/bin/certtool
    Found CA certificate /etc/pki/CA/cacert.pem for TLS Migration Test
    Found client certificate /etc/pki/libvirt/clientcert.pem for ComputeNode1
    Found client private key /etc/pki/libvirt/private/clientkey.pem
    Found server certificate /etc/pki/libvirt/servercert.pem for ComputeNode1
    Found server private key /etc/pki/libvirt/private/serverkey.pem
    Make sure /etc/sysconfig/libvirtd is setup to listen to
    TCP/IP connections and restart the libvirtd service

    [ComputeNode2]$ virt-pki-validate
    Found /usr/bin/certtool
    Found CA certificate /etc/pki/CA/cacert.pem for TLS Migration Test
    Found client certificate /etc/pki/libvirt/clientcert.pem for ComputeNode2
    Found client private key /etc/pki/libvirt/private/clientkey.pem
    Found server certificate /etc/pki/libvirt/servercert.pem for ComputeNode2
    Found server private key /etc/pki/libvirt/private/serverkey.pem
    Make sure /etc/sysconfig/libvirtd is setup to listen to
    TCP/IP connections and restart the libvirtd service


Other TLS environment related checks on compute nodes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**IMPORTANT**: Ensure that the permissions of certificate files and keys
in ``/etc/pki/qemu/*`` directory on both source *and* destination
compute nodes to be the following ``0640`` with ``root:qemu`` as the
group/user.  For example, on a Fedora-based system::

        $ ls -lasrtZ /etc/pki/qemu
        total 32
        0 drwxr-xr-x. 10 root root system_u:object_r:cert_t:s0      110 Dec 10 10:39 ..
        4 -rw-r-----.  1 root qemu unconfined_u:object_r:cert_t:s0 1464 Dec 10 11:08 ca-cert.pem
        4 -rw-r-----.  1 root qemu unconfined_u:object_r:cert_t:s0 1558 Dec 10 11:08 server-cert.pem
        4 -rw-r-----.  1 root qemu unconfined_u:object_r:cert_t:s0 1619 Dec 10 11:09 client-cert.pem
        8 -rw-r-----.  1 root qemu unconfined_u:object_r:cert_t:s0 8180 Dec 10 11:09 client-key.pem
        8 -rw-r-----.  1 root qemu unconfined_u:object_r:cert_t:s0 8177 Dec 11 05:35 server-key.pem
        0 drwxr-xr-x.  2 root root unconfined_u:object_r:cert_t:s0  146 Dec 11 06:01 .


Performing the migration
~~~~~~~~~~~~~~~~~~~~~~~~

(1) On all relevant compute nodes, enable the
    :oslo.config:option:`libvirt.live_migration_with_native_tls`
    configuration attribute::

       [libvirt]
       live_migration_with_native_tls = true

    .. note::
        Setting both
        :oslo.config:option:`libvirt.live_migration_with_native_tls` and
        :oslo.config:option:`libvirt.live_migration_tunnelled` at the
        same time is invalid (and disallowed).

    And restart the ``nova-compute`` service::

        $ systemctl restart openstack-nova-compute

(2) Now that all TLS-related configuration is in place, migrate guests
    (with or without shared storage) from ``ComputeNode1`` to
    ``ComputeNode2``.  Refer to the :doc:`live-migration-usage` document
    on details about live migration.


.. _`Related information`:

Related information
~~~~~~~~~~~~~~~~~~~

- If you have the relevant libvirt and QEMU versions (mentioned in the
  "`Prerequisites`_" section earlier), then using the
  :oslo.config:option:`libvirt.live_migration_with_native_tls` is
  strongly recommended over the more limited
  :oslo.config:option:`libvirt.live_migration_tunnelled` option, which
  is intended to be deprecated in future.


- There are in total *nine* TLS-related config options in
  ``/etc/libvirt/qemu.conf``::

      default_tls_x509_cert_dir
      default_tls_x509_verify
      nbd_tls
      nbd_tls_x509_cert_dir
      migrate_tls_x509_cert_dir

      vnc_tls_x509_cert_dir
      spice_tls_x509_cert_dir
      vxhs_tls_x509_cert_dir
      chardev_tls_x509_cert_dir

  If you set both ``default_tls_x509_cert_dir`` and
  ``default_tls_x509_verify`` parameters for all certificates, there is
  no need to specify any of the other ``*_tls*`` config options.

  The intention (of libvirt) is that you can just use the
  ``default_tls_x509_*`` config attributes so that you don't need to set
  any other ``*_tls*`` parameters, _unless_ you need different
  certificates for some services.  The rationale for that is that some
  services (e.g.  migration / NBD)  are only exposed to internal
  infrastructure; while some sevices (VNC, Spice) might be exposed
  publically, so might need different certificates.  For OpenStack this
  does not matter, though, we will stick with the defaults.

- If they are not already open, ensure you open up these TCP ports on
  your firewall: ``16514`` (where the authenticated and encrypted TCP/IP
  socket will be listening on) and ``49152-49215`` (for regular
  migration) on all relevant compute nodes.   (Otherwise you get
  ``error: internal error: unable to execute QEMU command
  'drive-mirror': Failed to connect socket: No route to host``).
