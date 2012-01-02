# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
# All Rights Reserved.
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

import sys

from lxml import etree
import webob
import urllib

from nova.api.openstack.v2.contrib import floating_ips
from nova.api.openstack.v2.contrib import floating_ip_dns
from nova import context
from nova import db
from nova import network
from nova import rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


name = "arbitraryname"
name2 = "anotherarbitraryname"

testaddress = '10.0.0.66'
testaddress2 = '10.0.0.67'

zone = "example.org"
zone2 = "example.net"
floating_ip_id = '1'


def _quote_zone(zone):
    """
    Zone names tend to have .'s in them.  Urllib doesn't quote dots,
    but Routes tends to choke on them, so we need an extra level of
    by-hand quoting here.  This function needs to duplicate the one in
    python-novaclient/novaclient/v1_1/floating_ip_dns.py
    """
    return urllib.quote(zone.replace('.', '%2E'))


def network_api_get_floating_ip(self, context, id):
    return {'id': floating_ip_id, 'address': testaddress,
            'fixed_ip': None}


def network_get_dns_zones(self, context):
    return ['foo', 'bar', 'baz', 'quux']


def network_get_dns_entries_by_address(self, context, address, zone):
    return [name, name2]


def network_get_dns_entries_by_name(self, context, address, zone):
    return [testaddress, testaddress2]


def network_add_dns_entry(self, context, address, name, dns_type, zone):
    return {'dns_entry': {'ip': testaddress,
                          'name': name,
                          'type': dns_type,
                          'zone': zone}}


def network_modify_dns_entry(self, context, address, name, zone):
    return {'dns_entry': {'name': name,
                          'ip': address,
                          'zone': zone}}


class FloatingIpDNSTest(test.TestCase):
    def _create_floating_ip(self):
        """Create a floating ip object."""
        host = "fake_host"
        return db.floating_ip_create(self.context,
                                     {'address': testaddress,
                                      'host': host})

    def _delete_floating_ip(self):
        db.floating_ip_destroy(self.context, testaddress)

    def setUp(self):
        super(FloatingIpDNSTest, self).setUp()
        self.stubs.Set(network.api.API, "get_dns_zones",
                       network_get_dns_zones)
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

        self.context = context.get_admin_context()

        self._create_floating_ip()
        self.dns_controller = floating_ip_dns.FloatingIPDNSController()

    def tearDown(self):
        self._delete_floating_ip()
        super(FloatingIpDNSTest, self).tearDown()

    def test_dns_zones_list(self):
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns')
        res_dict = self.dns_controller.index(req)
        entries = res_dict['zones']
        self.assertTrue(entries)
        self.assertEqual(entries[0]['zone'], "foo")
        self.assertEqual(entries[1]['zone'], "bar")
        self.assertEqual(entries[2]['zone'], "baz")
        self.assertEqual(entries[3]['zone'], "quux")

    def test_get_dns_entries_by_address(self):
        qparams = {'ip': testaddress}
        params = "?%s" % urllib.urlencode(qparams) if qparams else ""

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s%s' %
                                      (_quote_zone(zone), params))
        entries = self.dns_controller.show(req, _quote_zone(zone))

        self.assertEqual(len(entries['dns_entries']), 2)
        self.assertEqual(entries['dns_entries'][0]['name'],
                         name)
        self.assertEqual(entries['dns_entries'][1]['name'],
                         name2)
        self.assertEqual(entries['dns_entries'][0]['zone'],
                         zone)

    def test_get_dns_entries_by_name(self):
        qparams = {'name': name}
        params = "?%s" % urllib.urlencode(qparams) if qparams else ""

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s%s' %
                                      (_quote_zone(zone), params))
        entries = self.dns_controller.show(req, _quote_zone(zone))

        self.assertEqual(len(entries['dns_entries']), 2)
        self.assertEqual(entries['dns_entries'][0]['ip'],
                         testaddress)
        self.assertEqual(entries['dns_entries'][1]['ip'],
                         testaddress2)
        self.assertEqual(entries['dns_entries'][0]['zone'],
                         zone)

    def test_create(self):
        body = {'dns_entry':
                 {'name': name,
                  'ip': testaddress,
                  'dns_type': 'A',
                  'zone': zone}}
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns')
        entry = self.dns_controller.create(req, body)

        self.assertEqual(entry['dns_entry']['ip'], testaddress)

    def test_delete(self):
        self.called = False
        self.deleted_zone = ""
        self.deleted_name = ""

        def network_delete_dns_entry(fakeself, context, req, id):
            self.called = True
            self.deleted_zone = id

        self.stubs.Set(network.api.API, "delete_dns_entry",
                       network_delete_dns_entry)

        qparams = {'name': name}
        params = "?%s" % urllib.urlencode(qparams) if qparams else ""

        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s%s' %
                                      (_quote_zone(zone), params))
        entries = self.dns_controller.delete(req, _quote_zone(zone))

        self.assertTrue(self.called)
        self.assertEquals(self.deleted_zone, zone)

    def test_modify(self):
        body = {'dns_entry':
                 {'name': name,
                  'ip': testaddress2}}
        req = fakes.HTTPRequest.blank('/v2/123/os-floating-ip-dns/%s' %
                                      zone)
        entry = self.dns_controller.update(req, zone, body)

        self.assertEqual(entry['dns_entry']['ip'], testaddress2)


class FloatingIpDNSSerializerTest(test.TestCase):
    def test_default_serializer(self):
        serializer = floating_ip_dns.FloatingIPDNSTemplate()
        text = serializer.serialize(dict(
                dns_entry=dict(
                    ip=testaddress,
                    type='A',
                    zone=zone,
                    name=name)))

        tree = etree.fromstring(text)

        self.assertEqual('dns_entry', tree.tag)
        self.assertEqual(testaddress, tree.get('ip'))
        self.assertEqual(zone, tree.get('zone'))
        self.assertEqual(name, tree.get('name'))

    def test_index_serializer(self):
        serializer = floating_ip_dns.ZonesTemplate()
        text = serializer.serialize(dict(
                zones=[
                    dict(zone=zone),
                    dict(zone=zone2)]))

        tree = etree.fromstring(text)
        self.assertEqual('zones', tree.tag)
        self.assertEqual(2, len(tree))
        self.assertEqual(zone, tree[0].get('zone'))
        self.assertEqual(zone2, tree[1].get('zone'))

    def test_show_serializer(self):
        serializer = floating_ip_dns.FloatingIPDNSsTemplate()
        text = serializer.serialize(dict(
                dns_entries=[
                    dict(ip=testaddress,
                         type='A',
                         zone=zone,
                         name=name),
                    dict(ip=testaddress2,
                         type='C',
                         zone=zone,
                         name=name2)]))

        tree = etree.fromstring(text)
        self.assertEqual('dns_entries', tree.tag)
        self.assertEqual(2, len(tree))
        self.assertEqual('dns_entry', tree[0].tag)
        self.assertEqual('dns_entry', tree[1].tag)
        self.assertEqual(testaddress, tree[0].get('ip'))
        self.assertEqual('A', tree[0].get('type'))
        self.assertEqual(zone, tree[0].get('zone'))
        self.assertEqual(name, tree[0].get('name'))
        self.assertEqual(testaddress2, tree[1].get('ip'))
        self.assertEqual('C', tree[1].get('type'))
        self.assertEqual(zone, tree[1].get('zone'))
        self.assertEqual(name2, tree[1].get('name'))
