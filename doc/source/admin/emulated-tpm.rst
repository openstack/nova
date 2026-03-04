=======================================
Emulated Trusted Platform Module (vTPM)
=======================================

.. versionadded:: 22.0.0 (Victoria)

Starting in the 22.0.0 (Victoria) release, Nova supports adding an emulated
virtual `Trusted Platform Module`__ (vTPM) to guests.

.. versionadded:: 33.0.0 (2026.1 Gazpacho)

Starting in the 33.0.0 (2026.1 Gazpacho) release, Nova supports live migration
of guests with emulated vTPM for the ``host`` TPM secret security mode.

.. __: https://en.wikipedia.org/wiki/Trusted_Platform_Module


Enabling vTPM
-------------

The following are required on each compute host wishing to support the vTPM
feature:

* Currently vTPM is only supported when using the libvirt compute driver with a
  :oslo.config:option:`libvirt.virt_type` of ``kvm`` or ``qemu``.

* A `key manager service`__, such as `barbican`__, must be configured to store
  secrets used to encrypt the virtual device files at rest.

* The swtpm__ binary and associated libraries__.

* Set the :oslo.config:option:`libvirt.swtpm_enabled` config option to
  ``True``. This will enable support for both TPM version 1.2 and 2.0.

* Optionally set the :oslo.config:option:`libvirt.supported_tpm_secret_security`
  config option to configure which security modes to enable. The default is all
  modes enabled: ``user`` and ``host``. See the next section for more details
  about TPM secret security modes.

With the above requirements satisfied, verify vTPM support by inspecting the
traits on the compute node's resource provider:

.. code:: bash

   $ COMPUTE_UUID=$(openstack resource provider list --name $HOST -f value -c uuid)
   $ openstack resource provider trait list $COMPUTE_UUID | grep SECURITY_TPM
   | COMPUTE_SECURITY_TPM_1_2                        |
   | COMPUTE_SECURITY_TPM_2_0                        |
   | COMPUTE_SECURITY_TPM_CRB                        |
   | COMPUTE_SECURITY_TPM_TIS                        |
   | COMPUTE_SECURITY_TPM_SECRET_SECURITY_USER       |
   | COMPUTE_SECURITY_TPM_SECRET_SECURITY_HOST       |

.. __: https://docs.openstack.org/api-guide/key-manager/
.. __: https://docs.openstack.org/barbican/latest/
.. __: https://github.com/stefanberger/swtpm/wiki
.. __: https://github.com/stefanberger/libtpms/


Security
--------

With a hardware TPM, the root of trust is a secret known only to the TPM user.
In contrast, an emulated TPM comprises a file on disk which the libvirt daemon
must be able to present to the guest.

At rest, this file is encrypted using a passphrase stored in a key manager
service as a secret.

Nova supports a few different security modes that will control secret ownership
and visibility to the libvirt API. The passphrase is retrieved and used by
libvirt to unlock the emulated TPM data any time the server is booted.

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Mode
     - Description
   * - ``user``
     - The passphrase in the key manager is associated with the credentials of
       the owner of the server (the user who initially created it). The libvirt
       secret is both ``private`` and ``ephemeral``. A server with this
       security mode cannot be live migrated. This is the default mode.
       Existing servers that were created before 33.0.0 (2026.1 Gazpacho) will
       also have this mode.
   * - ``host``
     - The passphrase in the key manager is created using the credentials of
       the server owner (the user who initially created it). The libvirt
       secret is not ``private`` and not ``ephemeral``, which means it can be
       retrieved via the libvirt API or ``virsh`` and it exists on disk. A
       server with this security mode can be live migrated, including by users
       other than the server owner, if API policy allows. The key manager
       service is not accessed during live migration in this mode; the libvirt
       secret is sent to the destination host over RPC.

