# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
#    under the License

import urllib

import webob

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack import extensions
from nova import exception
from nova import log as logging
from nova import network


LOG = logging.getLogger('nova.api.openstack.compute.contrib.floating_ip_dns')


def make_dns_entry(elem):
    elem.set('id')
    elem.set('ip')
    elem.set('type')
    elem.set('zone')
    elem.set('name')


def make_zone_entry(elem):
    elem.set('zone')
    elem.set('scope')
    elem.set('project')
    elem.set('availability_zone')


class FloatingIPDNSTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('dns_entry',
                                       selector='dns_entry')
        make_dns_entry(root)
        return xmlutil.MasterTemplate(root, 1)


class FloatingIPDNSsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('dns_entries')
        elem = xmlutil.SubTemplateElement(root, 'dns_entry',
                                          selector='dns_entries')
        make_dns_entry(elem)
        return xmlutil.MasterTemplate(root, 1)


class ZoneTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('zone_entry',
                                       selector='zone_entry')
        make_zone_entry(root)
        return xmlutil.MasterTemplate(root, 1)


class ZonesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('zone_entries')
        elem = xmlutil.SubTemplateElement(root, 'zone_entry',
                                          selector='zone_entries')
        make_zone_entry(elem)
        return xmlutil.MasterTemplate(root, 1)


def _translate_dns_entry_view(dns_entry):
    result = {}
    result['ip'] = dns_entry.get('ip')
    result['id'] = dns_entry.get('id')
    result['type'] = dns_entry.get('type')
    result['zone'] = dns_entry.get('zone')
    result['name'] = dns_entry.get('name')
    return {'dns_entry': result}


def _translate_dns_entries_view(dns_entries):
    return {'dns_entries': [_translate_dns_entry_view(entry)['dns_entry']
                            for entry in dns_entries]}


def _translate_zone_entry_view(zone_entry):
    result = {}
    result['domain'] = zone_entry.get('domain')
    result['scope'] = zone_entry.get('scope')
    result['project'] = zone_entry.get('project')
    result['availability_zone'] = zone_entry.get('availability_zone')
    return {'zone_entry': result}


def _translate_zone_entries_view(zone_entries):
    return {'zone_entries': [_translate_zone_entry_view(entry)['zone_entry']
                             for entry in zone_entries]}


def _unquote_zone(zone):
    """Unquoting function for receiving a zone name in a URL.

    Zone names tend to have .'s in them.  Urllib doesn't quote dots,
    but Routes tends to choke on them, so we need an extra level of
    by-hand quoting here.
    """
    return urllib.unquote(zone).replace('%2E', '.')


def _create_dns_entry(ip, name, zone):
    return {'ip': ip, 'name': name, 'zone': zone}


def _create_domain_entry(domain, scope=None, project=None, av_zone=None):
    return {'domain': domain, 'scope': scope, 'project': project,
            'availability_zone': av_zone}


class FloatingIPDNSDomainController(object):
    """DNS domain controller for OpenStack API"""

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPDNSDomainController, self).__init__()

    @wsgi.serializers(xml=ZonesTemplate)
    def index(self, req):
        """Return a list of available DNS zones."""
        context = req.environ['nova.context']
        zones = self.network_api.get_dns_zones(context)
        zonelist = [_create_domain_entry(zone['domain'],
                                         zone.get('scope'),
                                         zone.get('project'),
                                         zone.get('availability_zone'))
                    for zone in zones]

        return _translate_zone_entries_view(zonelist)

    @wsgi.serializers(xml=ZoneTemplate)
    def update(self, req, id, body):
        """Add or modify domain entry"""
        context = req.environ['nova.context']
        fqdomain = _unquote_zone(id)
        try:
            entry = body['zone_entry']
            scope = entry['scope']
        except (TypeError, KeyError):
            raise webob.exc.HTTPUnprocessableEntity()
        project = entry.get('project', None)
        av_zone = entry.get('availability_zone', None)
        if (not scope or
            project and av_zone or
            scope == 'private' and project or
            scope == 'public' and av_zone):
            raise webob.exc.HTTPUnprocessableEntity()
        try:
            if scope == 'private':
                self.network_api.create_private_dns_domain(context,
                                                           fqdomain,
                                                           av_zone)
                return _translate_zone_entry_view({'domain': fqdomain,
                                                   'scope': scope,
                                             'availability_zone': av_zone})
            else:
                self.network_api.create_public_dns_domain(context,
                                                          fqdomain,
                                                          project)
                return _translate_zone_entry_view({'domain': fqdomain,
                                                   'scope': 'public',
                                                   'project': project})
        except exception.NotAuthorized or exception.AdminRequired:
            return webob.Response(status_int=403)

    def delete(self, req, id):
        """Delete the domain identified by id. """
        context = req.environ['nova.context']
        params = req.str_GET
        zone = _unquote_zone(id)

        # Delete the whole domain
        try:
            self.network_api.delete_dns_domain(context, zone)
        except exception.NotAuthorized or exception.AdminRequired:
            return webob.Response(status_int=403)
        except exception.NotFound:
            return webob.Response(status_int=404)

        return webob.Response(status_int=200)


