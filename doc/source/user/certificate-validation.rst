Image Signature Certificate Validation
======================================
Nova can determine if the certificate used to generate and verify the signature
of a signed image (see `Glance Image Signature Verification documentation`_) is
trusted by the user. This feature is called certificate validation and can be
applied to the creation or rebuild of an instance.

Certificate validation is meant to be performed jointly with image signature
verification but each feature has its own Nova configuration option, to be
specified in the ``[glance]`` section of the ``nova.conf`` configuration file.
To enable certificate validation, set
:oslo.config:option:`glance.enable_certificate_validation` to True. To
enable signature validation, set
:oslo.config:option:`glance.verify_glance_signatures` to True.
Conversely, to disable either of these features, set their option to False or
do not include the option in the Nova configurations at all.

Certificate validation operates in concert with signature validation in
`Cursive`_. It takes in a list of trusted certificate IDs and verifies that the
certificate used to sign the image being booted is cryptographically linked to
at least one of the provided trusted certificates. This provides the user with
confidence in the identity and integrity of the image being booted.

Certificate validation will only be performed if image signature validation is
enabled. However, the presence of trusted certificate IDs overrides the
``enable_certificate_validation`` and ``verify_glance_signatures`` settings. In
other words, if a list of trusted certificate IDs is provided to the instance
create or rebuild commands, signature verification and certificate validation
will be performed, regardless of their settings in the Nova configurations.
See `Using Signature Verification`_ for details.

.. _Cursive: http://opendev.org/x/cursive/
.. _Glance Image Signature Verification documentation: https://docs.openstack.org/glance/latest/user/signature.html

.. note::
    Certificate validation configuration options must be specified in the Nova
    configuration file that controls the ``nova-osapi_compute`` and
    ``nova-compute`` services, as opposed to other Nova services (conductor,
    scheduler, etc.).

Requirements
------------
Key manager that is a backend to the `Castellan Interface`_. Possible key
managers are:

* `Barbican`_
* `Vault`_

.. _Castellan Interface: https://docs.openstack.org/castellan/latest/
.. _Barbican: https://docs.openstack.org/barbican/latest/contributor/devstack.html
.. _Vault: https://www.vaultproject.io/

Limitations
-----------

* As of the 18.0.0 Rocky release, only the libvirt compute driver supports
  trusted image certification validation. The feature is not, however, driver
  specific so other drivers should be able to support this feature over time.
  See the `feature support matrix`_ for information on which drivers support
  the feature at any given release.

* As of the 18.0.0 Rocky release, image signature and trusted image
  certification validation is not supported with the Libvirt compute driver
  when using the ``rbd`` image backend (``[libvirt]/images_type=rbd``) and
  ``RAW`` formatted images. This is due to the images being cloned directly in
  the ``RBD`` backend avoiding calls to download and verify on the compute.

* As of the 18.0.0 Rocky release, trusted image certification validation is
  not supported with volume-backed
  (:term:`boot from volume <Boot From Volume>`) instances. The block
  storage service support may be available in a future release:

  https://blueprints.launchpad.net/cinder/+spec/certificate-validate

* Trusted image certification support can be controlled via
  `policy configuration`_ if it needs to be disabled. See the
  ``os_compute_api:servers:create:trusted_certs`` and
  ``os_compute_api:servers:rebuild:trusted_certs`` policy rules.

.. _feature support matrix: https://docs.openstack.org/nova/latest/user/support-matrix.html#operation_trusted_certs
.. _policy configuration: https://docs.openstack.org/nova/latest/configuration/policy.html

Configuration
-------------
Nova will use the key manager defined by the Castellan key manager interface,
which is the Barbican key manager by default. To use a different key manager,
update the ``backend`` value in the ``[key_manager]`` group
of the nova configuration file. For example::

  [key_manager]
  backend = barbican

.. note:: If these lines do not exist, then simply add them to the end of the
          file.

Using Signature Verification
----------------------------

An image will need a few properties for signature verification to be enabled:

``img_signature``
  Signature of your image. Signature restrictions are:

  * 255 character limit