Although the above ``user`` mechanism uses a libvirt secret__ that is both
``private`` (can't be displayed via the libvirt API or ``virsh``) and
``ephemeral`` (exists only in memory, never on disk), it is theoretically
possible for a sufficiently privileged user to retrieve the secret and/or vTPM
data from memory.

A full analysis and discussion of security issues related to emulated TPM is
beyond the scope of this document.

.. __: https://libvirt.org/formatsecret.html#SecretAttributes


Configuring a flavor or image
-----------------------------

A vTPM can be requested on a server via flavor extra specs or image metadata
properties. There are two versions supported - 1.2 and 2.0 - and two models -
TPM Interface Specification (TIS) and Command-Response Buffer (CRB). The CRB
model is only supported with version 2.0.

.. list-table::
   :header-rows: 1

   * - Flavor extra_specs
     - Image metadata
     - Description
   * - ``hw:tpm_version``
     - ``hw_tpm_version``
     - Specify the TPM version, ``1.2`` or ``2.0``. Required if requesting a
       vTPM.
   * - ``hw:tpm_model``
     - ``hw_tpm_model``
     - Specify the TPM model, ``tpm-tis`` (the default) or ``tpm-crb`` (only
       valid with version ``2.0``.
   * - ``hw:tpm_secret_security``
     - \-
     - Specify the TPM secret security mode, ``user`` (the default) or
       ``host``.

For example, to configure a flavor to use the TPM 2.0 with the CRB model:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw:tpm_version=2.0 \
       --property hw:tpm_model=tpm-crb

Scheduling will fail if flavor and image supply conflicting values, or if model
``tpm-crb`` is requested with version ``1.2``.

Upon successful boot, the server should see a TPM device such as ``/dev/tpm0``
which can be used in the same manner as a hardware TPM.


Legacy servers and live migration
---------------------------------

A legacy server can be converted to a TPM secret security mode capable of live
migration via a resize to a flavor that has the ``hw:tpm_secret_security``
extra spec set to ``host``.

For example, set the extra spec in the flavor:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw:tpm_version=2.0 \
       --property hw:tpm_model=tpm-crb \
       --property hw:tpm_secret_security=host

Then, resize the server to the flavor:

.. code-block:: console

   $ openstack server resize --flavor $FLAVOR $SERVER

   $ openstack server resize confirm $SERVER

.. important::

   Access to the TPM secret in the key manager service is required to perform
   a resize. Whether a user other than the server owner has access depends on
   the key manager service's access control policy. See the key manager
   service documentation for details.


Limitations
-----------

* Rebuild, evacuate, shelve, and rescue of servers with vTPMs is not currently
  supported.

* Other limitations will depend on the TPM secret security mode of the server.

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Mode
     - Description
   * - ``user``
     - Only server operations performed by the server owner are supported, as
       the user's credentials are required to unlock the virtual device files
       on the host in this mode. Thus the admin may need to decide whether to
       grant the user additional policy roles or key manager service ACLs; if
       not, those operations are effectively disabled. Live migration is not
       supported in this mode.
   * - ``host``
     - Certain server operations performed by users other than the server
       owner are supported. Hard reboot, start from stopped, and live migration
       are supported if API policy allows, without accessing the key manager
       service. This is because nova-compute can read the locally stored
       libvirt secret from the server's compute host in this mode.


References
----------

* `TCG PC Client Specific TPM Interface Specification (TIS)`__
* `TCG PC Client Platform TPM Profile (PTP) Specification`__
* `QEMU docs on tpm`__
* `Libvirt XML to request emulated TPM device`__
* `Libvirt secret for usage type ``vtpm```__

.. __: https://trustedcomputinggroup.org/resource/pc-client-work-group-pc-client-specific-tpm-interface-specification-tis/
.. __: https://trustedcomputinggroup.org/resource/pc-client-platform-tpm-profile-ptp-specification/
.. __: https://qemu.readthedocs.io/en/latest/specs/tpm.html
.. __: https://libvirt.org/formatdomain.html#elementsTpm
.. __: https://libvirt.org/formatsecret.html#vTPMUsageType
