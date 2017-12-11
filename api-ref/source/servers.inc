.. -*- rst -*-
.. TODO(sdague) parameter microversions need to be gone through in the
   response (request side should be good)
.. needs:example_verification
.. needs:body_verification

===================
 Servers (servers)
===================

Lists, creates, shows details for, updates, and deletes servers.

**Passwords**

When you create a server, you can specify a password through the
optional adminPass attribute. The password must meet the complexity
requirements set by your OpenStack Compute provider. The server might
enter an ``ERROR`` state if the complexity requirements are not met. In
this case, a client might issue a change password action to reset the
server password.

If you do not specify a password, the API generates and assigns a random
password that it returns in the response object. This password meets the
security requirements set by the compute provider. For security reasons,
subsequent GET calls do not require this password.

**Server metadata**

You can specify custom server metadata at server launch time. The
maximum size for each metadata key-value pair is 255 bytes. The compute
provider determines the maximum number of key-value pairs for each
server. You can query this value through the ``maxServerMeta`` absolute
limit.

**Server networks**

You can specify one or more networks to which the server connects at
launch time. Users can also specify a specific port on the network or
the fixed IP address to assign to the server interface.

.. note:: You can use both IPv4 and IPv6 addresses as access addresses,
          and you can assign both addresses simultaneously. You can update
          access addresses after you create a server.

**Server personality**

.. note:: The use of personality files is deprecated starting with the 2.57
  microversion. Use ``metadata`` and ``user_data`` to customize a server
  instance.

To customize the personality of a server instance, you can inject data
into its file system. For example, you might insert ssh keys, set
configuration files, or store data that you want to retrieve from inside
the instance. This customization method provides minimal launch-time
personalization. If you require significant customization, create a
custom image.

Follow these guidelines when you inject files:

-  The maximum size of the file path data is 255 bytes.

-  Encode the file contents as a Base64 string. The compute provider
   determines the maximum size of the file contents. The image that you
   use to create the server determines this value.

   .. note::

      The maximum limit refers to the number of bytes in the decoded
      data and not to the number of characters in the encoded data.

-  The ``maxPersonality`` absolute limit defines the maximum number of
   file path and content pairs that you can supply. The compute provider
   determines this value.

-  The ``maxPersonalitySize`` absolute limit is a byte limit that
   applies to all images in the deployment. Providers can set additional
   per-image personality limits.

The file injection might not occur until after the server builds and
boots.

After file injection, only system administrators can access personality
files. For example, on Linux, all files have root as the owner and the
root group as the group owner, and allow only user and group read access
(``chmod 440``).

**Server access addresses**

In a hybrid environment, the underlying implementation might not control
the IP address of a server. Instead, the access IP address might be part
of the dedicated hardware; for example, a router/NAT device. In this
case, you cannot use the addresses that the implementation provides to
access the server from outside the local LAN. Instead, the API might
assign a separate access address at creation time to provide access to
the server. This address might not be directly bound to a network
interface on the server and might not necessarily appear when you query
the server addresses. However, clients should use an access address to
access the server directly.

List Servers
============

.. rest_method:: GET /servers

Lists IDs, names, and links for all servers.


Servers contain a status attribute that indicates the current server
state. You can filter on the server status when you complete a list
servers request. The server status is returned in the response
body. The possible server status values are:

- ``ACTIVE``. The server is active.
- ``BUILD``. The server has not finished the original build process.
- ``DELETED``. The server is permanently deleted.
- ``ERROR``. The server is in error.
- ``HARD_REBOOT``. The server is hard rebooting. This is equivalent to
  pulling the power plug on a physical server, plugging it back in,
  and rebooting it.
- ``MIGRATING``. The server is being migrated to a new host.
- ``PASSWORD``. The password is being reset on the server.
- ``PAUSED``. In a paused state, the state of the server is stored in
  RAM. A paused server continues to run in frozen state.
- ``REBOOT``. The server is in a soft reboot state. A reboot command
  was passed to the operating system.
- ``REBUILD``. The server is currently being rebuilt from an image.
- ``RESCUE``. The server is in rescue mode. A rescue image is running
  with the original server image attached.
- ``RESIZE``. Server is performing the differential copy of data that
  changed during its initial copy. Server is down for this stage.
