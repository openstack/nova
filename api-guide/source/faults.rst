======
Faults
======

This doc explains how to understand what has happened to your API request.

Every HTTP request has a status code. 2xx codes signify the API call was a
success. However, that is often not the end of the story. That generally only
means the request to start the operation has been accepted. It does not mean
the action you requested has successfully completed.


Tracking Errors by Request ID
=============================

There are two types of request ID.

.. list-table::
  :header-rows: 1
  :widths: 2,8

  * - Type
    - Description
  * - Local request ID
    - Locally generated unique request ID by each service and different between
      all services (Nova, Cinder, Glance, Neutron, etc.) involved
      in that operation. The format is ``req-`` + UUID (UUID4).
  * - Global request ID
    - User specified request ID which is utilized as common identifier
      by all services (Nova, Cinder, Glance, Neutron, etc.) involved
      in that operation. This request ID is same among all services involved
      in that operation.
      The format is ``req-`` + UUID (UUID4).

It is extremely common for clouds to have an ELK (Elastic Search, Logstash,
Kibana) infrastructure consuming their logs.
The only way to query these flows is if there is a common identifier across
all relevant messages. The global request ID immediately makes existing
deployed tooling better for managing OpenStack.

**Request Header**

In each REST API request, you can specify the global request ID
in ``X-Openstack-Request-Id`` header, starting from microversion 2.46.
The format must be ``req-`` + UUID (UUID4).
If not in accordance with the format, the global request ID is ignored by Nova.

Request header example::

  X-Openstack-Request-Id: req-3dccb8c4-08fe-4706-a91d-e843b8fe9ed2

**Response Header**

In each REST API request, ``X-Compute-Request-Id`` is returned
in the response header.
Starting from microversion 2.46, ``X-Openstack-Request-Id`` is also returned
in the response header.

``X-Compute-Request-Id`` and ``X-Openstack-Request-Id`` are local request IDs.
The global request IDs are not returned.

Response header example::

  X-Compute-Request-Id: req-d7bc29d0-7b99-4aeb-a356-89975043ab5e
  X-Openstack-Request-Id: req-d7bc29d0-7b99-4aeb-a356-89975043ab5e

Server Actions
--------------

Most `server action APIs`_ are asynchronous. Usually the API service will do
some minimal work and then send the request off to the ``nova-compute`` service
to complete the action and the API will return a 202 response to the client.
The client will poll the API until the operation completes, which could be a
status change on the server but is usually at least always waiting for the
server ``OS-EXT-STS:task_state`` field to go to ``null`` indicating the action
has completed either successfully or with an error.

If a server action fails and the server status changes to ``ERROR`` an
:ref:`instance fault <instance-fault>` will be shown with the server details.

The `os-instance-actions API`_ allows users end users to list the outcome of
server actions, referencing the requested action by request id. This is useful
when an action fails and the server status does not change to ``ERROR``.

To illustrate, consider a server (vm1) created with flavor ``m1.tiny``:

.. code-block:: console

  $ openstack server create --flavor m1.tiny --image cirros-0.4.0-x86_64-disk --wait vm1
  +-----------------------------+-----------------------------------------------------------------+
  | Field                       | Value                                                           |
  +-----------------------------+-----------------------------------------------------------------+
  | OS-DCF:diskConfig           | MANUAL                                                          |
  | OS-EXT-AZ:availability_zone | nova                                                            |
  | OS-EXT-STS:power_state      | Running                                                         |
  | OS-EXT-STS:task_state       | None                                                            |
  | OS-EXT-STS:vm_state         | active                                                          |
  | OS-SRV-USG:launched_at      | 2019-12-02T19:14:48.000000                                      |
  | OS-SRV-USG:terminated_at    | None                                                            |
  | accessIPv4                  |                                                                 |
  | accessIPv6                  |                                                                 |
  | addresses                   | private=10.0.0.60, fda0:e0c4:2764:0:f816:3eff:fe03:806          |
  | adminPass                   | NgascCr3dYo4                                                    |
  | config_drive                |                                                                 |
  | created                     | 2019-12-02T19:14:42Z                                            |
  | flavor                      | m1.tiny (1)                                                     |
  | hostId                      | 22e88bec09a7e33606348fce0abac0ebbbe091a35e29db1498ec4e14        |
  | id                          | 344174b8-34fd-4017-ae29-b9084dcf3861                            |
  | image                       | cirros-0.4.0-x86_64-disk (cce5e6d6-d359-4152-b277-1b4f1871557f) |
  | key_name                    | None                                                            |
  | name                        | vm1                                                             |
  | progress                    | 0                                                               |
  | project_id                  | b22597ea961545f3bde1b2ede0bd5b91                                |
  | properties                  |                                                                 |
  | security_groups             | name='default'                                                  |
  | status                      | ACTIVE                                                          |
  | updated                     | 2019-12-02T19:14:49Z                                            |
  | user_id                     | 046033fb3f824550999752b6525adbac                                |
  | volumes_attached            |                                                                 |
  +-----------------------------+-----------------------------------------------------------------+