``img_signature_hash_method``
  Method used to hash your signature. Possible hash methods are:

  * SHA-224
  * SHA-256
  * SHA-384
  * SHA-512

``img_signature_key_type``
  Key type used for your image. Possible key types are:

  * RSA-PSS
  * DSA
  * ECC-CURVES

    * SECT571K1
    * SECT409K1
    * SECT571R1
    * SECT409R1
    * SECP521R1
    * SECP384R1

``img_signature_certificate_uuid``
  UUID of the certificate that you uploaded to the key manager. Possible certificate types are:

  * X_509

Using Certificate Validation
----------------------------
Certificate validation is triggered by one of two ways:

1. The Nova configuration options ``verify_glance_signatures`` and
   ``enable_certificate_validation`` are both set to True::

     [glance]
     verify_glance_signatures = True
     enable_certificate_validation = True

2. A list of trusted certificate IDs is provided by one of three ways:

   .. note:: The command line support is pending changes
      https://review.opendev.org/#/c/500396/ and
      https://review.opendev.org/#/c/501926/ to python-novaclient and
      python-openstackclient, respectively.

   Environment Variable
     Use the environment variable ``OS_TRUSTED_IMAGE_CERTIFICATE_IDS`` to
     define a comma-delimited list of trusted certificate IDs. For example:

     .. code-block:: console

       $ export OS_TRUSTED_IMAGE_CERTIFICATE_IDS=79a6ad17-3298-4e55-8b3a-1672dd93c40f,b20f5600-3c9d-4af5-8f37-3110df3533a0

   Command-Line Flag
     If booting or rebuilding an instance using the :command:`nova` commands,
     use the ``--trusted-image-certificate-id`` flag to define a single trusted
     certificate ID. The flag may be used multiple times to specify multiple trusted
     certificate IDs. For example:

     .. code-block:: console

       $ nova boot myInstanceName \
           --flavor 1 \
           --image myImageId \
           --trusted-image-certificate-id 79a6ad17-3298-4e55-8b3a-1672dd93c40f \
           --trusted-image-certificate-id b20f5600-3c9d-4af5-8f37-3110df3533a0

     If booting or rebuilding an instance using the :command:`openstack server` commands,
     use the ``--trusted-image-certificate-id`` flag to define a single trusted
     certificate ID. The flag may be used multiple times to specify multiple trusted
     certificate IDs. For example:

     .. code-block:: console

       $ openstack --os-compute-api-version=2.63 server create myInstanceName \
           --flavor 1 \
           --image myImageId \
           --nic net-id=fd25c0b2-b36b-45a8-82e4-ab52516289e5 \
           --trusted-image-certificate-id 79a6ad17-3298-4e55-8b3a-1672dd93c40f \
           --trusted-image-certificate-id b20f5600-3c9d-4af5-8f37-3110df3533a0

   Nova Configuration Option
     Use the Nova configuration option
     :oslo.config:option:`glance.default_trusted_certificate_ids` to
     define a comma-delimited list of trusted certificate IDs. This
     configuration value is only used if ``verify_glance_signatures`` and
     ``enable_certificate_validation`` options are set to True, and the trusted
     certificate IDs are not specified anywhere else. For example::

       [glance]
       default_trusted_certificate_ids=79a6ad17-3298-4e55-8b3a-1672dd93c40f,b20f5600-3c9d-4af5-8f37-3110df3533a0

Example Usage
-------------
For these instructions, we will construct a 4-certificate chain to illustrate
that it is possible to have a single trusted root certificate. We will upload
all four certificates to Barbican. Then, we will sign an image and upload it to
Glance, which will illustrate image signature verification.  Finally, we will
boot the signed image from Glance to show that certificate validation is
enforced.

Enable certificate validation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Enable image signature verification and certificate validation by setting both
of their Nova configuration options to True::

  [glance]
  verify_glance_signatures = True
  enable_certificate_validation = True

Create a certificate chain
^^^^^^^^^^^^^^^^^^^^^^^^^^
As mentioned above, we will construct a 4-certificate chain to illustrate that
it is possible to have a single trusted root certificate. Before we begin to
build our certificate chain, we must first create files for OpenSSL to use for
indexing and serial number tracking:

