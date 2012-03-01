About The Security Groups Extension
===================================
The Security Groups extension lets you view, create, and remove security groups for instances plus set rules for security groups using the OpenStack Compute API 1.1.

.. Are there any pre-requisites prior to using it such as special hardware or configuration?

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://mycloud.com/v1.1/tenant/extensions.

Security Groups Extension Overview
----------------------------------

Name
	Security Groups
	
Namespace
	http://docs.openstack.org/ext/securitygroups/api/v1.1

Alias
	OPS-SCG
	
Contact
	Tushar Patil <tushar.vitthal.patil@gmail.com>
	
Status
	Released
	
Extension Version
	v1.0 (2011-08-11)

Dependencies
	Compute API 1.1
	
Doc Link (PDF)
	http://
	
Doc Link (WADL)
	http://
	
Short Description
	This extension enables creation and listing of security groups.

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

    HTTP/1.1 200 OK
    Content-Type: application/xml
    Content-Length: 3295
    Date: Fri, 16 Sep 2011 21:06:55 GMT

    <extensions xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1">
    <extension name="SecurityGroups" namespace="http://docs.openstack.org/ext/securitygroups/api/v1.1" alias="security_groups" updated="2011-07-21T00:00:00+00:00"><description>Security group support</description></extension>
    </extensions>

Extension Query Response: JSON::

    {"extensions": [{"updated": "2011-07-21T00:00:00+00:00", "name": "SecurityGroups", "links": [], "namespace": "http://docs.openstack.org/ext/securitygroups/api/v1.1", "alias": "security_groups", "description": "Security group support"}]}

Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-09-16    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the Compute API allows you to create, update, and delete security groups. 

To support these new actions, the extension also issues new (faults, headers, resources, states, you name it.)

New Actions
-----------
os-security-group

os-security-group-rules


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
