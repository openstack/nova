About The Virtual Interfaces Extension
======================================
The Virtual Interfaces extension lets you view the virtual interfaces used in an instance.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://mycloud.com/v1.1/tenant/extensions.

Virtual Interfaces Extension Overview
-------------------------------------

Name
	Virtual Interfaces
	
Namespace
	http://docs.openstack.org/ext/virtual_interfaces/api/v1.1

Alias
	MID-VRT
	
Contact
	Name <ryu@midokura.jp>
	
Status
	Alpha
	
Extension Version
	v1.0 (2011-08-18)

Dependencies
	Compute API 1.1
	
Doc Link (PDF)
	http://
	
Doc Link (WADL)
	http://
	
Short Description
	This extension enables Virtual Interfaces capabilities for OpenStack Compute servers so that you know the interfaces for the virtual instances running in the cloud. 

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

	<extensions>
	<extension name="VirtualInterfaces" 
	namespace="http://docs.openstack.org/ext/virtual_interfaces/api/v1.1" 
	alias="virtual_interfaces" updated="2011-08-17T00:00:00+00:00">
	<description>Virtual interface support</description>
	</extension>
	</extensions>

Extension Query Response: JSON::

{"extensions": [{"updated": "2011-08-17T00:00:00+00:00", "name": "VirtualInterfaces", "links": [], "namespace": "http://docs.openstack.org/ext/virtual_interfaces/api/v1.1", "alias": "virtual_interfaces", "description": "Virtual interface support"}]}

Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-09-16    Initial draft
============= =====================================

Summary of Changes
==================
This extension to the OpenStack Compute API enables listing of Virtual Interfaces of running instances.

New Actions
----------
virtual_interfaces

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
A new action added to the 4.3 Server Actions section. 

============= ==================
Verb          URI
POST          /servers/id/virtual_interfaces
============= ==================

Normal Response Code(s): 202

Error Response Code(s): computeFault (400, 500, …), serviceUnavailable (503), unauthorized (401), forbidden (403), badRequest (400), badMethod (405), overLimit (413), itemNotFound (404), badMediaType (415), buildInProgress (409) 
