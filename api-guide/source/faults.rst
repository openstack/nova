======
Faults
======

This doc looks at how to understand what has happened to your API request.

Every HTTP request has a status code. 2xx codes signify the API was a success.
However, that is often not the end of the story. That generally only means the
request to start the operation has been accepted, it does not mean the action
you requested has successfully completed.


Tracking Errors by Request ID
==============================

Every request made has a unique Request ID.
This is returned in a response header.
Here is an example response header:

X-Compute-Request-ID: req-4b9e5c04-c40f-4b4f-960e-6ac0858dca6c

Server Actions
--------------

There is an API for end users to list the outcome of Server Actions,
referencing the requested action by request id.

For more details, please see:
http://developer.openstack.org/api-ref-compute-v2.1.html#os-instance-actions-v2.1

Logs
----

All logs on the system, by default, include the request-id when available.
This allows an administrator to track the API request processing as it
transitions between all the different nova services.

Instance Faults
---------------

Nova often adds an instance fault DB entry for an exception that happens
while processing an API request. This often includes more administrator
focused information, such as a stack trace.
However, there is currently no API to retrieve this information.

Notifications
-------------

In many cases there are also notifications emitted that describe the error.
This is an administrator focused API, that works best when treated as
structured logging.


Synchronous Faults
==================

If an error occurs while processing our API request, you get a non 2xx
API status code. The system also returns additional
information about the fault in the body of the response.


**Example: Fault: JSON response**

.. code::

    {
       "itemNotFound":{
          "code": 404,
          "message":"Aggregate agg_h1 could not be found."
       }
    }

The error code is returned in the body of the response for convenience.
The message section returns a human-readable message that is appropriate
for display to the end user. The details section is optional and may
contain information—for example, a stack trace—to assist in tracking
down an error. The detail section might or might not be appropriate for
display to an end user.

The root element of the fault (such as, computeFault) might change
depending on the type of error. The following is a list of possible
elements along with their associated error codes.

For more information on possible error code, please see:
http://specs.openstack.org/openstack/api-wg/guidelines/http.html#http-response-codes

Asynchronous faults
===================

An error may occur in the background while a server is being built or while a
server is executing an action.

In these cases, the server is usually placed in an ``ERROR`` state. For some
operations, like resize, its possible that the operations fails but
the instance gracefully returned to its original state before attempting the
operation. In both of these cases, you should be able to find out more from
the Server Actions API described above.

When a server is placed into an ``ERROR`` state, a fault is embedded in the
offending server. Note that these asynchronous faults follow the same format
as the synchronous ones. The fault contains an error code, a human readable
message, and optional details about the error. Additionally, asynchronous
faults may also contain a created timestamp that specifies when the fault
occurred.


**Example: Server in error state: JSON response**

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
