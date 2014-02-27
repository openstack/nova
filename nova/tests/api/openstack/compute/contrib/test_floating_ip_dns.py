# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from lxml import etree
import urllib
import webob

from nova.api.openstack.compute.contrib import floating_ip_dns
from nova import context
from nova import db
from nova import exception
from nova import network
from nova import test
from nova.tests.api.openstack import fakes


name = "arbitraryname"
name2 = "anotherarbitraryname"

test_ipv4_address = '10.0.0.66'
test_ipv4_address2 = '10.0.0.67'

test_ipv6_address = 'fe80:0:0:0:0:0:a00:42'

domain = "example.org"
domain2 = "example.net"
floating_ip_id = '1'


def _quote_domain(domain):
    """Domain names tend to have .'s in them.  Urllib doesn't quote dots,
    but Routes tends to choke on them, so we need an extra level of
    by-hand quoting here.  This function needs to duplicate the one in
    python-novaclient/novaclient/v1_1/floating_ip_dns.py
    """
    return urllib.quote(domain.replace('.', '%2E'))


def network_api_get_floating_ip(self, context, id):
    return {'id': floating_ip_id, 'address': test_ipv4_address,
            'fixed_ip': None}


def network_get_dns_domains(self, context):
    return [{'domain': 'example.org', 'scope': 'public'},
            {'domain': 'example.com', 'scope': 'public',
             'project': 'project1'},
            {'domain': 'private.example.com', 'scope': 'private',
             'availability_zone': 'avzone'}]


def network_get_dns_entries_by_address(self, context, address, domain):
    return [name, name2]


def network_get_dns_entries_by_name(self, context, address, domain):
    return [test_ipv4_address]


def network_add_dns_entry(self, context, address, name, dns_type, domain):
    return {'dns_entry': {'ip': test_ipv4_address,
                          'name': name,
                          'type': dns_type,
                          'domain': domain}}


def network_modify_dns_entry(self, context, address, name, domain):
    return {'dns_entry': {'name': name,
                          'ip': address,
                          'domain': domain}}


def network_create_private_dns_domain(self, context, domain, avail_zone):
    pass


def network_create_public_dns_domain(self, context, domain, project):
    pass