- ``REVERT_RESIZE``. The resize or migration of a server failed for
  some reason. The destination server is being cleaned up and the
  original source server is restarting.
- ``SHELVED``: The server is in shelved state. Depending on the shelve offload
  time, the server will be automatically shelved offloaded.
- ``SHELVED_OFFLOADED``: The shelved server is offloaded (removed from the
  compute host) and it needs unshelved action to be used again.
- ``SHUTOFF``. The server is powered off and the disk image still
  persists.
- ``SOFT_DELETED``. The server is marked as deleted but the disk
  images are still available to restore.
- ``SUSPENDED``. The server is suspended, either by request or
  necessity. This status appears for only the XenServer/XCP, KVM, and
  ESXi hypervisors. Administrative users can suspend an instance if it
  is infrequently used or to perform system maintenance. When you
  suspend an instance, its VM state is stored on disk, all memory is
  written to disk, and the virtual machine is stopped. Suspending an
  instance is similar to placing a device in hibernation; memory and
  vCPUs become available to create other instances.
- ``UNKNOWN``. The state of the server is unknown. Contact your cloud
  provider.
- ``VERIFY_RESIZE``. System is awaiting confirmation that the server
  is operational after a move or resize.


There is whitelist for valid filter keys. Any filter key other than from
whitelist will be silently ignored.

- For non-admin users, whitelist is different from admin users whitelist.
  Valid whitelist for non-admin users includes

  - ``all_tenants``
  - ``changes-since``
  - ``flavor``
  - ``image``
  - ``ip``
  - ``ip6`` (New in version 2.5)
  - ``name``
  - ``not-tags`` (New in version 2.26)
  - ``not-tags-any`` (New in version 2.26)
  - ``reservation_id``
  - ``status``
  - ``tags`` (New in version 2.26)
  - ``tags-any`` (New in version 2.26)


- For admin user, whitelist includes all filter keys mentioned in
  :ref:`list-server-request` Section.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401),
forbidden(403)

.. _list-server-request:

Request
-------

.. rest_parameters:: parameters.yaml

  - access_ip_v4: access_ip_v4_query_server
  - access_ip_v6: access_ip_v6_query_server
  - all_tenants: all_tenants_query
  - auto_disk_config: disk_config_query_server
  - availability_zone: availability_zone_query_server
  - config_drive: config_drive_query_server
  - changes-since: changes_since_server
  - created_at: created_at_query_server
  - deleted: deleted_query
  - description: description_query_server
  - flavor: flavor_query
  - host: host_query_server
  - hostname: hostname_query_server
  - image: image_query
  - ip: ip_query
  - ip6: ip6_query
  - kernel_id: kernel_id_query_server
  - key_name: key_name_query_server
  - launch_index: launch_index_query_server
  - launched_at: launched_at_query_server
  - limit: limit
  - locked_by: locked_by_query_server
  - marker: marker
  - name: server_name_query
  - node: node_query_server
  - not-tags: not_tags_query
  - not-tags-any: not_tags_any_query
  - power_state: power_state_query_server
  - progress: progress_query_server
  - project_id: project_id_query_server
  - ramdisk_id: ramdisk_id_query_server
  - reservation_id: reservation_id_query
  - root_device_name: server_root_device_name_query
  - sort_dir: sort_dir_server
  - sort_key: sort_key_server
  - status: server_status_query
  - tags: tags_query
  - tags-any: tags_any_query
  - task_state: task_state_query_server
  - terminated_at: terminated_at_query_server
  - user_id: user_id_query_server
  - uuid: server_uuid_query
  - vm_state: vm_state_query_server

Response
--------

.. rest_parameters:: parameters.yaml

  - servers: servers
  - id: server_id
  - links: links
  - name: server_name

**Example List Servers**

.. literalinclude:: ../../doc/api_samples/servers/servers-list-resp.json
   :language: javascript


Create Server
=============

.. rest_method:: POST /servers

Creates a server.

The progress of this operation depends on the location of the
requested image, network I/O, host load, selected flavor, and other
factors.

To check the progress of the request, make a ``GET /servers/{id}``
request. This call returns a progress attribute, which is a percentage
value from 0 to 100.

The ``Location`` header returns the full URL to the newly created
server and is available as a ``self`` and ``bookmark`` link in the
server representation.

When you create a server, the response shows only the server ID, its
links, and the admin password. You can get additional attributes
through subsequent ``GET`` requests on the server.