The owner of the server then tries to resize the server to flavor ``m1.small``
which fails because there are no hosts available on which to resize the server:

.. code-block:: console

  $ openstack server resize --flavor m1.small --wait vm1
  Complete

Despite the openstack command saying the operation completed, the server shows
the original ``m1.tiny`` flavor and the status is not ``VERIFY_RESIZE``:

.. code-block::

  $ openstack server show vm1 -f value -c status -c flavor
  m1.tiny (1)
  ACTIVE

Since the status is not ``ERROR`` there are is no ``fault`` field in the server
details so we find the details by listing the events for the server:

.. code-block:: console

  $ openstack server event list vm1
  +------------------------------------------+--------------------------------------+--------+----------------------------+
  | Request ID                               | Server ID                            | Action | Start Time                 |
  +------------------------------------------+--------------------------------------+--------+----------------------------+
  | req-ea1b0dfc-3186-42a9-84ff-c4f4fb130fae | 344174b8-34fd-4017-ae29-b9084dcf3861 | resize | 2019-12-02T19:15:35.000000 |
  | req-4cdc4c93-0668-4ae6-98c8-a0a5fcc63d39 | 344174b8-34fd-4017-ae29-b9084dcf3861 | create | 2019-12-02T19:14:42.000000 |
  +------------------------------------------+--------------------------------------+--------+----------------------------+

To see details about the ``resize`` action, we use the Request ID for that
action:

.. code-block:: console

  $ openstack server event show vm1 req-ea1b0dfc-3186-42a9-84ff-c4f4fb130fae
  +---------------+------------------------------------------+
  | Field         | Value                                    |
  +---------------+------------------------------------------+
  | action        | resize                                   |
  | instance_uuid | 344174b8-34fd-4017-ae29-b9084dcf3861     |
  | message       | Error                                    |
  | project_id    | b22597ea961545f3bde1b2ede0bd5b91         |
  | request_id    | req-ea1b0dfc-3186-42a9-84ff-c4f4fb130fae |
  | start_time    | 2019-12-02T19:15:35.000000               |
  | user_id       | 046033fb3f824550999752b6525adbac         |
  +---------------+------------------------------------------+

We see the message is "Error" but are not sure what failed. By default the
event details for an action are not shown to users without the admin role so
use microversion 2.51 to see the events (the ``events`` field is JSON-formatted
here for readability):

.. code-block::

  $ openstack --os-compute-api-version 2.51 server event show vm1 req-ea1b0dfc-3186-42a9-84ff-c4f4fb130fae -f json -c events
  {
    "events": [
      {
        "event": "cold_migrate",
        "start_time": "2019-12-02T19:15:35.000000",
        "finish_time": "2019-12-02T19:15:36.000000",
        "result": "Error"
      },
      {
        "event": "conductor_migrate_server",
        "start_time": "2019-12-02T19:15:35.000000",
        "finish_time": "2019-12-02T19:15:36.000000",
        "result": "Error"
      }
    ]
  }

By default policy configuration a user with the admin role can see a
``traceback`` for each failed event just like with an instance fault:

.. code-block::

  $ source openrc admin admin
  $ openstack --os-compute-api-version 2.51 server event show 344174b8-34fd-4017-ae29-b9084dcf3861 req-ea1b0dfc-3186-42a9-84ff-c4f4fb130fae -f json -c events
  {
    "events": [
      {
        "event": "cold_migrate",
        "start_time": "2019-12-02T19:15:35.000000",
        "finish_time": "2019-12-02T19:15:36.000000",
        "result": "Error",
        "traceback": "  File \"/opt/stack/nova/nova/conductor/manager.py\",
        line 301, in migrate_server\n    host_list)\n
        File \"/opt/stack/nova/nova/conductor/manager.py\", line 367, in
        _cold_migrate\n    raise exception.NoValidHost(reason=msg)\n"
      },
      {
        "event": "conductor_migrate_server",
        "start_time": "2019-12-02T19:15:35.000000",
        "finish_time": "2019-12-02T19:15:36.000000",
        "result": "Error",
        "traceback": "  File \"/opt/stack/nova/nova/compute/utils.py\",
        line 1410, in decorated_function\n    return function(self, context,
        *args, **kwargs)\n  File \"/opt/stack/nova/nova/conductor/manager.py\",
        line 301, in migrate_server\n    host_list)\n
        File \"/opt/stack/nova/nova/conductor/manager.py\", line 367, in
        _cold_migrate\n    raise exception.NoValidHost(reason=msg)\n"
      }
    ]
  }

.. _server action APIs: https://docs.openstack.org/api-ref/compute/#servers-run-an-action-servers-action
.. _os-instance-actions API: https://docs.openstack.org/api-ref/compute/#servers-actions-servers-os-instance-actions

Logs
----

