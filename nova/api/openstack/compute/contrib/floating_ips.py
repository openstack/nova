# Copyright 2011 OpenStack Foundation
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
#    under the License.

import webob

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova.compute import utils as compute_utils
from nova import exception
from nova import network
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import uuidutils


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'floating_ips')


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
    except (TypeError, KeyError, AttributeError):
        result['fixed_ip'] = None
    try:
        result['instance_id'] = floating_ip['instance']['uuid']
    except (TypeError, KeyError, AttributeError):
        result['instance_id'] = None
    return {'floating_ip': result}


def _translate_floating_ips_view(floating_ips):
    return {'floating_ips': [_translate_floating_ip_view(ip)['floating_ip']
                             for ip in floating_ips]}


def get_instance_by_floating_ip_addr(self, context, address):
    snagiibfa = self.network_api.get_instance_id_by_floating_address
    instance_id = snagiibfa(context, address)
    if instance_id:
        return self.compute_api.get(context, instance_id)


def disassociate_floating_ip(self, context, instance, address):
    try:
        self.network_api.disassociate_floating_ip(context, instance, address)
    except exception.NotAuthorized:
        raise webob.exc.HTTPForbidden()
    except exception.CannotDisassociateAutoAssignedFloatingIP:
        msg = _('Cannot disassociate auto assigned floating ip')
        raise webob.exc.HTTPForbidden(explanation=msg)


class FloatingIPController(object):
    """The Floating IPs API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(FloatingIPController, self).__init__()

    def _normalize_ip(self, floating_ip):
        # NOTE(vish): translate expects instance to be in the floating_ip
        #             dict but it is returned in the fixed_ip dict by
        #             nova-network
        fixed_ip = floating_ip.get('fixed_ip')
        if 'instance' not in floating_ip:
            if fixed_ip:
                floating_ip['instance'] = fixed_ip['instance']
            else:
                floating_ip['instance'] = None

    @wsgi.serializers(xml=FloatingIPTemplate)
    def show(self, req, id):
        """Return data about the given floating ip."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except (exception.NotFound, exception.InvalidID):
            msg = _("Floating ip not found for id %s") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        self._normalize_ip(floating_ip)

        return _translate_floating_ip_view(floating_ip)

    @wsgi.serializers(xml=FloatingIPsTemplate)
    def index(self, req):
        """Return a list of floating ips allocated to a project."""
        context = req.environ['nova.context']
        authorize(context)

        floating_ips = self.network_api.get_floating_ips_by_project(context)

        for floating_ip in floating_ips:
            self._normalize_ip(floating_ip)

        return _translate_floating_ips_view(floating_ips)

    @wsgi.serializers(xml=FloatingIPTemplate)
    def create(self, req, body=None):
        context = req.environ['nova.context']
        authorize(context)

        pool = None
        if body and 'pool' in body:
            pool = body['pool']
        try:
            address = self.network_api.allocate_floating_ip(context, pool)
            ip = self.network_api.get_floating_ip_by_address(context, address)
        except exception.NoMoreFloatingIps:
            if pool:
                msg = _("No more floating ips in pool %s.") % pool
            else:
                msg = _("No more floating ips available.")
            raise webob.exc.HTTPNotFound(explanation=msg)

        return _translate_floating_ip_view(ip)

    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)

        # get the floating ip object
        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except (exception.NotFound, exception.InvalidID):
            msg = _("Floating ip not found for id %s") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        address = floating_ip['address']

        # get the associated instance object (if any)
        instance = get_instance_by_floating_ip_addr(self, context, address)
        try:
            self.network_api.disassociate_and_release_floating_ip(
                context, instance, floating_ip)
        except exception.Forbidden:
            raise webob.exc.HTTPForbidden()
        except exception.CannotDisassociateAutoAssignedFloatingIP:
            msg = _('Cannot disassociate auto assigned floating ip')
            raise webob.exc.HTTPForbidden(explanation=msg)
        return webob.Response(status_int=202)

    def _get_ip_by_id(self, context, value):
        """Checks that value is id and then returns its address."""
        return self.network_api.get_floating_ip(context, value)['address']