Include the ``block-device-mapping-v2`` parameter in the create
request body to boot a server from a volume.

Include the ``key_name`` parameter in the create request body to add a
keypair to the server when you create it. To create a keypair, make a
`create keypair
<http://developer.openstack.org/api-ref/compute/#create-or-import-keypair>`__
request.

.. note:: Starting with microversion 2.37 the ``networks`` field is required.

**Preconditions**

- The user must have sufficient server quota to create the number of
  servers requested.
- The connection to the Image service is valid.

**Asynchronous postconditions**

- With correct permissions, you can see the server status as
  ``ACTIVE`` through API calls.
- With correct access, you can see the created server in the compute
  node that OpenStack Compute manages.

**Troubleshooting**

- If the server status remains ``BUILDING`` or shows another error
  status, the request failed. Ensure you meet the preconditions then
  investigate the compute node.

- The server is not created in the compute node that OpenStack Compute
  manages.

- The compute node needs enough free resource to match the resource of
  the server creation request.

- Ensure that the scheduler selection filter can fulfill the request
  with the available compute nodes that match the selection criteria
  of the filter.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401),
forbidden(403), itemNotFound(404), conflict(409)

..
  TODO(sdague): leave these notes for later when fixing the body
  language. They are commented out so they won't render, but are
  useful to not have to look this up again later.

  A conflict(409) is returned in the event of trying to allocated already
  allocated resources (such as networks) to the server in question.

  entityTooLarge(413) is returned if the ``user_data`` exceeds what is
  allowed by the backend.

  All other failure conditions map to 400, and will need to be
  disambiguated by the error string returned.

Request
-------

.. rest_parameters:: parameters.yaml


  - server: server
  - name: server_name
  - flavorRef: flavorRef
  - imageRef: imageRef
  - security_groups: security_groups
  - metadata: metadata
  - accessIPv4: accessIPv4_in
  - accessIPv6: accessIPv6_in
  - adminPass: adminPass_request
  - user_data: user_data
  - availability_zone: os-availability-zone:availability_zone
  - networks: networks
  - networks.uuid: network_uuid
  - networks.port: port
  - networks.fixed_ip: fixed_ip
  - networks.tag: device_tag_nic
  - personality: personality
  - block_device_mapping_v2: block_device_mapping_v2
  - block_device_mapping_v2.device_name: device_name
  - block_device_mapping_v2.source_type: source_type
  - block_device_mapping_v2.destination_type: destination_type
  - block_device_mapping_v2.delete_on_termination: delete_on_termination
  - block_device_mapping_v2.guest_format: guest_format
  - block_device_mapping_v2.boot_index: boot_index
  - block_device_mapping_v2.uuid: block_device_uuid
  - block_device_mapping_v2.tag: device_tag_bdm
  - block_device_mapping_v2.disk_bus: disk_bus
  - config_drive: config_drive
  - key_name: key_name
  - os:scheduler_hints: os:scheduler_hints
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - description: server_description
  - tags: server_tags_create

**Example Create Server**

.. literalinclude:: ../../doc/api_samples/servers/server-create-req.json
   :language: javascript

**Example Create Server With Automatic Networking (v2.37)**

.. literalinclude:: ../../doc/api_samples/servers/v2.37/server-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - server: server
  - id: server_id
  - links: links
  - OS-DCF:diskConfig: disk_config
  - security_groups: security_groups_obj
  - security_groups.name: name
  - adminPass: adminPass_response

**Example Create Server**

.. literalinclude:: ../../doc/api_samples/servers/server-create-resp.json
   :language: javascript

Create Multiple Servers
=======================

.. rest_method:: POST /servers

There is a second kind of create call which can build multiple servers
at once. This supports all the same parameters as create with a few
additional attributes specific to multiple create.

Error handling for multiple create is not as consistent as for single
server create, and there is no guarantee that all the servers will be
built. This call should generally be avoided in favor of clients doing
direct individual server creates.

Request (Additional Parameters)
-------------------------------

These are the parameters beyond single create that are supported.

.. rest_parameters:: parameters.yaml

   - name: servers_multiple_create_name
   - min_count: servers_min_count
   - max_count: servers_max_count
   - return_reservation_id: return_reservation_id

**Example Multiple Create with reservation ID**

