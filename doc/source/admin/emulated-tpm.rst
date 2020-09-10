=======================================
Emulated Trusted Platform Module (vTPM)
=======================================

.. versionadded:: 22.0.0 (Victoria)

Starting in the 22.0.0 (Victoria) release, Nova supports adding an emulated
virtual `Trusted Platform Module`__ (vTPM) to guests.

.. __: https://en.wikipedia.org/wiki/Trusted_Platform_Module


Enabling vTPM
-------------

The following are required on each compute host wishing to support the vTPM
feature:

* Currently vTPM is only supported when using the libvirt compute driver with a
  :oslo.config:option:`libvirt.virt_type` of ``kvm`` or ``qemu``.

* A `key manager service`__, such as `barbican`__, must be configured to store
  secrets used to encrypt the virtual device files at rest.

* QEMU version >= 2.11 (>= 2.12 is recommended)

* Libvirt version >= 5.6.0

* The swtpm__ binary and associated libraries__.

* Set the :oslo.config:option:`libvirt.swtpm_enabled` config option to
  ``True``. This will enable support for both TPM version 1.2 and 2.0.

With the above requirements satisfied, verify vTPM support by inspecting the
traits on the compute node's resource provider:

.. code:: console

   $ openstack resource provider trait list $compute_uuid | grep SECURITY_TPM
   | COMPUTE_SECURITY_TPM_1_2 |
   | COMPUTE_SECURITY_TPM_2_0 |

.. __: https://docs.openstack.org/api-guide/key-manager/
.. __: https://docs.openstack.org/barbican/latest/
.. __: https://github.com/stefanberger/swtpm/wiki
.. __: https://github.com/stefanberger/libtpms/


Configuring a flavor or image
-----------------------------

A vTPM can be requested on a server via :ref:`flavor extra_specs <vtpm-flavor>`
or image metadata properties.

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

Scheduling will fail if flavor and image supply conflicting values, or if model
``tpm-crb`` is requested with version ``1.2``.

Upon successful boot, the server should see a TPM device such as ``/dev/tpm0``
which can be used in the same manner as a hardware TPM.


Limitations
-----------

* Only server operations performed by the server owner are supported, as the
  user's credentials are required to unlock the virtual device files on the
  host. Thus the admin may need to decide whether to grant the user additional
  policy roles; if not, those operations are effectively disabled.

* Live migration, evacuation, shelving and rescuing of servers with vTPMs is
  not currently supported.


Security
--------

With a hardware TPM, the root of trust is a secret known only to the TPM user.
In contrast, an emulated TPM comprises a file on disk which the libvirt daemon
must be able to present to the guest. At rest, this file is encrypted using a
passphrase stored in a key manager service. The passphrase in the key manager
is associated with the credentials of the owner of the server (the user who
initially created it). The passphrase is retrieved and used by libvirt to
unlock the emulated TPM data any time the server is booted.

Although the above mechanism uses a libvirt secret__ that is both ``private``
(can't be displayed via the libvirt API or ``virsh``) and ``ephemeral`` (exists
only in memory, never on disk), it is theoretically possible for a sufficiently
privileged user to retrieve the secret and/or vTPM data from memory.

A full analysis and discussion of security issues related to emulated TPM is
beyond the scope of this document.

.. __: https://libvirt.org/formatsecret.html#SecretAttributes


References
----------

* `QEMU docs on tpm`__
* `Libvirt XML to request emulated TPM device`__
* `Libvirt secret for usage type ``vtpm```__

.. __: https://github.com/qemu/qemu/blob/stable-2.12/docs/specs/tpm.txt
.. __: https://libvirt.org/formatdomain.html#elementsTpm
.. __: https://libvirt.org/formatsecret.html#vTPMUsageType