class FloatingIPActionController(wsgi.Controller):
    def __init__(self, ext_mgr=None, *args, **kwargs):
        super(FloatingIPActionController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.network_api = network.API()
        self.ext_mgr = ext_mgr

    @wsgi.action('addFloatingIp')
    def _add_floating_ip(self, req, id, body):
        """Associate floating_ip to an instance."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            address = body['addFloatingIp']['address']
        except TypeError:
            msg = _("Missing parameter dict")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except KeyError:
            msg = _("Address not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        instance = common.get_instance(self.compute_api, context, id)
        cached_nwinfo = compute_utils.get_nw_info_for_instance(instance)
        if not cached_nwinfo:
            msg = _('No nw_info cache associated with instance')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        fixed_ips = cached_nwinfo.fixed_ips()
        if not fixed_ips:
            msg = _('No fixed ips associated to instance')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        fixed_address = None
        if self.ext_mgr.is_loaded('os-extended-floating-ips'):
            if 'fixed_address' in body['addFloatingIp']:
                fixed_address = body['addFloatingIp']['fixed_address']
                for fixed in fixed_ips:
                    if fixed['address'] == fixed_address:
                        break
                else:
                    msg = _('Specified fixed address not assigned to instance')
                    raise webob.exc.HTTPBadRequest(explanation=msg)

        if not fixed_address:
            fixed_address = fixed_ips[0]['address']
            if len(fixed_ips) > 1:
                msg = _('multiple fixed_ips exist, using the first: %s')
                LOG.warning(msg, fixed_address)

        try:
            self.network_api.associate_floating_ip(context, instance,
                                  floating_address=address,
                                  fixed_address=fixed_address)
        except exception.FloatingIpAssociated:
            msg = _('floating ip is already associated')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.NoFloatingIpInterface:
            msg = _('l3driver call to add floating ip failed')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except (exception.FloatingIpNotFoundForAddress,
                exception.NotAuthorized):
            msg = _('floating ip not found')
            raise webob.exc.HTTPNotFound(explanation=msg)
        except Exception:
            msg = _('Error. Unable to associate floating ip')
            LOG.exception(msg)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)

    @wsgi.action('removeFloatingIp')
    def _remove_floating_ip(self, req, id, body):
        """Dissociate floating_ip from an instance."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            address = body['removeFloatingIp']['address']
        except TypeError:
            msg = _("Missing parameter dict")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except KeyError:
            msg = _("Address not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # get the floating ip object
        try:
            floating_ip = self.network_api.get_floating_ip_by_address(context,
                                                                      address)
        except exception.FloatingIpNotFoundForAddress:
            msg = _("floating ip not found")
            raise webob.exc.HTTPNotFound(explanation=msg)

        # get the associated instance object (if any)
        instance = get_instance_by_floating_ip_addr(self, context, address)

        # disassociate if associated
        if (instance and
            floating_ip.get('fixed_ip_id') and
            (uuidutils.is_uuid_like(id) and
             [instance['uuid'] == id] or
             [instance['id'] == id])[0]):
            try:
                disassociate_floating_ip(self, context, instance, address)
            except exception.FloatingIpNotAssociated:
                msg = _('Floating ip is not associated')
                raise webob.exc.HTTPBadRequest(explanation=msg)
            return webob.Response(status_int=202)
        else:
            msg = _("Floating ip %(address)s is not associated with instance "
                    "%(id)s.") % {'address': address, 'id': id}
            raise webob.exc.HTTPUnprocessableEntity(explanation=msg)


class Floating_ips(extensions.ExtensionDescriptor):
    """Floating IPs support."""

    name = "FloatingIps"
    alias = "os-floating-ips"
    namespace = "http://docs.openstack.org/compute/ext/floating_ips/api/v1.1"
    updated = "2011-06-16T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-floating-ips',
                         FloatingIPController(),
                         member_actions={})
        resources.append(res)

        return resources

    def get_controller_extensions(self):
        controller = FloatingIPActionController(self.ext_mgr)
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
