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
from nova.api.openstack.v2 import extensions
from nova import exception
from nova import log as logging
from nova import network


LOG = logging.getLogger('nova.api.openstack.v2.contrib.floating_ip_dns')


def make_dns_entry(elem):
    elem.set('id')
    elem.set('ip')
    elem.set('type')
    elem.set('zone')
    elem.set('name')


def make_zone_entry(elem):
    elem.set('zone')


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


class ZonesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('zones')
        elem = xmlutil.SubTemplateElement(root, 'zone',
                                          selector='zones')
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


def _translate_zone_entries_view(zonelist):
    return {'zones': [{'zone': zone} for zone in zonelist]}


def _unquote_zone(zone):
    """Unquoting function for receiving a zone name in a URL.

    Zone names tend to have .'s in them.  Urllib doesn't quote dots,
    but Routes tends to choke on them, so we need an extra level of
    by-hand quoting here.
    """
    return urllib.unquote(zone).replace('%2E', '.')


def _create_dns_entry(ip, name, zone):
    return {'ip': ip, 'name': name, 'zone': zone}


class FloatingIPDNSController(object):
    """DNS Entry controller for OpenStack API"""

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPDNSController, self).__init__()

    @wsgi.serializers(xml=FloatingIPDNSsTemplate)
    def show(self, req, id):
        """Return a list of dns entries.  If ip is specified, query for
           names.  if name is specified, query for ips.
           Quoted domain (aka 'zone') specified as id."""
        context = req.environ['nova.context']
        params = req.str_GET
        floating_ip = params['ip'] if 'ip' in params else ""
        name = params['name'] if 'name' in params else ""
        zone = _unquote_zone(id)

        if floating_ip:
            entries = self.network_api.get_dns_entries_by_address(context,
                                                                  floating_ip,
                                                                  zone)
            entrylist = [_create_dns_entry(floating_ip, entry, zone)
                         for entry in entries]
        elif name:
            entries = self.network_api.get_dns_entries_by_name(context,
                                                               name, zone)
            entrylist = [_create_dns_entry(entry, name, zone)
                         for entry in entries]
        else:
            entrylist = []

        return _translate_dns_entries_view(entrylist)

    @wsgi.serializers(xml=ZonesTemplate)
    def index(self, req):
        """Return a list of available DNS zones."""

        context = req.environ['nova.context']
        zones = self.network_api.get_dns_zones(context)

        return _translate_zone_entries_view(zones)

    @wsgi.serializers(xml=FloatingIPDNSTemplate)
    def create(self, req, body):
        """Add dns entry for name and address"""
        context = req.environ['nova.context']

        try:
            entry = body['dns_entry']
            address = entry['ip']
            name = entry['name']
            dns_type = entry['dns_type']
            zone = entry['zone']
        except (TypeError, KeyError):
            raise webob.exc.HTTPUnprocessableEntity()

        try:
            self.network_api.add_dns_entry(context, address, name,
                                           dns_type, zone)
        except exception.FloatingIpDNSExists:
            return webob.Response(status_int=409)

        return _translate_dns_entry_view({'ip': address,
                                          'name': name,
                                          'type': dns_type,
                                          'zone': zone})

    def delete(self, req, id):
        """Delete the entry identified by req and id. """
        context = req.environ['nova.context']
        params = req.str_GET
        name = params['name'] if 'name' in params else ""
        zone = _unquote_zone(id)

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
                         FloatingIPDNSController())
        resources.append(res)

        return resources
