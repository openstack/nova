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

import mock
from six.moves import urllib
import webob

from nova.api.openstack.compute import floating_ip_dns \
        as fipdns_v21
from nova import context
from nova import db
from nova import exception
from nova import network
from nova import test
from nova.tests.unit.api.openstack import fakes


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
    return urllib.parse.quote(domain.replace('.', '%2E'))


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


class FloatingIpDNSTestV21(test.TestCase):
    floating_ip_dns = fipdns_v21

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

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_code)

    def _bad_request(self):
        return webob.exc.HTTPBadRequest

    def setUp(self):
        super(FloatingIpDNSTestV21, self).setUp()
        # None of these APIs are implemented for Neutron.
        self.flags(use_neutron=False)
        self.stub_out("nova.network.api.API.get_dns_domains",
                      network_get_dns_domains)
        self.stub_out("nova.network.api.API.get_dns_entries_by_address",
                      network_get_dns_entries_by_address)
        self.stub_out("nova.network.api.API.get_dns_entries_by_name",
                      network_get_dns_entries_by_name)
        self.stub_out("nova.network.api.API.get_floating_ip",
                      network_api_get_floating_ip)
        self.stub_out("nova.network.api.API.add_dns_entry",
                      network_add_dns_entry)
        self.stub_out("nova.network.api.API.modify_dns_entry",
                      network_modify_dns_entry)
        self.stub_out("nova.network.api.API.create_public_dns_domain",
                      network_create_public_dns_domain)
        self.stub_out("nova.network.api.API.create_private_dns_domain",
                      network_create_private_dns_domain)

        self.context = context.get_admin_context()

        self._create_floating_ip()
        temp = self.floating_ip_dns.FloatingIPDNSDomainController()
        self.domain_controller = temp
        self.entry_controller = self.floating_ip_dns.\
                                FloatingIPDNSEntryController()
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.req = fakes.HTTPRequest.blank('')

    def tearDown(self):
        self._delete_floating_ip()
        super(FloatingIpDNSTestV21, self).tearDown()

    def test_dns_domains_list(self):
        res_dict = self.domain_controller.index(self.req)
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

        entries = self.entry_controller.show(self.req, _quote_domain(domain),
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

    def test_get_dns_entries_by_name(self):
        entry = self.entry_controller.show(self.req, _quote_domain(domain),
                                           name)

        self.assertEqual(entry['dns_entry']['ip'],
                         test_ipv4_address)
        self.assertEqual(entry['dns_entry']['domain'],
                         domain)

    @mock.patch.object(network.api.API, "get_dns_entries_by_name",
                       side_effect=webob.exc.HTTPNotFound())
    def test_dns_entries_not_found(self, mock_get_entries):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.entry_controller.show,
                          self.req, _quote_domain(domain), 'nonexistent')
        self.assertTrue(mock_get_entries.called)

    def test_create_entry(self):
        body = {'dns_entry':
                 {'ip': test_ipv4_address,
                  'dns_type': 'A'}}
        entry = self.entry_controller.update(self.req, _quote_domain(domain),
                                             name, body=body)
        self.assertEqual(entry['dns_entry']['ip'], test_ipv4_address)

    def test_create_domain(self):
        self._test_create_domain(self.req)

    def _test_create_domain(self, req):
        body = {'domain_entry':
                {'scope': 'private',
                 'project': 'testproject'}}
        self.assertRaises(self._bad_request(),
                          self.domain_controller.update, req,
                          _quote_domain(domain), body=body)

        body = {'domain_entry':
                {'scope': 'public',
                 'availability_zone': 'zone1'}}
        self.assertRaises(self._bad_request(),
                          self.domain_controller.update, req,
                          _quote_domain(domain), body=body)

        body = {'domain_entry':
                {'scope': 'public',
                 'project': 'testproject'}}
        entry = self.domain_controller.update(req,
                                              _quote_domain(domain), body=body)
        self.assertEqual(entry['domain_entry']['domain'], domain)
        self.assertEqual(entry['domain_entry']['scope'], 'public')
        self.assertEqual(entry['domain_entry']['project'], 'testproject')

        body = {'domain_entry':
                {'scope': 'private',
                 'availability_zone': 'zone1'}}
        entry = self.domain_controller.update(req,
                                              _quote_domain(domain), body=body)
        self.assertEqual(entry['domain_entry']['domain'], domain)
        self.assertEqual(entry['domain_entry']['scope'], 'private')
        self.assertEqual(entry['domain_entry']['availability_zone'], 'zone1')

    @mock.patch.object(network.api.API, "delete_dns_entry")
    def test_delete_entry(self, mock_del_entry):
        delete = self.entry_controller.delete
        res = delete(self.req, _quote_domain(domain), name)

        self._check_status(202, res, delete)
        mock_del_entry.assert_called_once_with(mock.ANY, name, domain)

    @mock.patch.object(network.api.API, "delete_dns_entry",
                       side_effect=exception.NotFound)
    def test_delete_entry_notfound(self, mock_del_entry):
        self.assertRaises(webob.exc.HTTPNotFound,
            self.entry_controller.delete, self.req, _quote_domain(domain),
            name)
        self.assertTrue(mock_del_entry.called)

    def test_delete_domain(self):
        self._test_delete_domain(self.req)

    @mock.patch.object(network.api.API, "delete_dns_domain")
    def _test_delete_domain(self, req, mock_del_dom):
        delete = self.domain_controller.delete
        res = delete(req, _quote_domain(domain))

        self._check_status(202, res, delete)
        mock_del_dom.assert_called_once_with(mock.ANY, domain)

    def test_delete_domain_notfound(self):
        self._test_delete_domain_notfound(self.req)

    @mock.patch.object(network.api.API, "delete_dns_domain",
                       side_effect=exception.NotFound)
    def _test_delete_domain_notfound(self, req, mock_del_dom):
        self.assertRaises(
            webob.exc.HTTPNotFound, self.domain_controller.delete,
            req, _quote_domain(domain))
        self.assertTrue(mock_del_dom.called)

    def test_modify(self):
        body = {'dns_entry':
                 {'ip': test_ipv4_address2,
                  'dns_type': 'A'}}
        entry = self.entry_controller.update(self.req, domain, name, body=body)

        self.assertEqual(entry['dns_entry']['ip'], test_ipv4_address2)

    def test_not_implemented_dns_entry_update(self):
        body = {'dns_entry':
                 {'ip': test_ipv4_address,
                  'dns_type': 'A'}}
        with mock.patch.object(network.api.API, 'modify_dns_entry',
                               side_effect=NotImplementedError()):
            self.assertRaises(webob.exc.HTTPNotImplemented,
                              self.entry_controller.update, self.req,
                              _quote_domain(domain), name, body=body)

    def test_not_implemented_dns_entry_show(self):
        with mock.patch.object(network.api.API, 'get_dns_entries_by_name',
                               side_effect=NotImplementedError()):
            self.assertRaises(webob.exc.HTTPNotImplemented,
                              self.entry_controller.show,
                              self.req, _quote_domain(domain), name)

    def test_not_implemented_delete_entry(self):
        with mock.patch.object(network.api.API, 'delete_dns_entry',
                               side_effect=NotImplementedError()):
            self.assertRaises(webob.exc.HTTPNotImplemented,
                              self.entry_controller.delete, self.req,
                              _quote_domain(domain), name)

    def test_not_implemented_delete_domain(self):
        with mock.patch.object(network.api.API, 'delete_dns_domain',
                               side_effect=NotImplementedError()):
            self.assertRaises(webob.exc.HTTPNotImplemented,
                              self.domain_controller.delete, self.admin_req,
                              _quote_domain(domain))

    def test_not_implemented_create_domain(self):
        body = {'domain_entry':
                {'scope': 'private',
                 'availability_zone': 'zone1'}}
        with mock.patch.object(network.api.API, 'create_private_dns_domain',
                               side_effect=NotImplementedError()):
            self.assertRaises(webob.exc.HTTPNotImplemented,
                              self.domain_controller.update, self.admin_req,
                              _quote_domain(domain), body=body)

    def test_not_implemented_dns_domains_list(self):
        with mock.patch.object(network.api.API, 'get_dns_domains',
                               side_effect=NotImplementedError()):
            self.assertRaises(webob.exc.HTTPNotImplemented,
                              self.domain_controller.index, self.req)


class FloatingIPDNSDomainPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIPDNSDomainPolicyEnforcementV21, self).setUp()
        self.controller = fipdns_v21.FloatingIPDNSDomainController()
        self.rule_name = "os_compute_api:os-floating-ip-dns"
        self.policy.set_rules({self.rule_name: "project:non_fake"})
        self.req = fakes.HTTPRequest.blank('')

    def test_get_floating_ip_dns_policy_failed(self):
        rule_name = "os_compute_api:os-floating-ip-dns"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_update_floating_ip_dns_policy_failed(self):
        rule_name = "os_compute_api:os-floating-ip-dns:domain:update"
        self.policy.set_rules({rule_name: "project:non_fake"})
        body = {'domain_entry':
                {'scope': 'public',
                 'project': 'testproject'}}
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.update, self.req, _quote_domain(domain), body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_floating_ip_dns_policy_failed(self):
        rule_name = "os_compute_api:os-floating-ip-dns:domain:delete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, _quote_domain(domain))
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class FloatingIPDNSEntryPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIPDNSEntryPolicyEnforcementV21, self).setUp()
        self.controller = fipdns_v21.FloatingIPDNSEntryController()
        self.rule_name = "os_compute_api:os-floating-ip-dns"
        self.policy.set_rules({self.rule_name: "project:non_fake"})
        self.req = fakes.HTTPRequest.blank('')

    def test_show_floating_ip_dns_entry_policy_failed(self):
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show, self.req,
                _quote_domain(domain), test_ipv4_address)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % self.rule_name,
            exc.format_message())

    def test_update_floating_ip_dns_policy_failed(self):
        body = {'dns_entry':
                 {'ip': test_ipv4_address,
                  'dns_type': 'A'}}
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.update, self.req, _quote_domain(domain),
                                    name, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % self.rule_name,
            exc.format_message())

    def test_delete_floating_ip_dns_policy_failed(self):
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, _quote_domain(domain), name)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % self.rule_name,
            exc.format_message())


class FloatingIpDNSDomainDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIpDNSDomainDeprecationTest, self).setUp()
        self.controller = fipdns_v21.FloatingIPDNSDomainController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.update, self.req, fakes.FAKE_UUID, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)


class FloatingIpDNSEntryDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(FloatingIpDNSEntryDeprecationTest, self).setUp()
        self.controller = fipdns_v21.FloatingIPDNSEntryController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.update, self.req, fakes.FAKE_UUID, fakes.FAKE_UUID,
            {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID, fakes.FAKE_UUID)
