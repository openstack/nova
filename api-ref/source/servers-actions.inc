.. -*- rst -*-
.. needs:body_verification

===========================================
 Servers - run an action (servers, action)
===========================================

Enables all users to perform an action on a server. Specify the action
in the request body.

You can associate a fixed or floating IP address with a server,
or disassociate a fixed or floating IP address from a server.
You can attach a volume to a server.

You can create an image from a server, create a backup of a server,
evacuate a server from a failed host to a new host, and force-delete a
server before deferred cleanup.
You can lock, pause, reboot, rebuild, rescue, resize, resume, confirm
the resize of, revert a pending resize for, shelve, shelf-offload,
unshelve, start, stop, unlock, unpause, and unrescue a server. You can
also change the password of the server and add a security group to or
remove a security group from a server. You can also trigger a crash dump
into a server since Mitaka release.

You can get an RDP, serial, SPICE, or VNC console for a server.

Add (Associate) Floating Ip (addFloatingIp Action) (DEPRECATED)
================================================================

.. warning:: This API is deprecated and will fail with a 404 starting
             from microversion 2.44. This is replaced with using the
             Neutron networking service API.

.. rest_method:: POST /servers/{server_id}/action

Adds a floating IP address to a server, which associates
that address with the server.

A pool of floating IP addresses, configured by the cloud administrator,
is available in OpenStack Compute. The project quota defines the maximum
number of floating IP addresses that you can allocate to the project.
After you `create (allocate) a floating IPaddress
<http://developer.openstack.org/api-ref/compute/#create-allocate-floating-ip-address>`__
for a project, you can associate that address with the server. Specify
the ``addFloatingIp`` action in the request body.

If an instance is connected to multiple networks, you can associate a
floating IP address with a specific fixed IP address by using the
optional ``fixed_address`` parameter.

**Preconditions**

The server must exist.

You can only add a floating IP address to the server when its status is ``ACTIVE`` or ``STOPPED``

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - addFloatingIp: addFloatingIp
  - address: address
  - fixed_address: fixed_address

