About The Rescue Extension
==========================

The rescue extension lets you put a server into a "rescue" status when the virtual instance will be replaced with a "rescue" image and have its existing drive attached as a second disk so that a root user can log in and troubleshoot problems with the virtual server.

To put a server into "rescue" state, you do not have to be an administrator. The only requirement is that the base image used to build your instance must still be available.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://mycloud.com/v1.1/tenant/extensions.

Rescue Extension Overview
-------------------------

Name
	Rescue
	
Namespace
	http://docs.openstack.org/ext/rescue/api/v1.1

Alias
	OPS-RES
	
Contact
	Josh Kearney <josh@jk0.org>
	
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
	This extension enables rescue capabilities for OpenStack Compute servers so that virtual instances running in the cloud may be put in a rescue status. 

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::
N/A

Extension Query Response: JSON::

{"extensions": [{"updated": "2011-08-18T00:00:00+00:00", "name": "Rescue", "links": [], "namespace": "http://docs.openstack.org/ext/rescue/api/v1.1", "alias": "os-rescue", "description": "Instance rescue mode"}]}

Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-09-16    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the OpenStack Compute API enables rescue of running instances.

To support these new actions, the extension also issues new states.

New Actions
-----------
rescue
unrescue

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
RESCUING
UNRESCUING

Changes to the Cloud Servers Specification
------------------------------------------
A new action added to the 4.3 Server Actions section. 

Rescue Server
+++++++++++++

============= ==================
Verb          URI
POST          /servers/id/rescue
============= ==================

Normal Response Code(s): 202

Error Response Code(s): computeFault (400, 500, …), serviceUnavailable (503), unauthorized (401), forbidden (403), badRequest (400), badMethod (405), overLimit (413), itemNotFound (404), badMediaType (415), buildInProgress (409) 

Status Transition: 	ACTIVE -> RESCUING -> ACTIVE

This operation places the server into RESCUING status. 
