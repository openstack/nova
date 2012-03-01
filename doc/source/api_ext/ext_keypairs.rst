About The Keypairs Extension
============================
This extension enables you to create or import a keypair on a virtual instance. If you send the name of the instance to the API, you get a key and a private_key and fingerprint returned. You can also send a public_key to add an existing ssh key and also list the keypairs in use on instances.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://mycloud.com/v1.1/tenant/extensions.

Keypairs Extension Overview
---------------------------

Name
	Keypairs
	
Namespace
	http://docs.openstack.org/ext/keypairs/api/v1.1

Alias
	OPS-KYP
	
Contact
	Jesse Andrews <anotherjesse@gmail.com>
	
Status
	Released
	
Extension Version
	v1.0 (2011-08-09)

Dependencies
	Compute API 1.1
	
Doc Link (PDF)
	http://
	
Doc Link (WADL)
	http://
	
Short Description
	This extension enables keypair listing, creation, or import into an instance through a REST API.

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

    TBD

.. todo:: Provide example of extension query XML response.

Extension Query Response: JSON::

	{"extensions": [{"updated": "2011-08-08T00:00:00+00:00", "name": "Keypairs", "links": [], "namespace": "http://docs.openstack.org/ext/keypairs/api/v1.1", "alias": "os-keypairs", "description": "Keypair Support"}]}

Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-09-16    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the Compute API allows keypair support so that you can create or import keypairs to secure your running instances. You can also list keypairs per user. 

New Action
----------
When launching a new server, you can specify an already existing keypair with::

	POST /v1.1/tenant_id/os_keypairs/keypair

To lists the keypairs on all running instances, use::

	GET /v1.1/tenant_id/os_keypairs

New Faults
----------
None

New Headers
-----------
None

New Resources
-------------
None

New States
----------
None

Changes to the Cloud Servers Specification
------------------------------------------

This section lists the specific changes to the Compute API, namely adding a new section to the 4.3 Server Actions section. 