.. code-block:: console

  $ touch index.txt
  $ echo '01' > serial.txt

Create a certificate configuration file
"""""""""""""""""""""""""""""""""""""""
For these instructions, we will create a single configuration file called
``ca.conf``, which contains various sections that we can specify for use on the
command-line during certificate requests and generation.

Note that this certificate will be able to sign other certificates because it
is a certificate authority. Also note the root CA's unique common name
("root"). The intermediate certificates' common names will be specified on the
command-line when generating the corresponding certificate requests.

``ca.conf``::

  [ req ]
  prompt             = no
  distinguished_name = dn-param
  x509_extensions    = ca_cert_extensions

  [ ca ]
  default_ca = ca_default

  [ dn-param ]
  C  = US
  CN = Root CA

  [ ca_cert_extensions ]
  keyUsage         = keyCertSign, digitalSignature
  basicConstraints = CA:TRUE, pathlen:2

  [ ca_default ]
  new_certs_dir = .              # Location for new certs after signing
  database      = ./index.txt    # Database index file
  serial        = ./serial.txt   # The current serial number

  default_days  = 1000
  default_md    = sha256

  policy        = signing_policy
  email_in_dn   = no

  [ intermediate_cert_extensions ]
  keyUsage         = keyCertSign, digitalSignature
  basicConstraints = CA:TRUE, pathlen:1

  [client_cert_extensions]
  keyUsage         = keyCertSign, digitalSignature
  basicConstraints = CA:FALSE

  [ signing_policy ]
  countryName            = optional
  stateOrProvinceName    = optional
  localityName           = optional
  organizationName       = optional
  organizationalUnitName = optional
  commonName             = supplied
  emailAddress           = optional

Generate the certificate authority (CA) and corresponding private key
"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
For these instructions, we will save the certificate as ``cert_ca.pem`` and the
private key as ``key_ca.pem``. This certificate will be a self-signed root
certificate authority (CA) that can sign other CAs and non-CA certificates.

.. code-block:: console

  $ openssl req \
      -x509 \
      -nodes \
      -newkey rsa:1024 \
      -config ca.conf \
      -keyout key_ca.pem \
      -out cert_ca.pem

  Generating a 1024 bit RSA private key
  ............................++++++
  ...++++++
  writing new private key to 'key_ca.pem'
  -----

Create the first intermediate certificate
"""""""""""""""""""""""""""""""""""""""""
Create a certificate request for the first intermediate certificate. For these
instructions, we will save the certificate request as
``cert_intermeidate_a.csr`` and the private key as ``key_intermediate_a.pem``.

.. code-block:: console

  $ openssl req \
      -nodes \
      -newkey rsa:2048 \
      -subj '/CN=First Intermediate Certificate' \
      -keyout key_intermediate_a.pem \
      -out cert_intermediate_a.csr

  Generating a 2048 bit RSA private key
  .............................................................................................................+++
  .....+++
  writing new private key to 'key_intermediate_a.pem'
  -----

Generate the first intermediate certificate by signing its certificate request
with the CA. For these instructions we will save the certificate as
``cert_intermediate_a.pem``.

.. code-block:: console

  $ openssl ca \
      -config ca.conf \
      -extensions intermediate_cert_extensions \
      -cert cert_ca.pem \
      -keyfile key_ca.pem \
      -out cert_intermediate_a.pem \
      -infiles cert_intermediate_a.csr

  Using configuration from ca.conf
  Check that the request matches the signature
  Signature ok
  The Subject's Distinguished Name is as follows
  commonName            :ASN.1 12:'First Intermediate Certificate'
  Certificate is to be certified until Nov 15 16:24:21 2020 GMT (1000 days)
  Sign the certificate? [y/n]:y


  1 out of 1 certificate requests certified, commit? [y/n]y
  Write out database with 1 new entries
  Data Base Updated

Create the second intermediate certificate
""""""""""""""""""""""""""""""""""""""""""
Create a certificate request for the second intermediate certificate. For these
instructions, we will save the certificate request as
``cert_intermeidate_b.csr`` and the private key as ``key_intermediate_b.pem``.

