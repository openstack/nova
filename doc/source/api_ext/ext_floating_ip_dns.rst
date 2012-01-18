About The Floating IP DNS Extension
================================
The Floating IP DNS extension provides an interface for managing DNS records associated with IP addresses
allocated by the Floating Ips extension.  Requests are dispatched to a DNS driver selected at startup.

To obtain current information the extensions available to you, issue an EXTENSION query on the OpenStack system where it is installed, such as http://mycloud.com/v1.1/tenant/extension.

Floating IPs Extension Overview
-------------------------------

Name
        Floating IP DNS

Namespace
        http://docs.openstack.org/ext/floating_ip_dns/api/v1.1

Alias
        OPS-DNS

Contact
        Andrew Bogott <abogott@wikimedia.org>

Status
        Alpha

Extension Version
        v1.0 (2011-12-22)

Dependencies
        Compute API v1.1
        Floating IPs Extension, v1.0

Doc Link (PDF)
        http://

Doc Link (WADL)
        http://

Short Description
        This extension enables associated DNS entries with floating IPs.

Sample Query Responses
----------------------

As shown below, responses to an EXTENSION query in XML or JSON provide basic information about the extension.

Extension Query Response: XML::

        None

Extension Query Response: JSON::

        {'extensions':
        [{'updated': '2011-12-23T00:00:00+00:00',
        'name': 'Floating_ip_dns',
        'links': [],
        'namespace': 'http://docs.openstack.org/ext/floating_ip_dns/api/v1.1',
        'alias': 'os-floating-ip_dns',
        'description': 'Floating IP DNS support'}]}

Document Change History
-----------------------

============= =====================================
Revision Date Summary of Changes
2011-12-23    Initial draft
============= =====================================


Summary of Changes
==================
This extension to the Compute API enables management of DNS entries for floating IP addresses.

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
Get a list of registered DNS Domains published by the DNS drivers:

        GET /v1.1/<tenant_id>/os-floating-ip-dns/

    # Sample Response:
    {'domain_entries' : [
      {'domain': 'domain1.example.org', 'scope': 'public', 'project': 'proj1'}
      {'domain': 'domain2.example.net', 'scope': 'public', 'project': 'proj2'}
      {'domain': 'example.net', 'scope': 'public', 'project': ''}
      {'domain': 'example.internal', 'scope': 'private', 'availability_zone': 'zone1'}]}


Create or modify a DNS domain:

        PUT /v1.1/<tenant_id>/os-floating-ip-dns/<domain>

    # Sample body, public domain:
     {'domain_entry' :
       {'scope': 'public',
        'project' : 'project1'}}

    # Sample body, public (projectless) domain:
     {'domain_entry' :
       {'scope': 'public'}}

    # Sample Response, public domain (success):
     {'domain_entry' :
       {'domain': 'domain1.example.org',
        'scope': 'public',
        'project': 'project1'}}

    # Sample body, private domain:
     {'domain_entry' :
       {'scope': 'private',
        'availability_domain': 'zone1'}}

    # Sample Response, private domain (success):
     {'domain_entry' :
       {'domain': 'domain1.private',
        'scope': 'private',
        'availability_zone': 'zone1'}}

    Failure Response Code: 403 (Insufficient permissions.)


Delete a DNS domain and all associated host entries:

DELETE /v1.1/<tenant_id>/os-floating-ip-dns/<domain>

    Normal Response Code: 200
    Failure Response Code: 404 (Domain to be deleted not found.)
    Failure Response Code: 403 (Insufficient permissions to delete.)


Create or modify a DNS entry:

        PUT /v1.1/<tenant_id>/os-floating-ip-dns/<domain>/entries/<name>

    # Sample body:
    { 'dns_entry' :
      { 'ip': '192.168.53.11',
        'dns_type': 'A' }}

    # Sample Response (success):
    { 'dns_entry' :
      { 'type' : 'A',
        'name' : 'instance1' }}


Find unique DNS entry for a given domain and name:

        GET /v1.1/<tenant_id>/os-floating-ip-dns/<domain>/entries/<name>

    # Sample Response:
    { 'dns_entry' :
      { 'ip' : '192.168.53.11',
        'type' : 'A',
        'domain' : <domain>,
        'name' : <name> }}


Find DNS entries for a given domain and ip:

        GET /v1.1/<tenant_id>/os-floating-ip-dns/<domain>/entries?ip=<ip>

    # Sample Response:
    { 'dns_entries' : [
      { 'ip' : <ip>,
        'type' : 'A',
        'domain' : <domain>,
        'name' : 'example1' }
      { 'ip' : <ip>,
        'type' : 'A',
        'domain' : <domain>,
        'name' : 'example2' }]}


Delete a DNS entry:

DELETE /v1.1/<tenant_id>/os-floating-ip-dns/<domain>/entries/<name>

    Normal Response Code: 200
    Failure Response Code: 404 (Entry to be deleted not found)


New States
----------
None

Changes to the Cloud Servers Specification
------------------------------------------
None
