About This Extension
====================
The config-drive extension enables attaching a separate drive to the Compute guest on instance create. It is used with the OpenStack Compute 1.1 API to write configuration data into guest for those guests whose root filesystems cannot be mounted by the Compute host.

To use this extension, you must have installed Compute, with libvirt or Xen using local disk.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://example.com/v1.1/tenant/extensions.

Extension Overview
------------------

Name
    Config Drive
	
Namespace
	http://docs.openstack.org/ext/config-drive/api/v1.1

Alias
	ORG-EXT
	
Contact
    Christopher MacGown <chris@pistoncloud.com>
	
Status
	Alpha
	
Extension Version
	v1.0 (2011-09-16)

Dependencies
    Compute API 1.1
	
Doc Link (PDF)
	http://
	
Doc Link (WADL)
	http://
	
Short Description
	This extension enables the assignment of config-drives to a
	compute guest on instance create running in an OpenStack cloud.

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

  TBD

.. todo:: Provide example of extension query XML response.

Extension Query Response: JSON::

  TBD

.. todo:: Provide example of extension query JSON response.


Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-09-16    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the OpenStack Compute API allows the addition of a configuration drive to an instance.

New Action
----------
None

New Faults
----------

None

New Headers
-----------
None

New Resources
-------------
This extension to the OpenStack Compute API adds the following resources:

A config_drive attribute to the servers API that is None by default, but can optionally be True or the imageRef of a config-drive image.

Upon instance create, a guest built with a True config_drive attribute will create a local volume and partition it as a fat32 drive, all passed in metadata, networks, and keys will be written to the config_drive which is associated as the last available disk on the instance.
Upon instance create, a guest built with an imageRef config_drive attribute will create a local volume from the image.

New States
----------

Changes to the Cloud Servers Specification
------------------------------------------

In section 4.1.2 (Create Servers) of the API Specification: Examples 4.3 and 4.4 should optionally add the config-drive attribute as in the below examples:


Example XML with config_drive attribute = True:

::

    <?xml version="1.0" encoding="UTF-8"?>
    <server xmlns="http://docs.openstack.org/compute/api/v1.1"
            imageRef="http://servers.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f6f006e54"
            flavorRef="52415800-8b69-11e0-9b19-734f1195ff37"
            name="new-server-test"
            config=drive="True"
            >
      <metadata>
        <meta key="My Server Name">Apache1</meta>
      </metadata>
      <personality>
        <file path="/etc/banner.txt">
            ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBp
            dCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5k
            IGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVs
            c2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4g
            QnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRo
            ZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlv
            dSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vy
            c2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6
            b25zLiINCg0KLVJpY2hhcmQgQmFjaA==
        </file>
      </personality>
    </server>

Example XML with config_drive attribute is an imageRef:

::

    <?xml version="1.0" encoding="UTF-8"?>
    <server xmlns="http://docs.openstack.org/compute/api/v1.1"
            imageRef="http://servers.api.openstack.org/1234/images/
    52415800-8b69-11e0-9b19-734f6f006e54"
            flavorRef="52415800-8b69-11e0-9b19-734f1195ff37"
            name="new-server-test"
            config_drive="http://servers.api.openstack.org/1234/images/52415800-8b69-1341-9b19-734f6f006e54"
            >
      <metadata>
        <meta key="My Server Name">Apache1</meta>
      </metadata>
      <personality>
        <file path="/etc/banner.txt">
            ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBp
            dCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5k
            IGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVs
            c2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4g
            QnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRo
            ZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlv
            dSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vy
            c2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6
            b25zLiINCg0KLVJpY2hhcmQgQmFjaA==
        </file>
      </personality>
    </server>


Example JSON with config_drive attribute is true:

::

    {
        "server" : {
            "name" : "new-server-test",
            "imageRef" : "http://servers.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f6f006e54",
            "flavorRef" : "52415800-8b69-11e0-9b19-734f1195ff37",
            "config_drive" : "true",
            "metadata" : {
                "My Server Name" : "Apache1"
            },
            "personality" : [
                {
                    "path" : "/etc/banner.txt",
                    "contents" : "ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBp
     dCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5k
     IGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVs
     c2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4g
     QnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRo
     ZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlv
     dSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vy
     c2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6
     b25zLiINCg0KLVJpY2hhcmQgQmFjaA=="
                }
            ]
        }
    }

Example JSON with config_drive attribute is an imageRef:

::

    {
        "server" : {
            "name" : "new-server-test",
            "imageRef" : "http://servers.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f6f006e54",
            "flavorRef" : "52415800-8b69-11e0-9b19-734f1195ff37",
            "config_drive" : "http://servers.api.openstack.org/1234/images/52415800-8b69-11e0-9b19-734f6f006e54",
            "metadata" : {
                "My Server Name" : "Apache1"
            },
            "personality" : [
                {
                    "path" : "/etc/banner.txt",
                    "contents" : "ICAgICAgDQoiQSBjbG91ZCBkb2VzIG5vdCBrbm93IHdoeSBp
     dCBtb3ZlcyBpbiBqdXN0IHN1Y2ggYSBkaXJlY3Rpb24gYW5k
     IGF0IHN1Y2ggYSBzcGVlZC4uLkl0IGZlZWxzIGFuIGltcHVs
     c2lvbi4uLnRoaXMgaXMgdGhlIHBsYWNlIHRvIGdvIG5vdy4g
     QnV0IHRoZSBza3kga25vd3MgdGhlIHJlYXNvbnMgYW5kIHRo
     ZSBwYXR0ZXJucyBiZWhpbmQgYWxsIGNsb3VkcywgYW5kIHlv
     dSB3aWxsIGtub3csIHRvbywgd2hlbiB5b3UgbGlmdCB5b3Vy
     c2VsZiBoaWdoIGVub3VnaCB0byBzZWUgYmV5b25kIGhvcml6
     b25zLiINCg0KLVJpY2hhcmQgQmFjaA=="
                }
            ]
        }
    }