.. code-block:: console

  $ openssl req \
      -nodes \
      -newkey rsa:2048 \
      -subj '/CN=Second Intermediate Certificate' \
      -keyout key_intermediate_b.pem \
      -out cert_intermediate_b.csr

  Generating a 2048 bit RSA private key
  ..........+++
  ............................................+++
  writing new private key to 'key_intermediate_b.pem'
  -----

Generate the second intermediate certificate by signing its certificate request
with the first intermediate certificate. For these instructions we will save
the certificate as ``cert_intermediate_b.pem``.

.. code-block:: console

  $ openssl ca \
      -config ca.conf \
      -extensions intermediate_cert_extensions \
      -cert cert_intermediate_a.pem \
      -keyfile key_intermediate_a.pem \
      -out cert_intermediate_b.pem \
      -infiles cert_intermediate_b.csr

  Using configuration from ca.conf
  Check that the request matches the signature
  Signature ok
  The Subject's Distinguished Name is as follows
  commonName            :ASN.1 12:'Second Intermediate Certificate'
  Certificate is to be certified until Nov 15 16:25:42 2020 GMT (1000 days)
  Sign the certificate? [y/n]:y


  1 out of 1 certificate requests certified, commit? [y/n]y
  Write out database with 1 new entries
  Data Base Updated

