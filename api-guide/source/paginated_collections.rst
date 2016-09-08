=====================
Paginated collections
=====================

To reduce load on the service, list operations return a maximum number
of items at a time. The maximum number of items returned is determined
by the compute provider. To navigate the collection, the *``limit``* and
*``marker``* parameters can be set in the URI. For example:

.. code::

    ?limit=100&marker=1234

The *``marker``* parameter is the ID of the last item in the previous
list. By default, the service sorts items by create time in descending order.
When the service cannot identify a create time, it sorts items by ID. The
*``limit``* parameter sets the page size. Both parameters are optional. If the
client requests a *``limit``* beyond one that is supported by the deployment
an overLimit (413) fault may be thrown. A marker with an invalid ID returns
a badRequest (400) fault.

For convenience, collections should contain atom ``next``
links. They may optionally also contain ``previous`` links but the current
implementation does not contain ``previous`` links. The last
page in the list does not contain a link to "next" page. The following examples
illustrate three pages in a collection of images. The first page was
retrieved through a **GET** to
``http://servers.api.openstack.org/v2.1/servers?limit=1``. In these
examples, the *``limit``* parameter sets the page size to a single item.
Subsequent links honor the initial page size. Thus, a client can follow
links to traverse a paginated collection without having to input the
*``marker``* parameter.


**Example: Servers collection: JSON (first page)**

.. code::

    {
       "servers_links":[
          {
             "href":"https://servers.api.openstack.org/v2.1/servers?limit=1&marker=fc45ace4-3398-447b-8ef9-72a22086d775",
             "rel":"next"
          }
       ],
       "servers":[
          {
             "id":"fc55acf4-3398-447b-8ef9-72a42086d775",
             "links":[
                {
                   "href":"https://servers.api.openstack.org/v2.1/servers/fc45ace4-3398-447b-8ef9-72a22086d775",
                   "rel":"self"
                },
                {
                   "href":"https://servers.api.openstack.org/v2.1/servers/fc45ace4-3398-447b-8ef9-72a22086d775",
                   "rel":"bookmark"
                }
             ],
             "name":"elasticsearch-0"
          }
       ]
    }


In JSON, members in a paginated collection are stored in a JSON array
named after the collection. A JSON object may also be used to hold
members in cases where using an associative array is more practical.
Properties about the collection itself, including links, are contained
in an array with the name of the entity an underscore (\_) and
``links``. The combination of the objects and arrays that start with the
name of the collection and an underscore represent the collection in
JSON. The approach allows for extensibility of paginated collections by
allowing them to be associated with arbitrary properties. It also allows
collections to be embedded in other objects as illustrated below. Here,
a subset of metadata items are presented within the image. Clients must
keep following the ``next`` link to retrieve the full set of metadata.


**Example: Paginated metadata: JSON**

.. code::

    {
        "server": {
            "id": "52415800-8b69-11e0-9b19-734f6f006e54",
            "name": "Elastic",
            "metadata": {
                "Version": "1.3",
                "ServiceType": "Bronze"
            },
            "metadata_links": [
                {
                    "rel": "next",
                    "href": "https://servers.api.openstack.org/v2.1/servers/fc55acf4-3398-447b-8ef9-72a42086d775/meta?marker=ServiceType"
                }
            ],
            "links": [
                {
                    "rel": "self",
                    "href": "https://servers.api.openstack.org/v2.1/servers/fc55acf4-3398-447b-8ef9-72a42086d775"
                }
            ]
        }
    }