.. literalinclude:: ../../doc/api_samples/os-multiple-create/multiple-create-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

   - reservation_id: reservation_id

If ``return_reservation_id`` is set to ``true`` only the
``reservation_id`` will be returned. This can be used as a filter with
list servers detailed to see the status of all the servers being
built.

**Example Create multiple servers with reservation ID**

.. literalinclude:: ../../doc/api_samples/os-multiple-create/multiple-create-post-resp.json
   :language: javascript

If ``return_reservation_id`` is set to ``false`` a representation of
the ``first`` server will be returned.

**Example Create multiple servers without reservation ID**

.. literalinclude:: ../../doc/api_samples/os-multiple-create/multiple-create-no-resv-post-resp.json
   :language: javascript


List Servers Detailed
=====================

.. rest_method:: GET /servers/detail

For each server, shows server details including configuration drive,
extended status, and server usage information.

The extended status information appears in the OS-EXT-STS:vm_state,
OS-EXT-STS:power_state, and OS-EXT-STS:task_state attributes.

The server usage information appears in the OS-SRV-USG:launched_at and
OS-SRV-USG:terminated_at attributes.

To hide addresses information for instances in a certain state, set
the osapi_hide_server_address_states configuration option. Set this
option to a valid VM state in the nova.conf configuration file.

HostId is unique per account and is not globally unique.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401),
forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - access_ip_v4: access_ip_v4_query_server
  - access_ip_v6: access_ip_v6_query_server
  - all_tenants: all_tenants_query
  - auto_disk_config: disk_config_query_server
  - availability_zone: availability_zone_query_server
  - config_drive: config_drive_query_server
  - changes-since: changes_since_server
  - created_at: created_at_query_server
  - deleted: deleted_query
  - description: description_query_server
  - flavor: flavor_query
  - host: host_query_server
  - hostname: hostname_query_server
  - image: image_query
  - ip: ip_query
  - ip6: ip6_query
  - kernel_id: kernel_id_query_server
  - key_name: key_name_query_server
  - launch_index: launch_index_query_server
  - launched_at: launched_at_query_server
  - limit: limit
  - locked_by: locked_by_query_server
  - marker: marker
  - name: server_name_query
  - node: node_query_server
  - not-tags: not_tags_query
  - not-tags-any: not_tags_any_query
  - power_state: power_state_query_server
  - progress: progress_query_server
  - project_id: project_id_query_server
  - ramdisk_id: ramdisk_id_query_server
  - reservation_id: reservation_id_query
  - root_device_name: server_root_device_name_query
  - sort_dir: sort_dir_server
  - sort_key: sort_key_server
  - status: server_status_query
  - tags: tags_query
  - tags-any: tags_any_query
  - task_state: task_state_query_server
  - terminated_at: terminated_at_query_server
  - user_id: user_id_query_server
  - uuid: server_uuid_query
  - vm_state: vm_state_query_server

Response
--------

.. rest_parameters:: parameters.yaml

  - server: server
  - addresses: addresses
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
  - key_name: key_name_resp
  - links: links
  - metadata: metadata_compat
  - name: server_name
  - accessIPv4: accessIPv4
  - accessIPv6: accessIPv6
  - config_drive: config_drive_resp
  - OS-DCF:diskConfig: disk_config
  - OS-EXT-AZ:availability_zone: OS-EXT-AZ:availability_zone
  - OS-EXT-SRV-ATTR:host: OS-EXT-SRV-ATTR:host
  - OS-EXT-SRV-ATTR:hypervisor_hostname: OS-EXT-SRV-ATTR:hypervisor_hostname
  - OS-EXT-SRV-ATTR:instance_name: OS-EXT-SRV-ATTR:instance_name
  - OS-EXT-STS:power_state: OS-EXT-STS:power_state
  - OS-EXT-STS:task_state: OS-EXT-STS:task_state
  - OS-EXT-STS:vm_state: OS-EXT-STS:vm_state
  - os-extended-volumes:volumes_attached: os-extended-volumes:volumes_attached
  - os-extended-volumes:volumes_attached.id: os-extended-volumes:volumes_attached.id
  - os-extended-volumes:volumes_attached.delete_on_termination: os-extended-volumes:volumes_attached.delete_on_termination
  - OS-SRV-USG:launched_at: OS-SRV-USG:launched_at
  - OS-SRV-USG:terminated_at: OS-SRV-USG:terminated_at
  - progress: progress
  - security_groups: security_groups_obj
  - security_group.name: name
  - status: server_status
  - host_status: host_status
  - tenant_id: tenant_id_body
  - updated: updated
  - user_id: user_id
  - OS-EXT-SRV-ATTR:hostname: server_hostname
  - OS-EXT-SRV-ATTR:reservation_id: server_reservation_id
  - OS-EXT-SRV-ATTR:launch_index: server_launch_index
  - OS-EXT-SRV-ATTR:kernel_id: server_kernel_id
  - OS-EXT-SRV-ATTR:ramdisk_id: server_ramdisk_id
  - OS-EXT-SRV-ATTR:root_device_name: server_root_device_name
  - OS-EXT-SRV-ATTR:user_data: server_user_data
  - locked: locked

