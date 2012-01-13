# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2011 Grid Dynamics
# Copyright 2011 Eldar Nugaev, Kirill Shileev, Ilya Alekseyev
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

import webob

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack import extensions
from nova import compute
from nova import exception
from nova import log as logging
from nova import network
from nova import rpc


LOG = logging.getLogger('nova.api.openstack.compute.contrib.floating_ips')


def make_float_ip(elem):
    elem.set('id')
    elem.set('ip')
    elem.set('pool')
    elem.set('fixed_ip')
    elem.set('instance_id')


class FloatingIPTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('floating_ip',
                                       selector='floating_ip')
        make_float_ip(root)
        return xmlutil.MasterTemplate(root, 1)


class FloatingIPsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('floating_ips')
        elem = xmlutil.SubTemplateElement(root, 'floating_ip',
                                          selector='floating_ips')
        make_float_ip(elem)
        return xmlutil.MasterTemplate(root, 1)


def _translate_floating_ip_view(floating_ip):
    result = {
        'id': floating_ip['id'],
        'ip': floating_ip['address'],
        'pool': floating_ip['pool'],
    }
    try:
        result['fixed_ip'] = floating_ip['fixed_ip']['address']
    except (TypeError, KeyError):
        result['fixed_ip'] = None
    try:
        result['instance_id'] = floating_ip['fixed_ip']['instance']['uuid']
    except (TypeError, KeyError):
        result['instance_id'] = None
    return {'floating_ip': result}


def _translate_floating_ips_view(floating_ips):
    return {'floating_ips': [_translate_floating_ip_view(ip)['floating_ip']
                             for ip in floating_ips]}


class FloatingIPController(object):
    """The Floating IPs API controller for the OpenStack API."""

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPController, self).__init__()

    @wsgi.serializers(xml=FloatingIPTemplate)
    def show(self, req, id):
        """Return data about the given floating ip."""
        context = req.environ['nova.context']

        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound()

        return _translate_floating_ip_view(floating_ip)

    @wsgi.serializers(xml=FloatingIPsTemplate)
    def index(self, req):
        """Return a list of floating ips allocated to a project."""
        context = req.environ['nova.context']

        floating_ips = self.network_api.get_floating_ips_by_project(context)

        return _translate_floating_ips_view(floating_ips)

    @wsgi.serializers(xml=FloatingIPTemplate)
    def create(self, req, body=None):
        context = req.environ['nova.context']

        pool = None
        if body and 'pool' in body:
            pool = body['pool']
        try:
            address = self.network_api.allocate_floating_ip(context, pool)
            ip = self.network_api.get_floating_ip_by_address(context, address)
        except rpc.RemoteError as ex:
            # NOTE(tr3buchet) - why does this block exist?
            if ex.exc_type == 'NoMoreFloatingIps':
                if pool:
                    msg = _("No more floating ips in pool %s.") % pool
                else:
                    msg = _("No more floating ips available.")
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                raise

        return _translate_floating_ip_view(ip)

    def delete(self, req, id):
        context = req.environ['nova.context']
        floating_ip = self.network_api.get_floating_ip(context, id)

        if floating_ip.get('fixed_ip'):
            self.network_api.disassociate_floating_ip(context,
                                                      floating_ip['address'])

        self.network_api.release_floating_ip(context,
                                             address=floating_ip['address'])
        return webob.Response(status_int=202)

    def _get_ip_by_id(self, context, value):
        """Checks that value is id and then returns its address."""
        return self.network_api.get_floating_ip(context, value)['address']


class FloatingIPSerializer(xmlutil.XMLTemplateSerializer):
    def index(self):
        return FloatingIPsTemplate()

    def default(self):
        return FloatingIPTemplate()


class Floating_ips(extensions.ExtensionDescriptor):
    """Floating IPs support"""

    name = "Floating_ips"
    alias = "os-floating-ips"
    namespace = "http://docs.openstack.org/compute/ext/floating_ips/api/v1.1"
    updated = "2011-06-16T00:00:00+00:00"

    def __init__(self, ext_mgr):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(Floating_ips, self).__init__(ext_mgr)

    def _add_floating_ip(self, input_dict, req, instance_id):
        """Associate floating_ip to an instance."""
        context = req.environ['nova.context']

        try:
            address = input_dict['addFloatingIp']['address']
        except TypeError:
            msg = _("Missing parameter dict")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except KeyError:
            msg = _("Address not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            instance = self.compute_api.get(context, instance_id)
            self.compute_api.associate_floating_ip(context, instance,
                                                   address)
        except exception.ApiError, e:
            raise webob.exc.HTTPBadRequest(explanation=e.message)
        except exception.NotAuthorized, e:
            raise webob.exc.HTTPUnauthorized()

        return webob.Response(status_int=202)

    def _remove_floating_ip(self, input_dict, req, instance_id):
        """Dissociate floating_ip from an instance."""
        context = req.environ['nova.context']

        try:
            address = input_dict['removeFloatingIp']['address']
        except TypeError:
            msg = _("Missing parameter dict")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except KeyError:
            msg = _("Address not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        floating_ip = self.network_api.get_floating_ip_by_address(context,
                                                                  address)
        if floating_ip.get('fixed_ip'):
            try:
                self.network_api.disassociate_floating_ip(context, address)
            except exception.NotAuthorized, e:
                raise webob.exc.HTTPUnauthorized()

        return webob.Response(status_int=202)

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-floating-ips',
                         FloatingIPController(),
                         member_actions={})
        resources.append(res)

        return resources

    def get_actions(self):
        """Return the actions the extension adds, as required by contract."""
        actions = [
                extensions.ActionExtension("servers", "addFloatingIp",
                                            self._add_floating_ip),
                extensions.ActionExtension("servers", "removeFloatingIp",
                                            self._remove_floating_ip),
        ]

        return actions
