The Floating IPs Extension
=================================================================
About this Extension
--------------------
The Floating IPs extension enables assigning and allocation of floating IP addresses to instances running in an OpenStack cloud. It is used with the OpenStack Compute 1.1 API to add or remove floating IP addresses on named instances. 

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://example.com/v1.1/tenant/extension.

Extension Overview
~~~~~~~~~~~~~~~~~~

Name
	Floating IPs
	
Namespace
	http://docs.openstack.org/ext/floating_ips/api/v1.1

Alias
	OPS-FLO
	
Contact
	Anthony Young <sleepsonthefloor@gmail.com>
	
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
	This extension enables assigning floating IP addresses to instances.

Sample Query Responses
~~~~~~~~~~~~~~~~~~~~~~

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension. 

Extension Query Response: XML::

	None

Extension Query Response: JSON::

	{"extensions": 
	[{"updated": "2011-06-16T00:00:00+00:00", 
	"name": "Floating_ips", 
	"links": [], 
	"namespace": "http://docs.openstack.org/ext/floating_ips/api/v1.1", 
	"alias": "os-floating-ips", 
	"description": "Floating IPs support"}]}

Document Change History
~~~~~~~~~~~~~~~~~~~~~~~

============= =====================================
Revision Date Summary of Changes
2011-09-14    Initial draft
2012-03-30    Reformat of content
============= =====================================


Summary of Changes
------------------
This extension to the Compute API enables support for floating IP addresses.

This support is provided by the addition of new actions and resources.

New Actions
~~~~~~~~~~~
This extension uses POST to add or remove floating IP addresses to instances.

Normal Response Code: 202

addFloatingIp

removeFloatingIp

Include the response codes, transitions if applicable, and XML and JSON examples.

New Faults
~~~~~~~~~~
None

New Headers
~~~~~~~~~~~
None

New Resources
~~~~~~~~~~~~~
This extension provides an os-floating-ips resource extension to do the following:

List a tenant's floating ips::

	GET /v1.1/tenant_id/os-floating-ips/

    # Sample Response:
    { "floating_ips" : [ { "fixed_ip" : "10.0.0.3",
            "id" : 1,
            "instance_id" : 1,
            "ip" : "10.6.0.0"
          },
          { "fixed_ip" : null,
            "id" : 2,
            "instance_id" : null,
            "ip" : "10.6.0.1"
          }
        ] }

    Normal Response Code: 200

Allocate a floating ip to a tenant::

	POST /v1.1/tenant_id/os-floating-ips/

    # Sample Response:
    { "floating_ip" : { "fixed_ip" : "10.0.0.3",
            "id" : 1,
            "instance_id" : 1,
            "ip" : "10.6.0.0"
        }}

    If there are no floating ips available, 400 will be returned, with a 
    message indicating that no more floating ips are available


De-allocate a floating ip from a tenant::

	DELETE /v1.1/tenant_id/os-floating-ips/id

    Normal Response Code: 202

Show a floating ip::

	GET /v1.1/tenant_id/os-floating-ips/id

    # Sample Response:
    { "floating_ip" : { "fixed_ip" : "10.0.0.3",
            "id" : 1,
            "instance_id" : 1,
            "ip" : "10.6.0.0"
        }}

    Normal Response Code: 200

New States
~~~~~~~~~~
None

Changes to the Cloud Servers Specification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

List the specific changes to the API. For example: 

In the List Addresses section of the Cloud Servers Specification: Examples 4.21 and 4.22 should be replaced with examples below. 

Provide examples in XML and JSON
