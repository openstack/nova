===================
Handling Down Cells
===================

Starting from microversion 2.69 if there are transient conditions in a
deployment like partial infrastructure failures (for example a cell
not being reachable), some API responses may contain partial results
(i.e. be missing some keys). The server operations which exhibit this
behavior are described below:

* List Servers (GET /servers): This operation may give partial
  constructs from the non-responsive portion of the infrastructure. A
  typical response, while listing servers from unreachable parts of
  the infrastructure, would include only the following keys from
  available information:

  - status: The state of the server which will be "UNKNOWN".
  - id: The UUID of the server.
  - links: Links to the servers in question.

  A sample response for a GET /servers request that includes one
  result each from an unreachable and a healthy part of the
  infrastructure is shown below.

  Response::

     {
         "servers": [
             {
                 "status": "UNKNOWN",
                 "id": "bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                 "links": [
                    {
                        "rel": "self",
                        "href": "http://openstack.example.com/v2/6f70656e737461636b20342065766572/servers/bcc6c6dd-3d0a-4633-9586-60878fd68edb"
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://openstack.example.com/6f70656e737461636b20342065766572/servers/bcc6c6dd-3d0a-4633-9586-60878fd68edb"
                    }
                ]
             },
             {
                 "id": "22c91117-08de-4894-9aa9-6ef382400985",
                 "name": "test_server",
                 "links": [
                    {
                        "rel": "self",
                        "href": "http://openstack.example.com/v2/6f70656e737461636b20342065766572/servers/22c91117-08de-4894-9aa9-6ef382400985"
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://openstack.example.com/6f70656e737461636b20342065766572/servers/22c91117-08de-4894-9aa9-6ef382400985"
                    }
                ]
             }
         ]
     }

