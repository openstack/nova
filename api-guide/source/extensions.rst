==========
Extensions
==========

The OpenStack Compute API v2.0 is extensible. Extensions serve two purposes:
They allow the introduction of new features in the API without requiring
a version change and they allow the introduction of vendor specific
niche functionality. Applications can programmatically list available
extensions by performing a **GET** on the ``/extensions`` URI. Note that
this is a versioned request; that is, an extension available in one API
version might not be available in another.

Extensions may also be queried individually by their unique alias. This
provides the simplest method of checking if an extension is available
because an unavailable extension issues an itemNotFound (404)
response.

Extensions may define new data types, parameters, actions, headers,
states, and resources.

NOTE: Extensions is a deprecated concept in Nova and their support
will be removed in a future version. If your product or cloud relies
on extensions you should work on getting those features into the main
upstream project.

Important
~~~~~~~~~

Applications should ignore response data that contains extension
elements. An extended state should always be treated as an ``UNKNOWN``
state if the application does not support the extension. Applications
should also verify that an extension is available before submitting an
extended request.


**Example: Extended server: JSON response**

.. code::

    {
        "servers": [
            {
                "id": "52415800-8b69-11e0-9b19-734f6af67565",
                "tenant_id": "1234",
                "user_id": "5678",
                "name": "sample-server",
                "updated": "2010-10-10T12:00:00Z",
                "created": "2010-08-10T12:00:00Z",
                "hostId": "e4d909c290d0fb1ca068ffaddf22cbd0",
                "status": "BUILD",
                "progress": 60,
                "accessIPv4" : "67.23.10.132",
                "accessIPv6" : "::babe:67.23.10.132",
                "image" : {
                    "id": "52415800-8b69-11e0-9b19-734f6f006e54",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://servers.api.openstack.org/v2/1234/images/52415800-8b69-11e0-9b19-734f6f006e54"
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://servers.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f6f006e54"
                        }
                    ]
                },
                "flavor" : {
                    "id": "52415800-8b69-11e0-9b19-734f216543fd",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://servers.api.openstack.org/v2/1234/flavors/52415800-8b69-11e0-9b19-734f216543fd"
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://servers.api.openstack.org/1234/flavors/52415800-8b69-11e0-9b19-734f216543fd"
                        }
                    ]
                },
                "addresses": {
                    "public" : [
                        {
                            "version": 4,
                            "addr": "67.23.10.132"
                        },
                        {
                            "version": 6,
                            "addr": "::babe:67.23.10.132"
                        },
                        {
                            "version": 4,
                            "addr": "67.23.10.131"
                        },
                        {
                            "version": 6,
                            "addr": "::babe:4317:0A83"
                        }
                    ],
                    "private" : [
                        {
                            "version": 4,
                            "addr": "10.176.42.16"
                        },
                        {
                            "version": 6,
                            "addr": "::babe:10.176.42.16"
                        }
                    ]
                },
                "metadata": {
                    "Server Label": "Web Head 1",
                    "Image Version": "2.1"
                },
                "links": [
                    {
                        "rel": "self",
                        "href": "http://servers.api.openstack.org/v2/1234/servers/52415800-8b69-11e0-9b19-734f6af67565"
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://servers.api.openstack.org/1234/servers/52415800-8b69-11e0-9b19-734f6af67565"
                    }
                ],
                "RS-CBS:volumes": [
                    {
                        "name": "OS",
                        "href": "https://cbs.api.rackspacecloud.com/12934/volumes/19"
                    },
                    {
                        "name": "Work",
                        "href": "https://cbs.api.rackspacecloud.com/12934/volumes/23"
                    }
                ]
            }
        ]
    }


**Example: Extended action: JSON response**

.. code::

    {
       "RS-CBS:attach-volume":{
          "href":"https://cbs.api.rackspacecloud.com/12934/volumes/19"
       }
    }
