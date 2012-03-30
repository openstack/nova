The Quotas Extension
=================================================================
About this Extension
--------------------
The quotas extension enables limiters placed on the resources used per tenant (project) for virtual instances. It is used with the OpenStack Compute API 1.1 for administrators who need to control the amount of volumes, memory, floating IP addresses, instances, or cores allowed within a defined tenant or project.

To use this extension, you need to have administrative rights to the tenants upon which you are placing quotas.
.. Are there any pre-requisites prior to using it such as special hardware or configuration?

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://example.com/v1.1/tenant/extensions.

Extension Overview
~~~~~~~~~~~~~~~~~~
Name
	Quotas
	
Namespace
	http://docs.openstack.org/ext/quotas-sets/api/v1.1

Alias
	OPS-QUO
	
Contact
	Name <jake@markupisart.com>
	
Status
	Alpha
	
Extension Version
	v1.0 (2011-08-16)

Dependencies
	Compute API 1.1
	
Doc Link (PDF)
	http://
	
Doc Link (WADL)
	http://
	
Short Description
	This extension enables quota management for OpenStack Compute servers so that resources for virtual instances are properly managed.

Sample Query Responses
~~~~~~~~~~~~~~~~~~~~~~

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

    TBD

.. todo:: Provide example of extension query XML response.

Extension Query Response: JSON::

{"extensions": [{"updated": "2011-08-08T00:00:00+00:00", "name": "Quotas", "links": [], "namespace": "http://docs.openstack.org/ext/quotas-sets/api/v1.1", "alias": "os-quota-sets", "description": "Quotas management support"}]}

Document Change History
~~~~~~~~~~~~~~~~~~~~~~~

============= =====================================
Revision Date Summary of Changes
2011-09-14    Initial draft
2012-03-30    Reformat of content
============= =====================================


Summary of Changes
------------------
This extension to the OpenStack Compute API allows administrators to control quotas for tenants (formerly known as projects).

This support is provided by the addition of new <actions, faults, headers, resources, states, something else>.

New Actions
~~~~~~~~~~~
List the actions each in a section. Enter "None" if there are no changes.

Include the response codes, transitions if applicable, and XML and JSON examples.

New Faults
~~~~~~~~~~

New Headers
~~~~~~~~~~~

New Resources
~~~~~~~~~~~~~

New States
~~~~~~~~~~

Changes to the Cloud Servers Specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

List the specific changes to the API. For example:

In section 4.1.1 (List Servers) of the Cloud Servers Specification: Examples 4.1 and 4.2 should be replaced with Example 2.7 and Example 2.8 below.

Provide examples in XML and JSON