* List Servers Detailed (GET /servers/detail): This operation may give
  partial constructs from the non-responsive portion of the
  infrastructure. A typical response, while listing servers from
  unreachable parts of the infrastructure, would include only the
  following keys from available information:

  - status: The state of the server which will be "UNKNOWN".
  - id: The UUID of the server.
  - tenant_id: The tenant_id to which the server belongs to.
  - created: The time of server creation.
  - links: Links to the servers in question.

  A sample response for a GET /servers/details request that includes
  one result each from an unreachable and a healthy part of the
  infrastructure is shown below.

  Response::

     {
         "servers": [
               {
                   "created": "2018-06-29T15:07:29Z",
                   "status": "UNKNOWN",
                   "tenant_id": "940f47b984034c7f8f9624ab28f5643c",
                   "id": "bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                   "links": [
                       {
                           "href": "http://openstack.example.com/v2.1/6f70656e737461636b20342065766572/servers/bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                           "rel": "self"
                       },
                       {
                           "href": "http://openstack.example.com/6f70656e737461636b20342065766572/servers/bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                           "rel": "bookmark"
                       }
                   ]
               },
               {
                   "OS-DCF:diskConfig": "AUTO",
                   "OS-EXT-AZ:availability_zone": "nova",
                   "OS-EXT-SRV-ATTR:host": "compute",
                   "OS-EXT-SRV-ATTR:hostname": "new-server-test",
                   "OS-EXT-SRV-ATTR:hypervisor_hostname": "fake-mini",
                   "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
                   "OS-EXT-SRV-ATTR:kernel_id": "",
                   "OS-EXT-SRV-ATTR:launch_index": 0,
                   "OS-EXT-SRV-ATTR:ramdisk_id": "",
                   "OS-EXT-SRV-ATTR:reservation_id": "r-y0w4v32k",
                   "OS-EXT-SRV-ATTR:root_device_name": "/dev/sda",
                   "OS-EXT-SRV-ATTR:user_data": "IyEvYmluL2Jhc2gKL2Jpbi9zdQplY2hvICJJIGFtIGluIHlvdSEiCg==",
                   "OS-EXT-STS:power_state": 1,
                   "OS-EXT-STS:task_state": null,
                   "OS-EXT-STS:vm_state": "active",
                   "OS-SRV-USG:launched_at": "2017-10-10T15:49:09.516729",
                   "OS-SRV-USG:terminated_at": null,
                   "accessIPv4": "1.2.3.4",
                   "accessIPv6": "80fe::",
                   "addresses": {
                       "private": [
                           {
                               "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
                               "OS-EXT-IPS:type": "fixed",
                               "addr": "192.168.0.3",
                               "version": 4
                           }
                       ]
                   },
                   "config_drive": "",
                   "created": "2017-10-10T15:49:08Z",
                   "description": null,
                   "flavor": {
                       "disk": 1,
                       "ephemeral": 0,
                       "extra_specs": {
                           "hw:numa_nodes": "1"
                       },
                       "original_name": "m1.tiny.specs",
                       "ram": 512,
                       "swap": 0,
                       "vcpus": 1
                   },
                   "hostId": "2091634baaccdc4c5a1d57069c833e402921df696b7f970791b12ec6",
                   "host_status": "UP",
                   "id": "569f39f9-7c76-42a1-9c2d-8394e2638a6d",
                   "image": {
                       "id": "70a599e0-31e7-49b7-b260-868f441e862b",
                       "links": [
                           {
                               "href": "http://openstack.example.com/6f70656e737461636b20342065766572/images/70a599e0-31e7-49b7-b260-868f441e862b",
                               "rel": "bookmark"
                           }
                       ]
                   },
                   "key_name": null,
                   "links": [
                       {
                           "href": "http://openstack.example.com/v2.1/6f70656e737461636b20342065766572/servers/569f39f9-7c76-42a1-9c2d-8394e2638a6d",
                           "rel": "self"
                       },
                       {
                           "href": "http://openstack.example.com/6f70656e737461636b20342065766572/servers/569f39f9-7c76-42a1-9c2d-8394e2638a6d",
                           "rel": "bookmark"
                       }
                   ],
                   "locked": false,
                   "metadata": {
                       "My Server Name": "Apache1"
                   },
                   "name": "new-server-test",
                   "os-extended-volumes:volumes_attached": [],
                   "progress": 0,
                   "security_groups": [
                       {
                           "name": "default"
                       }
                   ],
                   "status": "ACTIVE",
                   "tags": [],
                   "tenant_id": "6f70656e737461636b20342065766572",
                   "trusted_image_certificates": [
                       "0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8",
                       "674736e3-f25c-405c-8362-bbf991e0ce0a"
                   ],
                   "updated": "2017-10-10T15:49:09Z",
                   "user_id": "fake"
               }
         ]
     }

  **Edge Cases**

  * **Filters:** If the user is listing servers using filters, results
    from unreachable parts of the infrastructure cannot be tested for
    matching those filters and thus no minimalistic construct will be
    provided. Note that by default ``openstack server list`` uses the
    ``deleted=False`` and ``project_id=tenant_id`` filters and since
    we know both of these fundamental values at all times, they are
    the only allowed filters to be applied to servers with only
    partial information available.  Hence only doing ``openstack
    server list`` and ``openstack server list --all-projects`` (admin
    only) will show minimalistic results when parts of the
    infrastructure are unreachable. Other filters like ``openstack
    server list --deleted`` or ``openstack server list --host xx``
    will skip the results depending on the administrator's
    configuration of the deployment.  Note that the filter ``openstack
    server list --limit`` will also skip the results and if not
    specified will return 1000 (or the configured default) records
    from the available parts of the infrastructure.

  * **Marker:** If the user does ``openstack server list --marker`` it will
    fail with a 500 if the marker is an instance that is no longer reachable.

  * **Sorting:** We exclude the unreachable parts of the infrastructure just like
    we do for filters since there is no way of obtaining valid sorted results from
    those parts with missing information.

  * **Paging:** We ignore the parts of the deployment which are non-responsive.
    For example if we have three cells A (reachable state), B (unreachable state)
    and C (reachable state) and if the marker is half way in A, we would get the
    remaining half of the results from A, all the results from C and ignore cell B.

  .. note:: All the edge cases that are not supported for minimal constructs would
     give responses based on the administrator's configuration of the deployment,
     either skipping those results or returning an error.