**Example List Servers Detailed (2.47)**

.. literalinclude:: /../../doc/api_samples/servers/v2.47/servers-details-resp.json
   :language: javascript


Show Server Details
===================

.. rest_method:: GET /servers/{server_id}

Shows details for a server.

Includes server details including configuration drive, extended status, and server usage information.

The extended status information appears in the ``OS-EXT-STS:vm_state``, ``OS-EXT-STS:power_state``, and ``OS-EXT-STS:task_state`` attributes.

The server usage information appears in the ``OS-SRV-USG:launched_at`` and ``OS-SRV-USG:terminated_at`` attributes.

To hide ``addresses`` information for instances in a certain state, set the ``osapi_hide_server_address_states`` configuration option. Set this option to a valid VM state in the ``nova.conf`` configuration file.

HostId is unique per account and is not globally unique.

**Preconditions**

The server must exist.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - server: server
  - addresses: addresses
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
  - key_name: key_name_resp
  - links: links
  - metadata: metadata_compat
  - name: server_name
  - accessIPv4: accessIPv4
  - accessIPv6: accessIPv6
  - config_drive: config_drive_resp
  - OS-DCF:diskConfig: disk_config
  - OS-EXT-AZ:availability_zone: OS-EXT-AZ:availability_zone
  - OS-EXT-SRV-ATTR:host: OS-EXT-SRV-ATTR:host
  - OS-EXT-SRV-ATTR:hypervisor_hostname: OS-EXT-SRV-ATTR:hypervisor_hostname
  - OS-EXT-SRV-ATTR:instance_name: OS-EXT-SRV-ATTR:instance_name
  - OS-EXT-STS:power_state: OS-EXT-STS:power_state
  - OS-EXT-STS:task_state: OS-EXT-STS:task_state
  - OS-EXT-STS:vm_state: OS-EXT-STS:vm_state
  - os-extended-volumes:volumes_attached: os-extended-volumes:volumes_attached
  - os-extended-volumes:volumes_attached.id: os-extended-volumes:volumes_attached.id
  - os-extended-volumes:volumes_attached.delete_on_termination: os-extended-volumes:volumes_attached.delete_on_termination
  - OS-SRV-USG:launched_at: OS-SRV-USG:launched_at
  - OS-SRV-USG:terminated_at: OS-SRV-USG:terminated_at
  - progress: progress
  - security_groups: security_groups_obj
  - security_group.name: name
  - status: server_status
  - host_status: host_status
  - tenant_id: tenant_id_body
  - updated: updated
  - user_id: user_id
  - fault: fault
  - OS-EXT-SRV-ATTR:hostname: server_hostname
  - OS-EXT-SRV-ATTR:reservation_id: server_reservation_id
  - OS-EXT-SRV-ATTR:launch_index: server_launch_index
  - OS-EXT-SRV-ATTR:kernel_id: server_kernel_id
  - OS-EXT-SRV-ATTR:ramdisk_id: server_ramdisk_id
  - OS-EXT-SRV-ATTR:root_device_name: server_root_device_name
  - OS-EXT-SRV-ATTR:user_data: server_user_data
  - locked: locked

**Example Show Server Details (2.47)**

.. literalinclude:: ../../doc/api_samples/servers/v2.47/server-get-resp.json
   :language: javascript

Update Server
=============

.. rest_method:: PUT /servers/{server_id}