class FloatingIpDNSTest(test.TestCase):
    def _create_floating_ip(self):
        """Create a floating ip object."""
        host = "fake_host"
        db.floating_ip_create(self.context,
                              {'address': test_ipv4_address,
                              'host': host})
        db.floating_ip_create(self.context,
                              {'address': test_ipv6_address,
                              'host': host})

    def _delete_floating_ip(self):
        db.floating_ip_destroy(self.context, test_ipv4_address)
        db.floating_ip_destroy(self.context, test_ipv6_address)

    def setUp(self):
        super(FloatingIpDNSTest, self).setUp()
        self.stubs.Set(network.api.API, "get_dns_domains",
                       network_get_dns_domains)
        self.stubs.Set(network.api.API, "get_dns_entries_by_address",
                       network_get_dns_entries_by_address)
        self.stubs.Set(network.api.API, "get_dns_entries_by_name",
                       network_get_dns_entries_by_name)
        self.stubs.Set(network.api.API, "get_floating_ip",
                       network_api_get_floating_ip)
        self.stubs.Set(network.api.API, "add_dns_entry",
                       network_add_dns_entry)
        self.stubs.Set(network.api.API, "modify_dns_entry",
                       network_modify_dns_entry)
        self.stubs.Set(network.api.API, "create_public_dns_domain",
                       network_create_public_dns_domain)
        self.stubs.Set(network.api.API, "create_private_dns_domain",
                       network_create_private_dns_domain)

        self.context = context.get_admin_context()

        self._create_floating_ip()
        temp = floating_ip_dns.FloatingIPDNSDomainController()
        self.domain_controller = temp
        self.entry_controller = floating_ip_dns.FloatingIPDNSEntryController()

    def tearDown(self):
        self._delete_floating_ip()
        super(FloatingIpDNSTest, self).tearDown()

    def test_dns_domains_list(self):
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns')
        res_dict = self.domain_controller.index(req)
        entries = res_dict['domain_entries']
        self.assertTrue(entries)
        self.assertEqual(entries[0]['domain'], "example.org")
        self.assertFalse(entries[0]['project'])
        self.assertFalse(entries[0]['availability_zone'])
        self.assertEqual(entries[1]['domain'], "example.com")
        self.assertEqual(entries[1]['project'], "project1")
        self.assertFalse(entries[1]['availability_zone'])
        self.assertEqual(entries[2]['domain'], "private.example.com")
        self.assertFalse(entries[2]['project'])
        self.assertEqual(entries[2]['availability_zone'], "avzone")

    def _test_get_dns_entries_by_address(self, address):

        qparams = {'ip': address}
        params = "?%s" % urllib.urlencode(qparams) if qparams else ""

        req = fakes.HTTPRequest.blank(
            '/v2/123/os-floating-ip-dns/%s/entries/%s'
            % (_quote_domain(domain), params))
        entries = self.entry_controller.show(req, _quote_domain(domain),
                                             address)
        entries = entries.obj
        self.assertEqual(len(entries['dns_entries']), 2)
        self.assertEqual(entries['dns_entries'][0]['name'],
                         name)
        self.assertEqual(entries['dns_entries'][1]['name'],
                         name2)
        self.assertEqual(entries['dns_entries'][0]['domain'],
                         domain)

    def test_get_dns_entries_by_ipv4_address(self):
        self._test_get_dns_entries_by_address(test_ipv4_address)

    def test_get_dns_entries_by_ipv6_address(self):
        self._test_get_dns_entries_by_address(test_ipv6_address)

    def test_get_dns_entries_by_invalid_ipv4_or_ipv6(self):
        # If it's not a valid ipv4 neither ipv6, the method 'show'
        # will try to get dns entries by name instead. We use this
        # to test if address is being correctly validated.
        def fake_get_dns_entries_by_name(self, context, address, domain):
            raise webob.exc.HTTPUnprocessableEntity()

        self.stubs.Set(network.api.API, "get_dns_entries_by_name",
                       fake_get_dns_entries_by_name)

        invalid_addr = '333.333.333.333'

        qparams = {'ip': invalid_addr}
        params = "?%s" % urllib.urlencode(qparams) if qparams else ""

        req = fakes.HTTPRequest.blank(
            '/v2/123/os-floating-ip-dns/%s/entries/%s'
            % (_quote_domain(domain), params))

        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.entry_controller.show,
                          req, _quote_domain(domain), invalid_addr)

    def test_get_dns_entries_by_name(self):
        req = fakes.HTTPRequest.blank(
              '/v2/123/os-floating-ip-dns/%s/entries/%s' %
              (_quote_domain(domain), name))
        entry = self.entry_controller.show(req, _quote_domain(domain), name)

        self.assertEqual(entry['dns_entry']['ip'],
                         test_ipv4_address)
        self.assertEqual(entry['dns_entry']['domain'],
                         domain)

    def test_dns_entries_not_found(self):
        def fake_get_dns_entries_by_name(self, context, address, domain):
            raise webob.exc.HTTPNotFound()

        self.stubs.Set(network.api.API, "get_dns_entries_by_name",
                       fake_get_dns_entries_by_name)

        req = fakes.HTTPRequest.blank(
              '/v2/123/os-floating-ip-dns/%s/entries/%s' %
              (_quote_domain(domain), 'nonexistent'))
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.entry_controller.show,
                          req, _quote_domain(domain), 'nonexistent')

    def test_create_entry(self):
        body = {'dns_entry':
                 {'ip': test_ipv4_address,
                  'dns_type': 'A'}}
        req = fakes.HTTPRequest.blank(
              '/v2/123/os-floating-ip-dns/%s/entries/%s' %
              (_quote_domain(domain), name))
        entry = self.entry_controller.update(req, _quote_domain(domain),
                                             name, body)
        self.assertEqual(entry['dns_entry']['ip'], test_ipv4_address)

    def test_create_domain(self):
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s' %
                                      _quote_domain(domain))
        body = {'domain_entry':
                {'scope': 'private',
                 'project': 'testproject'}}
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.domain_controller.update,
                          req, _quote_domain(domain), body)

        body = {'domain_entry':
                {'scope': 'public',
                 'availability_zone': 'zone1'}}
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.domain_controller.update,
                          req, _quote_domain(domain), body)

        body = {'domain_entry':
                {'scope': 'public',
                 'project': 'testproject'}}
        entry = self.domain_controller.update(req, _quote_domain(domain), body)
        self.assertEqual(entry['domain_entry']['domain'], domain)
        self.assertEqual(entry['domain_entry']['scope'], 'public')
        self.assertEqual(entry['domain_entry']['project'], 'testproject')

        body = {'domain_entry':
                {'scope': 'private',
                 'availability_zone': 'zone1'}}
        entry = self.domain_controller.update(req, _quote_domain(domain), body)
        self.assertEqual(entry['domain_entry']['domain'], domain)
        self.assertEqual(entry['domain_entry']['scope'], 'private')
        self.assertEqual(entry['domain_entry']['availability_zone'], 'zone1')

    def test_delete_entry(self):
        calls = []

        def network_delete_dns_entry(fakeself, context, name, domain):
            calls.append((name, domain))

        self.stubs.Set(network.api.API, "delete_dns_entry",
                       network_delete_dns_entry)

        req = fakes.HTTPRequest.blank(
              '/v2/123/os-floating-ip-dns/%s/entries/%s' %
              (_quote_domain(domain), name))
        res = self.entry_controller.delete(req, _quote_domain(domain), name)

        self.assertEqual(202, res.status_int)
        self.assertEqual([(name, domain)], calls)

    def test_delete_entry_notfound(self):
        def delete_dns_entry_notfound(fakeself, context, name, domain):
            raise exception.NotFound

        self.stubs.Set(network.api.API, "delete_dns_entry",
                       delete_dns_entry_notfound)

        req = fakes.HTTPRequest.blank(
              '/v2/123/os-floating-ip-dns/%s/entries/%s' %
              (_quote_domain(domain), name))
        self.assertRaises(webob.exc.HTTPNotFound,
            self.entry_controller.delete, req, _quote_domain(domain), name)

    def test_delete_domain(self):
        calls = []

        def network_delete_dns_domain(fakeself, context, fqdomain):
            calls.append(fqdomain)

        self.stubs.Set(network.api.API, "delete_dns_domain",
                       network_delete_dns_domain)

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s' %
                                      _quote_domain(domain))
        res = self.domain_controller.delete(req, _quote_domain(domain))

        self.assertEqual(202, res.status_int)
        self.assertEqual([domain], calls)

    def test_delete_domain_notfound(self):
        def delete_dns_domain_notfound(fakeself, context, fqdomain):
            raise exception.NotFound

        self.stubs.Set(network.api.API, "delete_dns_domain",
                       delete_dns_domain_notfound)

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s' %
                                      _quote_domain(domain))
        self.assertRaises(webob.exc.HTTPNotFound,
            self.domain_controller.delete, req, _quote_domain(domain))

    def test_modify(self):
        body = {'dns_entry':
                 {'ip': test_ipv4_address2,
                  'dns_type': 'A'}}
        req = fakes.HTTPRequest.blank(
              '/v2/123/os-floating-ip-dns/%s/entries/%s' % (domain, name))
        entry = self.entry_controller.update(req, domain, name, body)

        self.assertEqual(entry['dns_entry']['ip'], test_ipv4_address2)


