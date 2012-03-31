The Volumes Extension
=================================================================
About this Extension
--------------------
This extension enables volume management on virtual servers. It is used with the OpenStack Compute 1.1 API to add or remove fixed IP addresses on named instances. 

To use this extension, you must have configured Compute to manage volumes.

.. Are there any pre-requisites prior to using it such as special hardware or configuration?

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://example.com/v1.1/tenant/extensions.

Extension Overview
~~~~~~~~~~~~~~~~~~

Name
	Volumes
	
Namespace
	http://docs.openstack.org/ext/volumes/api/v1.1

Alias
	OPS-VOL
	
Contact
	Name <justin@fathomdb.com>
	
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
	This extension enables listing of volumes available to virtual servers running in an OpenStack cloud. You can create, attach, and detach a volume with this extension.


Sample Query Responses
~~~~~~~~~~~~~~~~~~~~~~

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

   TBD

.. todo:: Provide example of XML query and response for volumes extension.

Extension Query Response: JSON::

    {"extensions": [{"updated": "2011-03-25T00:00:00+00:00", "name": "Volumes", "links": [], "namespace": "http://docs.openstack.org/ext/volumes/api/v1.1", "alias": "os-volumes", "description": "Volumes support"}]}


Document Change History
~~~~~~~~~~~~~~~~~~~~~~~

============= =====================================
Revision Date Summary of Changes
2011-09-14    Initial draft
2012-03-30    Reformat of content
============= =====================================


Summary of Changes
------------------
This extension to the Compute API allows volume management through the OpenStack Compute API.

This support is provided by the addition of new actions.

New Actions
~~~~~~~~~~~
This extension uses POST to attach or detach volumes to instances.

Normal Response Code: 202

Enter "None" if there are no changes to the sections below. 

Include the response codes, transitions if applicable, and XML and JSON examples.

New Faults
~~~~~~~~~~
None

New Headers
~~~~~~~~~~~
None

New Resources
~~~~~~~~~~~~~
None

New States
~~~~~~~~~~
None

Changes to the Cloud Servers Specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

List the specific changes to the API. For example:

In section 4.1.1 (List Servers) of the Cloud Servers Specification: Examples 4.1 and 4.2 should be replaced with Example 2.7 and Example 2.8 below.

Provide examples in XML and JSON