class FloatingIPDNSEntryController(object):
    """DNS Entry controller for OpenStack API"""

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPDNSEntryController, self).__init__()

    @wsgi.serializers(xml=FloatingIPDNSTemplate)
    def show(self, req, zone_id, id):
        """Return the DNS entry that corresponds to zone_id and id."""
        context = req.environ['nova.context']
        zone = _unquote_zone(zone_id)
        name = id

        entries = self.network_api.get_dns_entries_by_name(context,
                                                           name, zone)
        entry = _create_dns_entry(entries[0], name, zone)
        return _translate_dns_entry_view(entry)

    @wsgi.serializers(xml=FloatingIPDNSsTemplate)
    def index(self, req, zone_id):
        """Return a list of dns entries for the specified zone and ip."""
        context = req.environ['nova.context']
        params = req.GET
        floating_ip = params.get('ip')
        zone = _unquote_zone(zone_id)

        if not floating_ip:
            raise webob.exc.HTTPUnprocessableEntity()

        entries = self.network_api.get_dns_entries_by_address(context,
                                                              floating_ip,
                                                              zone)
        entrylist = [_create_dns_entry(floating_ip, entry, zone)
                     for entry in entries]

        return _translate_dns_entries_view(entrylist)

    @wsgi.serializers(xml=FloatingIPDNSTemplate)
    def update(self, req, zone_id, id, body):
        """Add or modify dns entry"""
        context = req.environ['nova.context']
        zone = _unquote_zone(zone_id)
        name = id
        try:
            entry = body['dns_entry']
            address = entry['ip']
            dns_type = entry['dns_type']
        except (TypeError, KeyError):
            raise webob.exc.HTTPUnprocessableEntity()

        entries = self.network_api.get_dns_entries_by_name(context, name, zone)
        if not entries:
            # create!
            self.network_api.add_dns_entry(context, address, name,
                                           dns_type, zone)
        else:
            # modify!
            self.network_api.modify_dns_entry(context, name, address, zone)

        return _translate_dns_entry_view({'ip': address,
                                          'name': name,
                                          'type': dns_type,
                                          'zone': zone})

    def delete(self, req, zone_id, id):
        """Delete the entry identified by req and id. """
        context = req.environ['nova.context']
        zone = _unquote_zone(zone_id)
        name = id

        try:
            self.network_api.delete_dns_entry(context, name, zone)
        except exception.NotFound:
            return webob.Response(status_int=404)

        return webob.Response(status_int=200)


class Floating_ip_dns(extensions.ExtensionDescriptor):
    """Floating IP DNS support"""

    name = "Floating_ip_dns"
    alias = "os-floating-ip-dns"
    namespace = "http://docs.openstack.org/ext/floating_ip_dns/api/v1.1"
    updated = "2011-12-23:00:00+00:00"

    def __init__(self, ext_mgr):
        self.network_api = network.API()
        super(Floating_ip_dns, self).__init__(ext_mgr)

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-floating-ip-dns',
                         FloatingIPDNSDomainController())
        resources.append(res)

        res = extensions.ResourceExtension('entries',
                         FloatingIPDNSEntryController(),
                         parent={'member_name': 'zone',
                                 'collection_name': 'os-floating-ip-dns'})
        resources.append(res)

        return resources
