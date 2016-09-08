====================
Links and references
====================

Often resources need to refer to other resources. For example, when
creating a server, you must specify the image from which to build the
server. You can specify the image by providing an ID or a URL to a
remote image. When providing an ID, it is assumed that the resource
exists in the current OpenStack deployment.

**Example: ID image reference: JSON request**

.. code::

    {
       "server":{
          "flavorRef":"http://openstack.example.com/openstack/flavors/1",
          "imageRef":"http://openstack.example.com/openstack/images/70a599e0-31e7-49b7-b260-868f441e862b",
          "metadata":{
             "My Server Name":"Apache1"
          },
          "name":"new-server-test",
          "personality":[
             {
                "contents":"ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBpdCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5kIGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVsc2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4gQnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRoZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlvdSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vyc2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6b25zLiINCg0KLVJpY2hhcmQgQmFjaA==",
                "path":"/etc/banner.txt"
             }
          ]
       }
    }


**Example: Full image reference: JSON request**

.. code::

    {
        "server": {
            "name": "server-test-1",
            "imageRef": "b5660a6e-4b46-4be3-9707-6b47221b454f",
            "flavorRef": "2",
            "max_count": 1,
            "min_count": 1,
            "networks": [
                {
                    "uuid": "d32019d3-bc6e-4319-9c1d-6722fc136a22"
                }
            ],
            "security_groups": [
                {
                    "name": "default"
                },
                {
                    "name": "another-secgroup-name"
                }
            ]
        }
    }


For convenience, resources contain links to themselves. This allows a
client to easily obtain rather than construct resource URIs. The
following types of link relations are associated with resources:

-  A ``self`` link contains a versioned link to the resource. Use these
   links when the link is followed immediately.

-  A ``bookmark`` link provides a permanent link to a resource that is
   appropriate for long term storage.

-  An ``alternate`` link can contain an alternate representation of the
   resource. For example, an OpenStack Compute image might have an
   alternate representation in the OpenStack Image service.

.. note:: The ``type`` attribute provides a hint as to the type of
   representation to expect when following the link.

**Example: Server with self links: JSON**

.. code::

    {
       "server":{
          "id":"52415800-8b69-11e0-9b19-734fcece0043",
          "name":"my-server",
          "links":[
             {
                "rel":"self",
                "href":"http://servers.api.openstack.org/v2.1/servers/52415800-8b69-11e0-9b19-734fcece0043"
             },
             {
                "rel":"bookmark",
                "href":"http://servers.api.openstack.org/servers/52415800-8b69-11e0-9b19-734fcece0043"
             }
          ]
       }
    }


**Example: Server with alternate link: JSON**

.. code::

    {
        "image" : {
            "id" : "52415800-8b69-11e0-9b19-734f5736d2a2",
            "name" : "My Server Backup",
            "links": [
                {
                    "rel" : "self",
                    "href" : "http://servers.api.openstack.org/v2.1/images/52415800-8b69-11e0-9b19-734f5736d2a2"
                },
                {
                    "rel" : "bookmark",
                    "href" : "http://servers.api.openstack.org/images/52415800-8b69-11e0-9b19-734f5736d2a2"
                },
                {
                    "rel"  : "alternate",
                    "type" : "application/vnd.openstack.image",
                    "href" : "http://glance.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f5736d2a2"
                }
            ]
        }
    }