class FloatingIpDNSSerializerTest(test.TestCase):
    def test_domains(self):
        serializer = floating_ip_dns.DomainsTemplate()
        text = serializer.serialize(dict(
                domain_entries=[
                    dict(domain=domain, scope='public', project='testproject'),
                    dict(domain=domain2, scope='private',
                         availability_zone='avzone')]))

        tree = etree.fromstring(text)
        self.assertEqual('domain_entries', tree.tag)
        self.assertEqual(2, len(tree))
        self.assertEqual(domain, tree[0].get('domain'))
        self.assertEqual(domain2, tree[1].get('domain'))
        self.assertEqual('avzone', tree[1].get('availability_zone'))

    def test_domain_serializer(self):
        serializer = floating_ip_dns.DomainTemplate()
        text = serializer.serialize(dict(
                domain_entry=dict(domain=domain,
                                  scope='public',
                                  project='testproject')))

        tree = etree.fromstring(text)
        self.assertEqual('domain_entry', tree.tag)
        self.assertEqual(domain, tree.get('domain'))
        self.assertEqual('testproject', tree.get('project'))

    def test_entries_serializer(self):
        serializer = floating_ip_dns.FloatingIPDNSsTemplate()
        text = serializer.serialize(dict(
                dns_entries=[
                    dict(ip=test_ipv4_address,
                         type='A',
                         domain=domain,
                         name=name),
                    dict(ip=test_ipv4_address2,
                         type='C',
                         domain=domain,
                         name=name2)]))

        tree = etree.fromstring(text)
        self.assertEqual('dns_entries', tree.tag)
        self.assertEqual(2, len(tree))
        self.assertEqual('dns_entry', tree[0].tag)
        self.assertEqual('dns_entry', tree[1].tag)
        self.assertEqual(test_ipv4_address, tree[0].get('ip'))
        self.assertEqual('A', tree[0].get('type'))
        self.assertEqual(domain, tree[0].get('domain'))
        self.assertEqual(name, tree[0].get('name'))
        self.assertEqual(test_ipv4_address2, tree[1].get('ip'))
        self.assertEqual('C', tree[1].get('type'))
        self.assertEqual(domain, tree[1].get('domain'))
        self.assertEqual(name2, tree[1].get('name'))

    def test_entry_serializer(self):
        serializer = floating_ip_dns.FloatingIPDNSTemplate()
        text = serializer.serialize(dict(
                dns_entry=dict(
                    ip=test_ipv4_address,
                    type='A',
                    domain=domain,
                    name=name)))

        tree = etree.fromstring(text)

        self.assertEqual('dns_entry', tree.tag)
        self.assertEqual(test_ipv4_address, tree.get('ip'))
        self.assertEqual(domain, tree.get('domain'))
        self.assertEqual(name, tree.get('name'))
