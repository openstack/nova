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
Get a list of DNS Domains (aka 'zones') published by the DNS driver:

        GET /v1.1/<tenant_id>/os-floating-ip-dns/

    # Sample Response:
    { 'zones' : [
      {'zone' : 'example.org'}
      {'zone' : 'example.net'}]}


Create a DNS entry:

        POST /v1.1/<tenant_id>/os-floating-ip-dns/

    # Sample body:
    { 'dns_entry' :
      { 'name': 'instance1',
        'ip': '192.168.53.11',
        'dns_type': 'A',
        'zone': 'example.org'}}

    # Sample Response (success):
    { 'dns_entry' :
      { 'ip' : '192.168.53.11',
        'type' : 'A',
        'zone' : 'example.org',
        'name' : 'instance1' }}

    Failure Response Code: 409 (indicates an entry with name & zone already exists.)


Change the ip address of an existing DNS entry:

        PUT /v1.1/<tenant_id>/os-floating-ip-dns/<domain>

    # Sample body:
    { 'dns_entry' :
      { 'name': 'instance1',
        'ip': '192.168.53.99'}}

    # Sample Response (success):
    { 'dns_entry' :
      { 'ip' : '192.168.53.99',
        'name' : 'instance1',
        'zone' : 'example.org'}}

    Failure Response Code: 404 (Entry to be modified not found)


Find DNS entries for a given domain and name:

        GET /v1.1/<tenant_id>/os-floating-ip-dns/<domain>?name=<name>

    # Sample Response:
    { 'dns_entries' : [
      { 'ip' : '192.168.53.11',
        'type' : 'A',
        'zone' : <domain>,
        'name' : <name> }]}


Find DNS entries for a given domain and ip:

        GET /v1.1/<tenant_id>/os-floating-ip-dns/<domain>/?ip=<ip>

    # Sample Response:
    { 'dns_entries' : [
      { 'ip' : <ip>,
        'type' : 'A',
        'zone' : <domain>,
        'name' : 'example1' }
      { 'ip' : <ip>,
        'type' : 'A',
        'zone' : <domain>,
        'name' : 'example2' }]}


Delete a DNS entry:

DELETE /v1.1/<tenant_id>/os-floating-ip-dns/<domain>?name=<name>

    Normal Response Code: 200
    Failure Response Code: 404 (Entry to be deleted not found)

New States
----------
None

Changes to the Cloud Servers Specification
------------------------------------------
None