All logs on the system, by default, include the global request ID and
the local request ID when available. This allows an administrator to
track the API request processing as it transitions between all the
different nova services or between nova and other component services
called by nova during that request.

When nova services receive the local request IDs of other components in the
``X-Openstack-Request-Id`` header, the local request IDs are output to logs
along with the local request IDs of nova services.

.. tip::

   If a session client is used in client library, set ``DEBUG`` level to
   the ``keystoneauth`` log level. If not, set ``DEBUG`` level to the client
   library package. e.g. ``glanceclient``, ``cinderclient``.

Sample log output is provided below.
In this example, nova is using local request ID
``req-034279a7-f2dd-40ff-9c93-75768fda494d``,
while neutron is using local request ID
``req-39b315da-e1eb-4ab5-a45b-3f2dbdaba787``::

  Jun 19 09:16:34 devstack-master nova-compute[27857]: DEBUG keystoneauth.session [None req-034279a7-f2dd-40ff-9c93-75768fda494d admin admin] POST call to network for http://10.0.2.15:9696/v2.0/ports used request id req-39b315da-e1eb-4ab5-a45b-3f2dbdaba787 {{(pid=27857) request /usr/local/lib/python2.7/dist-packages/keystoneauth1/session.py:640}}

.. note::

   The local request IDs are useful to make 'call graphs'.

.. _instance-fault:

Instance Faults
---------------

Nova often adds an instance fault DB entry for an exception that happens
while processing an API request. This often includes more administrator
focused information, such as a stack trace. For a server with status
``ERROR`` or ``DELETED``, a ``GET /servers/{server_id}`` request will include
a ``fault`` object in the response body for the ``server`` resource. For
example::

  GET https://10.211.2.122/compute/v2.1/servers/c76a7603-95be-4368-87e9-7b9b89fb1d7e
  {
     "server": {
        "id": "c76a7603-95be-4368-87e9-7b9b89fb1d7e",
        "fault": {
           "created": "2018-04-10T13:49:40Z",
           "message": "No valid host was found.",
           "code": 500
        },
        "status": "ERROR",
        ...
     }
  }

Notifications
-------------

In many cases there are also notifications emitted that describe the error.
This is an administrator focused API, that works best when treated as
structured logging.

.. _synchronous_faults:

Synchronous Faults
==================

If an error occurs while processing our API request, you get a non 2xx
API status code. The system also returns additional
information about the fault in the body of the response.


**Example: Fault: JSON response**

.. code::

    {
       "itemNotFound":{
          "code": 404,
          "message":"Aggregate agg_h1 could not be found."
       }
    }

The error ``code`` is returned in the body of the response for convenience.
The ``message`` section returns a human-readable message that is appropriate
for display to the end user. The ``details`` section is optional and may
contain information--for example, a stack trace--to assist in tracking
down an error. The ``details`` section might or might not be appropriate for
display to an end user.

The root element of the fault (such as, computeFault) might change
depending on the type of error. The following link contains a list of possible
elements along with their associated error codes.

For more information on possible error code, please see:
http://specs.openstack.org/openstack/api-wg/guidelines/http/response-codes.html

Asynchronous faults
===================

An error may occur in the background while a server is being built or while a
server is executing an action.

In these cases, the server is usually placed in an ``ERROR`` state. For some
operations, like resize, it is possible that the operation fails but
the instance gracefully returned to its original state before attempting the
operation. In both of these cases, you should be able to find out more from
the `Server Actions`_ API described above.

When a server is placed into an ``ERROR`` state, a fault is embedded in the
offending server. Note that these asynchronous faults follow the same format
as the synchronous ones. The fault contains an error code, a human readable
message, and optional details about the error. Additionally, asynchronous
faults may also contain a ``created`` timestamp that specifies when the fault
occurred.


**Example: Server in error state: JSON response**

.. code::

    {
        "server": {
            "id": "52415800-8b69-11e0-9b19-734f0000ffff",
            "tenant_id": "1234",
            "user_id": "5678",
            "name": "sample-server",
            "created": "2010-08-10T12:00:00Z",
            "hostId": "e4d909c290d0fb1ca068ffafff22cbd0",
            "status": "ERROR",
            "progress": 66,
            "image" : {
                "id": "52415800-8b69-11e0-9b19-734f6f007777"
            },
            "flavor" : {
                "id": "52415800-8b69-11e0-9b19-734f216543fd"
            },
            "fault" : {
                "code" : 500,
                "created": "2010-08-10T11:59:59Z",
                "message": "No valid host was found. There are not enough hosts available.",
                "details": [snip]
            },
            "links": [
                {
                    "rel": "self",
                    "href": "http://servers.api.openstack.org/v2/1234/servers/52415800-8b69-11e0-9b19-734f000004d2"
                },
                {
                    "rel": "bookmark",
                    "href": "http://servers.api.openstack.org/1234/servers/52415800-8b69-11e0-9b19-734f000004d2"
                }
            ]
        }
    }