Create the client certificate
"""""""""""""""""""""""""""""
Create a certificate request for the client certificate. For these
instructions, we will save the certificate request as ``cert_client.csr`` and
the private key as ``key_client.pem``.

.. code-block:: console

  $ openssl req \
      -nodes \
      -newkey rsa:2048 \
      -subj '/CN=Client Certificate' \
      -keyout key_client.pem \
      -out cert_client.csr

  Generating a 2048 bit RSA private key
  .............................................................................................................................+++
  ..............................................................................................+++
  writing new private key to 'key_client.pem'
  -----

Generate the client certificate by signing its certificate request with the
second intermediate certificate. For these instructions we will save the
certificate as ``cert_client.pem``.

.. code-block:: console

  $ openssl ca \
      -config ca.conf \
      -extensions client_cert_extensions \
      -cert cert_intermediate_b.pem \
      -keyfile key_intermediate_b.pem \
      -out cert_client.pem \
      -infiles cert_client.csr

  Using configuration from ca.conf
  Check that the request matches the signature
  Signature ok
  The Subject's Distinguished Name is as follows
  commonName            :ASN.1 12:'Client Certificate'
  Certificate is to be certified until Nov 15 16:26:46 2020 GMT (1000 days)
  Sign the certificate? [y/n]:y


  1 out of 1 certificate requests certified, commit? [y/n]y
  Write out database with 1 new entries
  Data Base Updated

Upload the generated certificates to the key manager
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
In order interact with the key manager, the user needs to have a `creator` role.

To list all users with a `creator` role, run the following command as an admin:

.. code-block:: console

  $ openstack role assignment list --role creator --names

  +---------+-----------------------------+-------+-------------------+--------+-----------+
  | Role    | User                        | Group | Project           | Domain | Inherited |
  +---------+-----------------------------+-------+-------------------+--------+-----------+
  | creator | project_a_creator_2@Default |       | project_a@Default |        | False     |
  | creator | project_b_creator@Default   |       | project_b@Default |        | False     |
  | creator | project_a_creator@Default   |       | project_a@Default |        | False     |
  +---------+-----------------------------+-------+-------------------+--------+-----------+

To give the `demo` user a `creator` role in the `demo` project, run the
following command as an admin:

.. code-block:: console

  $ openstack role add --user demo --project demo creator

.. note:: This command provides no output. If the command fails, the user will
          see a "4xx Client error" indicating that "Secret creation attempt not
          allowed" and to "please review your user/project privileges".

.. note:: The following "openstack secret" commands require that the
          `python-barbicanclient <https://pypi.org/project/python-barbicanclient/>`_
          package is installed.

.. code-block:: console

  $ openstack secret store \
      --name CA \
      --algorithm RSA \
      --expiration 2018-06-29 \
      --secret-type certificate \
      --payload-content-type "application/octet-stream" \
      --payload-content-encoding base64 \
      --payload "$(base64 cert_ca.pem)"

  $ openstack secret store \
      --name IntermediateA \
      --algorithm RSA \
      --expiration 2018-06-29 \
      --secret-type certificate \
      --payload-content-type "application/octet-stream" \
      --payload-content-encoding base64 \
      --payload "$(base64 cert_intermediate_a.pem)"

  $ openstack secret store \
      --name IntermediateB \
      --algorithm RSA \
      --expiration 2018-06-29 \
      --secret-type certificate \
      --payload-content-type "application/octet-stream" \
      --payload-content-encoding base64 \
      --payload "$(base64 cert_intermediate_b.pem)"

  $ openstack secret store \
      --name Client \
      --algorithm RSA \
      --expiration 2018-06-29 \
      --secret-type certificate \
      --payload-content-type "application/octet-stream" \
      --payload-content-encoding base64 \
      --payload "$(base64 cert_client.pem)"

The responses should look something like this:

.. code-block:: console

  +---------------+------------------------------------------------------------------------------+
  | Field         | Value                                                                        |
  +---------------+------------------------------------------------------------------------------+
  | Secret href   | http://127.0.0.1/key-manager/v1/secrets/8fbcce5d-d646-4295-ba8a-269fc9451eeb |
  | Name          | CA                                                                           |
  | Created       | None                                                                         |
  | Status        | None                                                                         |
  | Content types | {u'default': u'application/octet-stream'}                                    |
  | Algorithm     | RSA                                                                          |
  | Bit length    | 256                                                                          |
  | Secret type   | certificate                                                                  |
  | Mode          | cbc                                                                          |
  | Expiration    | 2018-06-29T00:00:00+00:00                                                    |
  +---------------+------------------------------------------------------------------------------+

Save off the certificate UUIDs (found in the secret href):

.. code-block:: console

  $ cert_ca_uuid=8fbcce5d-d646-4295-ba8a-269fc9451eeb
  $ cert_intermediate_a_uuid=0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8
  $ cert_intermediate_b_uuid=674736e3-f25c-405c-8362-bbf991e0ce0a
  $ cert_client_uuid=125e6199-2de4-46e3-b091-8e2401ef0d63


Create a signed image
^^^^^^^^^^^^^^^^^^^^^
For these instructions, we will download a small CirrOS image:

.. code-block:: console

  $ wget -nc -O cirros.tar.gz http://download.cirros-cloud.net/0.3.5/cirros-0.3.5-source.tar.gz

  --2018-02-19 11:37:52--  http://download.cirros-cloud.net/0.3.5/cirros-0.3.5-source.tar.gz
  Resolving download.cirros-cloud.net (download.cirros-cloud.net)... 64.90.42.85
  Connecting to download.cirros-cloud.net (download.cirros-cloud.net)|64.90.42.85|:80... connected.
  HTTP request sent, awaiting response... 200 OK
  Length: 434333 (424K) [application/x-tar]
  Saving to: ‘cirros.tar.gz’

  cirros.tar.gz       100%[===================>] 424.15K  --.-KB/s    in 0.1s

  2018-02-19 11:37:54 (3.79 MB/s) - ‘cirros.tar.gz’ saved [434333/434333]

Sign the image with the generated client private key:

.. code-block:: console

  $ openssl dgst \
      -sha256 \
      -sign key_client.pem \
      -sigopt rsa_padding_mode:pss \
      -out cirros.self_signed.signature \
      cirros.tar.gz

.. note:: This command provides no output.

Save off the base64 encoded signature:

.. code-block:: console

  $ base64_signature=$(base64 -w 0 cirros.self_signed.signature)

Upload the signed image to Glance:

.. code-block:: console

  $ openstack image create \
      --public \
      --container-format bare \
      --disk-format qcow2 \
      --property img_signature="$base64_signature" \
      --property img_signature_certificate_uuid="$cert_client_uuid" \
      --property img_signature_hash_method='SHA-256' \
      --property img_signature_key_type='RSA-PSS' \
      --file cirros.tar.gz \
      cirros_client_signedImage

  +------------------+------------------------------------------------------------------------+
  | Field            | Value                                                                  |
  +------------------+------------------------------------------------------------------------+
  | checksum         | d41d8cd98f00b204e9800998ecf8427e                                       |
  | container_format | bare                                                                   |
  | created_at       | 2019-02-06T06:29:56Z                                                   |
  | disk_format      | qcow2                                                                  |
  | file             | /v2/images/17f48a6c-e592-446e-9c91-00fbc436d47e/file                   |
  | id               | 17f48a6c-e592-446e-9c91-00fbc436d47e                                   |
  | min_disk         | 0                                                                      |
  | min_ram          | 0                                                                      |
  | name             | cirros_client_signedImage                                              |
  | owner            | 45e13e63606f40d6b23275c3cd91aec2                                       |
  | properties       | img_signature='swA/hZi3WaNh35VMGlnfGnBWuXMlUbdO8h306uG7W3nwOyZP6dGRJ3  |
  |                  | Xoi/07Bo2dMUB9saFowqVhdlW5EywQAK6vgDsi9O5aItHM4u7zUPw+2e8eeaIoHlGhTks  |
  |                  | kmW9isLy0mYA9nAfs3coChOIPXW4V8VgVXEfb6VYGHWm0nShiAP1e0do9WwitsE/TVKoS  |
  |                  | QnWjhggIYij5hmUZ628KAygPnXklxVhqPpY/dFzL+tTzNRD0nWAtsc5wrl6/8HcNzZsaP  |
  |                  | oexAysXJtcFzDrf6UQu66D3UvFBVucRYL8S3W56It3Xqu0+InLGaXJJpNagVQBb476zB2  |
  |                  | ZzZ5RJ/4Zyxw==',                                                       |
  |                  | img_signature_certificate_uuid='125e6199-2de4-46e3-b091-8e2401ef0d63', |
  |                  | img_signature_hash_method='SHA-256',                                   |
  |                  | img_signature_key_type='RSA-PSS',                                      |
  |                  | os_hash_algo='sha512',                                                 |
  |                  | os_hash_value='cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a92 |
  |                  | 1d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927d |
  |                  | a3e',                                                                  |
  |                  | os_hidden='False'                                                      |
  | protected        | False                                                                  |
  | schema           | /v2/schemas/image                                                      |
  | size             | 0                                                                      |
  | status           | active                                                                 |
  | tags             |                                                                        |
  | updated_at       | 2019-02-06T06:29:56Z                                                   |
  | virtual_size     | None                                                                   |
  | visibility       | public                                                                 |
  +------------------+------------------------------------------------------------------------+

.. note:: Creating the image can fail if validation does not succeed. This will
          cause the image to be deleted and the Glance log to report that
          "Signature verification failed" for the given image ID.

Boot the signed image
^^^^^^^^^^^^^^^^^^^^^
Boot the signed image without specifying trusted certificate IDs:

.. code-block:: console

  $ nova boot myInstance \
      --flavor m1.tiny \
      --image cirros_client_signedImage

.. note:: The instance should fail to boot because certificate validation fails
          when the feature is enabled but no trusted image certificates are
          provided. The Nova log output should indicate that "Image signature
          certificate validation failed" because "Certificate chain building failed".

Boot the signed image with trusted certificate IDs:

.. code-block:: console

  $ nova boot myInstance \
      --flavor m1.tiny \
      --image cirros_client_signedImage \
      --trusted-image-certificate-id $cert_ca_uuid,$cert_intermediate_a_uuid \
      --trusted-image-certificate-id $cert_intermediate_b_uuid

.. note:: The instance should successfully boot and certificate validation
          should succeed. The Nova log output should indicate that "Image
          signature certificate validation succeeded".

Other Links
-----------
* https://etherpad.openstack.org/p/mitaka-glance-image-signing-instructions
* https://etherpad.openstack.org/p/queens-nova-certificate-validation
* https://wiki.openstack.org/wiki/OpsGuide/User-Facing_Operations
* http://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/nova-validate-certificates.html