**Example Add (Associate) Floating Ip (addFloatingIp Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-addfloatingip-req.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Add Security Group To A Server (addSecurityGroup Action)
========================================================

.. rest_method:: POST /servers/{server_id}/action

Adds a security group to a server.

Specify the ``addSecurityGroup`` action in the request body.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - addSecurityGroup: addSecurityGroup
  - name: name

**Example Add Security Group To A Server (addSecurityGroup Action)**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-group-add-post-req.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Change Administrative Password (changePassword Action)
======================================================

.. rest_method:: POST /servers/{server_id}/action

Changes the administrative password for a server.

Specify the ``changePassword`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers can
change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - changePassword: changePassword
  - adminPass: adminPass_change_password

**Example Change Administrative Password (changePassword Action)**

.. literalinclude:: ../../doc/api_samples/os-admin-password/admin-password-change-password.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Confirm Resized Server (confirmResize Action)
=============================================

.. rest_method:: POST /servers/{server_id}/action

Confirms a pending resize action for a server.

Specify the ``confirmResize`` action in the request body.

After you make this request, you typically must keep polling the server
status to determine whether the request succeeded. A successfully
confirming resize operation shows a status of ``ACTIVE`` or ``SHUTOFF``
and a migration_status of ``confirmed``. You can also see the resized
server in the compute node that OpenStack Compute manages.

**Preconditions**

You can only confirm the resized server where the status is
``VERIFY_RESIZE``.

If the server is locked, you must have administrator privileges
to confirm the server.

**Troubleshooting**

If the server status remains ``RESIZED``, the request failed. Ensure you
meet the preconditions and run the request again. If the request fails
again, investigate the compute back end or ask your cloud provider.

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - confirmResize: confirmResize

**Example Confirm Resized Server (confirmResize Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-confirm-resize.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Create Server Back Up (createBackup Action)
===========================================

.. rest_method:: POST /servers/{server_id}/action

Creates a back up of a server.

.. note:: This API is not supported for volume-backed instances.

Specify the ``createBackup`` action in the request body.

Policy defaults enable only users with the administrative role or the
owner of the server to perform this operation. Cloud providers can
change these permissions through the ``policy.json`` file.

.. note::
    Starting from version 2.39 the image quota enforcement with Nova `metadata`
    is removed and quota checks should be performed using Glance API directly.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - createBackup: createBackup
  - name: backup_name
  - backup_type: backup_type
  - rotation: backup_rotation
  - metadata: metadata

**Example Create Server Back Up (createBackup Action)**

.. literalinclude:: ../../doc/api_samples/os-create-backup/create-backup-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: image_location
  - image_id: snapshot_id_resp_2_45

**Example Create Server Back Up (v2.45)**

.. literalinclude:: ../../doc/api_samples/os-create-backup/v2.45/create-backup-resp.json
   :language: javascript


Create Image (createImage Action)
=================================

.. rest_method:: POST /servers/{server_id}/action

Creates an image from a server.

Specify the ``createImage`` action in the request body.

After you make this request, you typically must keep polling the status of
the created image to determine whether the request succeeded.

If the operation succeeds, the created image has a status of ``active`` and
the server status returns to the original status. You can also see the new
image in the image back end that OpenStack Image service manages.

.. note::
    Starting from version 2.39 the image quota enforcement with Nova `metadata`
    is removed and quota checks should be performed using Glance API directly.

**Preconditions**

The server must exist.

You can only create a new image from the server when its status is ``ACTIVE``,
``SHUTOFF``, ``PAUSED``, or ``SUSPENDED``.

The connection to the Image service is valid.

**Troubleshooting**

If the image status remains uploading or shows another error status,
the request failed. Ensure you meet the preconditions and run the request
again. If the request fails again, investigate the image back end.

If the server status does not go back to an original server's status,
the request failed. Ensure you meet the preconditions, or check if
there is another operation that causes race conditions for the server,
then run the request again. If the request fails again, investigate the
compute back end or ask your cloud provider.

If the request fails due to an error on OpenStack Compute service, the image
is purged from the image store that OpenStack Image service manages. Ensure
you meet the preconditions and run the request again. If the request fails
again, investigate OpenStack Compute service or ask your cloud provider.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - createImage: createImage
  - name: image_name
  - metadata: image_metadata

**Example Create Image (createImage Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-create-image.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: image_location
  - image_id: snapshot_id_resp_2_45

**Example Create Image (v2.45)**

.. literalinclude:: ../../doc/api_samples/servers/v2.45/server-action-create-image-resp.json
   :language: javascript


Lock Server (lock Action)
=========================

.. rest_method:: POST /servers/{server_id}/action

Locks a server.

Specify the ``lock`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - lock: lock

**Example Lock Server (lock Action)**

.. literalinclude:: ../../doc/api_samples/os-lock-server/lock-server.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Pause Server (pause Action)
===========================

.. rest_method:: POST /servers/{server_id}/action

Pauses a server. Changes its status to ``PAUSED``.

Specify the ``pause`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - pause: pause

**Example Pause Server (pause Action)**

.. literalinclude:: ../../doc/api_samples/os-pause-server/pause-server.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Reboot Server (reboot Action)
=============================

.. rest_method:: POST /servers/{server_id}/action

Reboots a server.

Specify the ``reboot`` action in the request body.

**Preconditions**

The preconditions for rebooting a server depend on the type of reboot.

You can only *SOFT* reboot a server when its status is ``ACTIVE``.

You can only *HARD* reboot a server when its status is one of:

* ``ACTIVE``
* ``ERROR``
* ``HARD_REBOOT``
* ``PAUSED``
* ``REBOOT``
* ``SHUTOFF``
* ``SUSPENDED``

If the server is locked, you must have administrator privileges
to reboot the server.

**Asynchronous Postconditions**

After you successfully reboot a server, its status changes to ``ACTIVE``.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - reboot: reboot
  - type: reboot_type

**Example Reboot Server (reboot Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-reboot.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Rebuild Server (rebuild Action)
===============================

.. rest_method:: POST /servers/{server_id}/action

Rebuilds a server.

Specify the ``rebuild`` action in the request body.

This operation recreates the root disk of the server.
For a volume-backed server, this operation keeps the contents of the volume.

**Preconditions**

The server status must be ``ACTIVE``, ``SHUTOFF`` or ``ERROR``.

**Asynchronous Postconditions**

If the server was in status ``SHUTOFF`` before the rebuild, it will be stopped
and in status ``SHUTOFF`` after the rebuild, otherwise it will be ``ACTIVE``
if the rebuild was successful or ``ERROR`` if the rebuild failed.

.. note:: There is a `known limitation`_ where the root disk is not
   replaced for volume-backed instances during a rebuild.

.. _known limitation: https://bugs.launchpad.net/nova/+bug/1482040

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - rebuild: rebuild
  - imageRef: imageRef_rebuild
  - accessIPv4: accessIPv4_in
  - accessIPv6: accessIPv6_in
  - adminPass: adminPass_request
  - metadata: metadata
  - name: server_name_optional
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - personality: personality
  - personality.path: path
  - personality.contents: contents
  - preserve_ephemeral: preserve_ephemeral
  - description: server_description
  - key_name: key_name_rebuild_req
  - user_data: user_data_rebuild_req
  - trusted_image_certificates: server_trusted_image_certificates_rebuild_req

**Example Rebuild Server (rebuild Action) (v2.63)**

.. literalinclude:: ../../doc/api_samples/servers/v2.63/server-action-rebuild.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - Location: server_location
  - server: server
  - accessIPv4: accessIPv4
  - accessIPv6: accessIPv6
  - addresses: addresses_obj
  - created: created
  - flavor: flavor_server
  - flavor.id: flavor_id_body_2_46
  - flavor.links: flavor_links_2_46
  - flavor.vcpus: flavor_cpus_2_47
  - flavor.ram: flavor_ram_2_47
  - flavor.disk: flavor_disk_2_47
  - flavor.ephemeral: flavor_ephem_disk_2_47
  - flavor.swap: flavor_swap_2_47
  - flavor.original_name: flavor_original_name
  - flavor.extra_specs: extra_specs_2_47
  - flavor.extra_specs.key: flavor_extra_spec_key_2_47
  - flavor.extra_specs.value: flavor_extra_spec_value_2_47
  - hostId: hostId
  - id: server_id
  - image: image
  - image.id: image_id_body
  - image.links: links
  - links: server_links
  - metadata: metadata_object
  - name: server_name
  - OS-DCF:diskConfig: disk_config
  - status: server_status
  - tenant_id: tenant_id_body
  - updated: updated
  - user_id: user_id
  - adminPass: adminPass_response
  - progress: progress
  - locked: locked
  - description: server_description_resp
  - tags: tags
  - key_name: key_name_rebuild_resp
  - user_data: user_data_rebuild_resp
  - trusted_image_certificates: server_trusted_image_certificates_resp

**Example Rebuild Server (rebuild Action) (v2.63)**

.. literalinclude:: ../../doc/api_samples/servers/v2.63/server-action-rebuild-resp.json
   :language: javascript

Remove (Disassociate) Floating Ip (removeFloatingIp Action) (DEPRECATED)
=========================================================================

.. warning:: This API is deprecated and will fail with a 404 starting
             from microversion 2.44. This is replaced with using the
             Neutron networking service API.

.. rest_method:: POST /servers/{server_id}/action

Removes, or disassociates, a floating IP address from a server.

The IP address is returned to the pool of IP addresses that is available
for all projects. When you remove a floating IP address and that IP address
is still associated with a running instance, it is automatically
disassociated from that instance.

Specify the ``removeFloatingIp`` action in the request body.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - removeFloatingIp: removeFloatingIp
  - address: address

**Example Remove (Disassociate) Floating Ip (removeFloatingIp Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-removefloatingip-req.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Remove Security Group From A Server (removeSecurityGroup Action)
================================================================

.. rest_method:: POST /servers/{server_id}/action

Removes a security group from a server.

Specify the ``removeSecurityGroup`` action in the request body.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - removeSecurityGroup: removeSecurityGroup
  - name: name

**Example Remove Security Group From A Server (removeSecurityGroup Action)**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-group-remove-post-req.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Rescue Server (rescue Action)
=============================

.. rest_method:: POST /servers/{server_id}/action

Puts a server in rescue mode and changes its status to ``RESCUE``.

.. note:: This API is not supported for volume-backed instances.

Specify the ``rescue`` action in the request body.

If you specify the ``rescue_image_ref`` extended attribute,
the image is used to rescue the instance. If you omit an image
reference, the base image reference is used by default.

**Asynchronous Postconditions**

After you successfully rescue a server and make a ``GET
/servers/​{server_id}​`` request, its status changes to ``RESCUE``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - rescue: rescue
  - adminPass: adminPass_rescue_request
  - rescue_image_ref: rescue_image_ref

**Example Rescue server (rescue Action)**

.. literalinclude:: ../../doc/api_samples/os-rescue/server-rescue-req-with-image-ref.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - adminPass: adminPass_response

**Example Rescue server (rescue Action)**

.. literalinclude:: ../../doc/api_samples/os-rescue/server-rescue.json
   :language: javascript

Resize Server (resize Action)
=============================

.. rest_method:: POST /servers/{server_id}/action

Resizes a server.

Specify the ``resize`` action in the request body.

A successfully resized server shows a ``VERIFY_RESIZE`` status,
``RESIZED`` VM status, and ``finished`` migration status. If you set the
``resize_confirm_window`` option of the Compute service to an integer value,
the Compute service automatically confirms the resize operation after
the set interval in seconds.

**Preconditions**

You can only resize a server when its status is ``ACTIVE`` or ``SHUTOFF``.

If the server is locked, you must have administrator privileges
to resize the server.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - resize: resize
  - flavorRef: flavorRef_resize
  - OS-DCF:diskConfig: OS-DCF:diskConfig

**Example Resize Server (Resize Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-resize.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Resume Suspended Server (resume Action)
=======================================

.. rest_method:: POST /servers/{server_id}/action

Resumes a suspended server and changes its status to ``ACTIVE``.

Specify the ``resume`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - resume: resume

**Example Resume Suspended Server (Resume Action)**

.. literalinclude:: ../../doc/api_samples/os-suspend-server/server-resume.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Revert Resized Server (revertResize Action)
===========================================

.. rest_method:: POST /servers/{server_id}/action

Cancels and reverts a pending resize action for a server.

Specify the ``revertResize`` action in the request body.

**Preconditions**

You can only revert the resized server where the status is
``VERIFY_RESIZE`` and the OS-EXT-STS:vm_state is ``resized``.

If the server is locked, you must have administrator privileges to revert
the resizing.

**Asynchronous Postconditions**

After you make this request, you typically must keep polling the server status
to determine whether the request succeeded. A reverting resize operation shows
a status of ``REVERT_RESIZE`` and a task_state of ``resize_reverting``. If
successful, the status will return to ``ACTIVE`` or ``SHUTOFF``. You can also
see the reverted server in the compute node that OpenStack Compute manages.

**Troubleshooting**

If the server status remains ``VERIFY_RESIZE``, the request failed. Ensure you
meet the preconditions and run the request again. If the request fails again,
investigate the compute back end.

The server is not reverted in the compute node that OpenStack Compute manages.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - revertResize: revertResize

**Example Revert Resized Server (revertResize Action)**

.. literalinclude:: ../../doc/api_samples/servers/server-action-revert-resize.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Start Server (os-start Action)
==============================

.. rest_method:: POST /servers/{server_id}/action

Starts a stopped server and changes its status to ``ACTIVE``.

Specify the ``os-start`` action in the request body.

**Preconditions**

The server status must be ``SHUTOFF``.

If the server is locked, you must have administrator privileges
to start the server.

**Asynchronous Postconditions**

After you successfully start a server, its status changes to ``ACTIVE``.

**Troubleshooting**

If the server status does not change to ``ACTIVE``, the start operation failed.
Ensure that you meet the preconditions and run the request again.
If the request fails again, investigate whether another operation is running
that causes a race condition.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - os-start: os-start

**Example Start server**

.. literalinclude:: ../../doc/api_samples/servers/server-action-start.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Stop Server (os-stop Action)
============================

.. rest_method:: POST /servers/{server_id}/action

Stops a running server and changes its status to ``SHUTOFF``.

Specify the ``os-stop`` action in the request body.

**Preconditions**

The server status must be ``ACTIVE`` or ``ERROR``.

If the server is locked, you must have administrator privileges
to stop the server.

**Asynchronous Postconditions**

After you successfully stop a server, its status changes to ``SHUTOFF``.
This API operation does not delete the server instance data and the data
will be available again after ``os-start`` action.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - os-stop: os-stop

**Example Stop server**

.. literalinclude:: ../../doc/api_samples/servers/server-action-stop.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Suspend Server (suspend Action)
===============================

.. rest_method:: POST /servers/{server_id}/action

Suspends a server and changes its status to ``SUSPENDED``.

Specify the ``suspend`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - suspend: suspend

**Example Suspend Server (suspend Action)**

.. literalinclude:: ../../doc/api_samples/os-suspend-server/server-suspend.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Unlock Server (unlock Action)
=============================

.. rest_method:: POST /servers/{server_id}/action

Unlocks a locked server.

Specify the ``unlock`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - unlock: unlock

**Example Unlock Server (unlock Action)**

.. literalinclude:: ../../doc/api_samples/os-lock-server/unlock-server.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Unpause Server (unpause Action)
===============================

.. rest_method:: POST /servers/{server_id}/action

Unpauses a paused server and changes its status to ``ACTIVE``.

Specify the ``unpause`` action in the request body.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id_path
  - unpause: unpause

**Example Unpause Server (unpause Action)**

.. literalinclude:: ../../doc/api_samples/os-pause-server/unpause-server.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.


Unrescue Server (unrescue Action)
=================================

.. rest_method:: POST /servers/{server_id}/action

Unrescues a server. Changes status to ``ACTIVE``.

Specify the ``unrescue`` action in the request body.

**Preconditions**

The server must exist.

You can only unrescue a server when its status is ``RESCUE``.

**Asynchronous Postconditions**

After you successfully unrescue a server and make a
``GET /servers/​{server_id}​``
request, its status changes to ``ACTIVE``.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - unrescue: unrescue

**Example Unrescue server**

.. literalinclude:: ../../doc/api_samples/os-rescue/server-unrescue-req.json
   :language: javascript

Response
--------

If successful, this method does not return content in the response body.