Updates the editable attributes of an existing server.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401),
forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - accessIPv4: accessIPv4_in
  - accessIPv6: accessIPv6_in
  - name: server_name_optional
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - description: server_description

**Example Update server name (2.47)**

.. literalinclude:: ../../doc/api_samples/servers/v2.47/server-update-req.json
   :language: javascript

..
   TODO(sdague): split up the update examples to show them being used
   separately.

   **Example Update server IP addresses: JSON request**

   .. literalinclude:: ../../doc/api_samples/servers/server-update-address-req.json
      :language: javascript

   **Example Update server OS-DCF:diskConfig parameter: JSON request**

   .. literalinclude:: ../../doc/api_samples/servers/server-update-diskconfig-req.json
      :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - server: server
  - addresses: addresses
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
  - key_name: key_name
  - links: links
  - metadata: metadata
  - name: server_name
  - accessIPv4: accessIPv4
  - accessIPv6: accessIPv6
  - OS-DCF:diskConfig: OS-DCF:diskConfig
  - OS-EXT-AZ:availability_zone: OS-EXT-AZ:availability_zone
  - OS-EXT-SRV-ATTR:host: OS-EXT-SRV-ATTR:host
  - OS-EXT-SRV-ATTR:hypervisor_hostname: OS-EXT-SRV-ATTR:hypervisor_hostname
  - OS-EXT-SRV-ATTR:instance_name: OS-EXT-SRV-ATTR:instance_name
  - OS-EXT-STS:power_state: OS-EXT-STS:power_state
  - OS-EXT-STS:task_state: OS-EXT-STS:task_state
  - OS-EXT-STS:vm_state: OS-EXT-STS:vm_state
  - OS-SRV-USG:launched_at: OS-SRV-USG:launched_at
  - OS-SRV-USG:terminated_at: OS-SRV-USG:terminated_at
  - progress: progress
  - security_groups: security_groups_obj
  - security_group.name: name
  - status: server_status
  - host_status: host_status
  - tenant_id: tenant_id_body
  - updated: updated
  - user_id: user_id
  - OS-EXT-SRV-ATTR:hostname: server_hostname
  - OS-EXT-SRV-ATTR:reservation_id: server_reservation_id
  - OS-EXT-SRV-ATTR:launch_index: server_launch_index
  - OS-EXT-SRV-ATTR:kernel_id: server_kernel_id
  - OS-EXT-SRV-ATTR:ramdisk_id: server_ramdisk_id
  - OS-EXT-SRV-ATTR:root_device_name: server_root_device_name
  - OS-EXT-SRV-ATTR:user_data: server_user_data
  - locked: locked

**Example Update server name (2.47)**

.. literalinclude:: ../../doc/api_samples/servers/v2.47/server-update-resp.json
   :language: javascript

Delete Server
=============

.. rest_method:: DELETE /servers/{server_id}

Deletes a server.

By default, the instance is going to be (hard) deleted immediately from
the system, but you can set ``reclaim_instance_interval`` > 0 to make
the API soft delete the instance, so that the instance won't be
deleted until the ``reclaim_instance_interval`` has expired since the
instance was soft deleted. The instance marked as ``SOFT_DELETED`` can
be recovered via ``restore`` action before it's really deleted from the
system.

**Preconditions**

- The server must exist.
- Anyone can delete a server when the status of the server is not
  locked and when the policy allows.
- If the server is locked, you must have administrator privileges to
  delete the server.

**Asynchronous postconditions**

- With correct permissions, you can see the server status as ``deleting``.
- The ports attached to the server, which Nova created during the server
  create process or when attaching interfaces later, are deleted.
- The server does not appear in the list servers response.
- If hard delete, the server managed by OpenStack Compute is deleted
  on the compute node.

**Troubleshooting**

- If server status remains in ``deleting`` status or another error
  status, the request failed. Ensure that you meet the
  preconditions. Then, investigate the compute back end.
- The request returns the HTTP 409 response code when the server is
  locked even if you have correct permissions. Ensure that you meet the
  preconditions then investigate the server status.
- The server managed by OpenStack Compute is not deleted from the
  compute node.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

..
   TODO(sdague): for later phase of updating body.

   conflict is returned under 2 conditions. When the instance is
   locked, so can't be deleted, or if the instance is in some other
   state which makes it not possible to delete.


Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

There is no body content for the response of a successful DELETE query
