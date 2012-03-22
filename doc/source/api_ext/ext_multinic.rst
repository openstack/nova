About The Fixed IPs Extension
=============================
This extension enables addFixedIp and removeFixedIp actions on servers. It is used with the OpenStack Compute 1.1 API to add or remove fixed IP addresses on named instances. 

To use this extension, you must have configured Compute with more than one Network Interface Card.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://example.com/v1.1/tenant/extension.

Fixed IPs Extension Overview
----------------------------

Name
	Multinic
	
Namespace
	http://docs.openstack.org/ext/multinic/api/v1.1

Alias
	OPS-MLT
	
Contact
	Kevin Mitchell <kevin.mitchell@rackspace.com>
	
Status
	Alpha
	
Extension Version
	v1.0 (2011-09-14)

Dependencies
	Compute API 1.1
	
Doc Link (PDF)
	http://
	
Doc Link (WADL)
	http://
	
Short Description
	This extension enables the assignment and removal of fixed IP addresses on virtual servers running in an OpenStack Compute cloud.

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

	<extensions xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1">
	<extension name="Multinic" namespace="http://docs.openstack.org/ext/multinic/api/v1.1" alias="NMN" updated="2011-06-09T00:00:00+00:00"><description>Multiple network support</description></extension>
	</extensions>


Extension Query Response: JSON::

	{"extensions": [{"updated": "2011-06-09T00:00:00+00:00", "name": "Multinic", "links": [], "namespace": "http://docs.openstack.org/ext/multinic/api/v1.1", "alias": "NMN", "description": "Multiple network support"}]}

Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-09-14    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the Compute API allows addition and removal of fixed IP addresses to instances.

To support these new actions, the extension also issues new (faults, headers, resources, states, you name it.)

New Action
----------
This extension uses POST to add or remove fixed IP addresses to instances.

add_fixed_ip
remove_fixed_ip

Normal Response Code: 202

Enter "None" if there are no changes to the sections below. 

Include the response codes, transitions if applicable, and XML and JSON examples.

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

List the specific changes to the API. For example: 

In section 4.1.1 (List Servers) of the Cloud Servers Specification: Examples 4.1 and 4.2 should be replaced with Example 2.7 and Example 2.8 below. 

Provide examples in XML and JSON
