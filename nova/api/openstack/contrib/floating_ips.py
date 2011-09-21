# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova import compute
from nova import exception
from nova import log as logging
from nova import network
from nova import rpc
from nova.api.openstack import faults
from nova.api.openstack import extensions


LOG = logging.getLogger('nova.api.openstack.contrib.floating_ips')


def _translate_floating_ip_view(floating_ip):
    result = {'id': floating_ip['id'],
              'ip': floating_ip['address']}
    try:
        result['fixed_ip'] = floating_ip['fixed_ip']['address']
    except (TypeError, KeyError):
        result['fixed_ip'] = None
    try:
        result['instance_id'] = floating_ip['fixed_ip']['instance_id']
    except (TypeError, KeyError):
        result['instance_id'] = None
    return {'floating_ip': result}


def _translate_floating_ips_view(floating_ips):
    return {'floating_ips': [_translate_floating_ip_view(ip)['floating_ip']
                             for ip in floating_ips]}


class FloatingIPController(object):
    """The Floating IPs API controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "floating_ip": [
                    "id",
                    "ip",
                    "instance_id",
                    "fixed_ip",
                    ]}}}

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPController, self).__init__()

    def show(self, req, id):
        """Return data about the given floating ip."""
        context = req.environ['nova.context']

        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except exception.NotFound:
            return faults.Fault(webob.exc.HTTPNotFound())

        return _translate_floating_ip_view(floating_ip)

    def index(self, req):
        context = req.environ['nova.context']

        try:
            # FIXME(ja) - why does self.network_api.list_floating_ips raise?
            floating_ips = self.network_api.list_floating_ips(context)
        except exception.FloatingIpNotFoundForProject:
            floating_ips = []

        return _translate_floating_ips_view(floating_ips)

    def create(self, req, body=None):
        context = req.environ['nova.context']

        try:
            address = self.network_api.allocate_floating_ip(context)
            ip = self.network_api.get_floating_ip_by_ip(context, address)
        except rpc.RemoteError as ex:
            # NOTE(tr3buchet) - why does this block exist?
            if ex.exc_type == 'NoMoreFloatingIps':
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
        return webob.exc.HTTPAccepted()

    def _get_ip_by_id(self, context, value):
        """Checks that value is id and then returns its address."""
        return self.network_api.get_floating_ip(context, value)['address']


class Floating_ips(extensions.ExtensionDescriptor):
    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(Floating_ips, self).__init__()

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
            self.compute_api.associate_floating_ip(context, instance_id,
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

        floating_ip = self.network_api.get_floating_ip_by_ip(context, address)
        if floating_ip.get('fixed_ip'):
            try:
                self.network_api.disassociate_floating_ip(context, address)
            except exception.NotAuthorized, e:
                raise webob.exc.HTTPUnauthorized()

        return webob.Response(status_int=202)

    def get_name(self):
        return "Floating_ips"

    def get_alias(self):
        return "os-floating-ips"

    def get_description(self):
        return "Floating IPs support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/floating_ips/api/v1.1"

    def get_updated(self):
        return "2011-06-16T00:00:00+00:00"

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