* Show Server Details (GET /servers/{server_id}): This operation may
  give partial constructs from the non-responsive portion of the
  infrastructure. A typical response while viewing a server from an
  unreachable part of the infrastructure would include only the
  following keys from available information:

  - status: The state of the server which will be "UNKNOWN".
  - id: The UUID of the server.
  - tenant_id: The tenant_id to which the server belongs to.
  - created: The time of server creation.
  - user_id: The user_id to which the server belongs to. This may be "UNKNOWN"
    for older servers.
  - image: The image details of the server. If it is not set like
    in the boot-from-volume case, this value will be an empty string.
  - flavor: The flavor details of the server.
  - availability_zone: The availability_zone of the server if it was specified
    during during boot time and "UNKNOWN" otherwise.
  - power_state: Its value will be 0 (``NOSTATE``).
  - links: Links to the servers in question.
  - server_groups: The UUIDs of the server groups to which the server belongs.
    Currently this can contain at most one entry. Note that this key will be in
    the response only from the "2.71" microversion.

  A sample response for a GET /servers/{server_id} request that
  includes one server from an unreachable part of the infrastructure
  is shown below.

  Response::

     {
         "server": [
             {
                 "created": "2018-06-29T15:07:29Z",
                 "status": "UNKNOWN",
                 "tenant_id": "940f47b984034c7f8f9624ab28f5643c",
                 "id": "bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                 "user_id": "940f47b984034c7f8f9624ab28f5643c",
                 "image": {
                     "id": "70a599e0-31e7-49b7-b260-868f441e862b",
                 },
                 "flavor": {
                     "disk": 1,
                     "ephemeral": 0,
                     "extra_specs": {
                         "hw:numa_nodes": "1"
                     },
                     "original_name": "m1.tiny.specs",
                     "ram": 512,
                     "swap": 0,
                     "vcpus": 1
                 },
                 "OS-EXT-AZ:availability_zone": "geneva",
                 "OS-EXT-STS:power_state": 0,
                 "links": [
                       {
                           "href": "http://openstack.example.com/v2.1/6f70656e737461636b20342065766572/servers/bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                           "rel": "self"
                       },
                       {
                           "href": "http://openstack.example.com/6f70656e737461636b20342065766572/servers/bcc6c6dd-3d0a-4633-9586-60878fd68edb",
                           "rel": "bookmark"
                       }
                 ],
                 "server_groups": ["0fd77252-4eef-4ec4-ae9b-e05dfc98aeac"]
             }
         ]
     }

* List Compute Services (GET /os-services): This operation may give
  partial constructs for the services with :program:`nova-compute` as
  their binary from the non-responsive portion of the
  infrastructure. A typical response while listing the compute
  services from unreachable parts of the infrastructure would include
  only the following keys for the :program:`nova-compute` services
  from available information while the other services like the
  :program:`nova-conductor` service will be skipped from the result:

  - binary: The binary name of the service which would always be
    ``nova-compute``.
  - host: The name of the host running the service.
  - status: The status of the service which will be "UNKNOWN".

  A sample response for a GET /servers request that includes two
  compute services from unreachable parts of the infrastructure and
  other services from a healthy one are shown below.

  Response::

     {
         "services": [
             {
                 "binary": "nova-compute",
                 "host": "host1",
                 "status": "UNKNOWN"
             },
             {
                 "binary": "nova-compute",
                 "host": "host2",
                 "status": "UNKNOWN"
             },
             {
                 "id": 1,
                 "binary": "nova-scheduler",
                 "disabled_reason": "test1",
                 "host": "host3",
                 "state": "up",
                 "status": "disabled",
                 "updated_at": "2012-10-29T13:42:02.000000",
                 "forced_down": false,
                 "zone": "internal"
             },
             {
                 "id": 2,
                 "binary": "nova-compute",
                 "disabled_reason": "test2",
                 "host": "host4",
                 "state": "up",
                 "status": "disabled",
                 "updated_at": "2012-10-29T13:42:05.000000",
                 "forced_down": false,
                 "zone": "nova"
             }
         ]
     }
