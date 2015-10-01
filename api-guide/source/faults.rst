======
Faults
======

Synchronous faults
~~~~~~~~~~~~~~~~~~

When an error occurs at request time, the system also returns additional
information about the fault in the body of the response.


**Example: Fault: JSON response**

.. code::

    {
       "computeFault":{
          "code":500,
          "message":"Fault!",
          "details":"Error Details..."
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

Fault elements and error codes
------------------------------

-  ``computeFault``: 500, 400, other codes possible

- ``notImplemented``: 501

-  ``serverCapacityUnavailable``: 503

- ``serviceUnavailable``: 503

- ``badRequest``: 400

- ``unauthorized``: 401

- ``forbidden``: 403

- ``resizeNotAllowed``: 403

- ``itemNotFound``: 404

- ``badMethod``: 405

- ``backupOrResizeInProgress``: 409

- ``buildInProgress``: 409

- ``conflictingRequest``: 409

- ``overLimit``: 413

- ``badMediaType``: 415

**Example: Item Not Found fault: JSON response**

.. code::

    {
       "itemNotFound":{
          "code":404,
          "message":"Not Found",
          "details":"Error Details..."
       }
    }


From an XML schema perspective, all API faults are extensions of the
base ComputeAPIFault fault type. When working with a system that binds
XML to actual classes (such as JAXB), you should use ComputeAPIFault as
a catch-all if you do not want to distinguish between individual fault
types.

The OverLimit fault is generated when a rate limit threshold is
exceeded. For convenience, the fault adds a retryAfter attribute that
contains the content of the Retry-After header in XML Schema 1.0
date/time format.


**Example: Over Limit fault: JSON response**

.. code::

    {
        "overLimit" : {
            "code" : 413,
            "message" : "OverLimit Retry...",
            "details" : "Error Details...",
            "retryAfter" : "2010-08-01T00:00:00Z"
        }
    }


Asynchronous faults
~~~~~~~~~~~~~~~~~~~

An error may occur in the background while a server or image is being
built or while a server is executing an action. In these cases, the
server or image is placed in an ``ERROR`` state and the fault is
embedded in the offending server or image. Note that these asynchronous
faults follow the same format as the synchronous ones. The fault
contains an error code, a human readable message, and optional details
about the error. Additionally, asynchronous faults may also contain a
created timestamp that specify when the fault occurred.


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
                "code" : 404,
                "created": "2010-08-10T11:59:59Z",
                "message" : "Could not find image 52415800-8b69-11e0-9b19-734f6f007777",
                "details" : "Fault details"
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


**Example: Image in error state: JSON response**

.. code::

    {
        "image" : {
            "id" : "52415800-8b69-11e0-9b19-734f5736d2a2",
            "name" : "My Server Backup",
            "created" : "2010-08-10T12:00:00Z",
            "status" : "SAVING",
            "progress" : 89,
            "server" : {
                "id": "52415800-8b69-11e0-9b19-734f335aa7b3"
            },
            "fault" : {
                "code" : 500,
                "message" : "An internal error occurred",
                "details" : "Error details"
            },
            "links": [
                {
                    "rel" : "self",
                    "href" : "http://servers.api.openstack.org/v2/1234/images/52415800-8b69-11e0-9b19-734f5736d2a2"
                },
                {
                    "rel" : "bookmark",
                    "href" : "http://servers.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f5736d2a2"
                }
            ]
        }
    }
