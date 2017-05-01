# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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

from oslo_utils import netutils
from six.moves import urllib
import webob

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import floating_ip_dns
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
from nova import network
from nova.policies import floating_ip_dns as fid_policies


def _translate_dns_entry_view(dns_entry):
    result = {}
    result['ip'] = dns_entry.get('ip')
    result['id'] = dns_entry.get('id')
    result['type'] = dns_entry.get('type')
    result['domain'] = dns_entry.get('domain')
    result['name'] = dns_entry.get('name')
    return {'dns_entry': result}


def _translate_dns_entries_view(dns_entries):
    return {'dns_entries': [_translate_dns_entry_view(entry)['dns_entry']
                            for entry in dns_entries]}


def _translate_domain_entry_view(domain_entry):
    result = {}
    result['domain'] = domain_entry.get('domain')
    result['scope'] = domain_entry.get('scope')
    result['project'] = domain_entry.get('project')
    result['availability_zone'] = domain_entry.get('availability_zone')
    return {'domain_entry': result}


def _translate_domain_entries_view(domain_entries):
    return {'domain_entries':
            [_translate_domain_entry_view(entry)['domain_entry']
                             for entry in domain_entries]}


def _unquote_domain(domain):
    """Unquoting function for receiving a domain name in a URL.

    Domain names tend to have .'s in them.  Urllib doesn't quote dots,
    but Routes tends to choke on them, so we need an extra level of
    by-hand quoting here.
    """
    return urllib.parse.unquote(domain).replace('%2E', '.')


def _create_dns_entry(ip, name, domain):
    return {'ip': ip, 'name': name, 'domain': domain}


def _create_domain_entry(domain, scope=None, project=None, av_zone=None):
    return {'domain': domain, 'scope': scope, 'project': project,
            'availability_zone': av_zone}


class FloatingIPDNSDomainController(wsgi.Controller):
    """DNS domain controller for OpenStack API."""

    def __init__(self):
        super(FloatingIPDNSDomainController, self).__init__()
        self.network_api = network.API()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(501)
    def index(self, req):
        """Return a list of available DNS domains."""
        context = req.environ['nova.context']
        context.can(fid_policies.BASE_POLICY_NAME)

        try:
            domains = self.network_api.get_dns_domains(context)
        except NotImplementedError:
            common.raise_feature_not_supported()

        domainlist = [_create_domain_entry(domain['domain'],
                                         domain.get('scope'),
                                         domain.get('project'),
                                         domain.get('availability_zone'))
                    for domain in domains]

        return _translate_domain_entries_view(domainlist)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((400, 501))
    @validation.schema(floating_ip_dns.domain_entry_update)
    def update(self, req, id, body):
        """Add or modify domain entry."""
        context = req.environ['nova.context']
        context.can(fid_policies.POLICY_ROOT % "domain:update")
        fqdomain = _unquote_domain(id)
        entry = body['domain_entry']
        scope = entry['scope']
        project = entry.get('project', None)
        av_zone = entry.get('availability_zone', None)

        if scope == 'private' and project:
            msg = _("you can not pass project if the scope is private")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if scope == 'public' and av_zone:
            msg = _("you can not pass av_zone if the scope is public")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if scope == 'private':
            create_dns_domain = self.network_api.create_private_dns_domain
            area_name, area = 'availability_zone', av_zone
        else:
            create_dns_domain = self.network_api.create_public_dns_domain
            area_name, area = 'project', project

        try:
            create_dns_domain(context, fqdomain, area)
        except NotImplementedError:
            common.raise_feature_not_supported()

        return _translate_domain_entry_view({'domain': fqdomain,
                                             'scope': scope,
                                             area_name: area})

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((404, 501))
    @wsgi.response(202)
    def delete(self, req, id):
        """Delete the domain identified by id."""
        context = req.environ['nova.context']
        context.can(fid_policies.POLICY_ROOT % "domain:delete")
        domain = _unquote_domain(id)

        # Delete the whole domain
        try:
            self.network_api.delete_dns_domain(context, domain)
        except NotImplementedError:
            common.raise_feature_not_supported()
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())


class FloatingIPDNSEntryController(wsgi.Controller):
    """DNS Entry controller for OpenStack API."""

    def __init__(self):
        super(FloatingIPDNSEntryController, self).__init__()
        self.network_api = network.API()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((404, 501))
    def show(self, req, domain_id, id):
        """Return the DNS entry that corresponds to domain_id and id."""
        context = req.environ['nova.context']
        context.can(fid_policies.BASE_POLICY_NAME)
        domain = _unquote_domain(domain_id)

        floating_ip = None
        # Check whether id is a valid ipv4/ipv6 address.
        if netutils.is_valid_ip(id):
            floating_ip = id

        try:
            if floating_ip:
                entries = self.network_api.get_dns_entries_by_address(context,
                                                                  floating_ip,
                                                                  domain)
            else:
                entries = self.network_api.get_dns_entries_by_name(context,
                                                                   id,
                                                                   domain)
        except NotImplementedError:
            common.raise_feature_not_supported()

        if not entries:
            explanation = _("DNS entries not found.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        if floating_ip:
            entrylist = [_create_dns_entry(floating_ip, entry, domain)
                         for entry in entries]
            dns_entries = _translate_dns_entries_view(entrylist)
            return wsgi.ResponseObject(dns_entries)

        entry = _create_dns_entry(entries[0], id, domain)
        return _translate_dns_entry_view(entry)

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(501)
    @validation.schema(floating_ip_dns.dns_entry_update)
    def update(self, req, domain_id, id, body):
        """Add or modify dns entry."""
        context = req.environ['nova.context']
        context.can(fid_policies.BASE_POLICY_NAME)
        domain = _unquote_domain(domain_id)
        name = id
        entry = body['dns_entry']
        address = entry['ip']
        dns_type = entry['dns_type']

        try:
            entries = self.network_api.get_dns_entries_by_name(context,
                                                               name, domain)
            if not entries:
                # create!
                self.network_api.add_dns_entry(context, address, name,
                                               dns_type, domain)
            else:
                # modify!
                self.network_api.modify_dns_entry(context, name,
                                                  address, domain)
        except NotImplementedError:
            common.raise_feature_not_supported()

        return _translate_dns_entry_view({'ip': address,
                                          'name': name,
                                          'type': dns_type,
                                          'domain': domain})

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((404, 501))
    @wsgi.response(202)
    def delete(self, req, domain_id, id):
        """Delete the entry identified by req and id."""
        context = req.environ['nova.context']
        context.can(fid_policies.BASE_POLICY_NAME)
        domain = _unquote_domain(domain_id)
        name = id

        try:
            self.network_api.delete_dns_entry(context, name, domain)
        except NotImplementedError:
            common.raise_feature_not_supported()
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
