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

import netaddr
from oslo_log import log as logging
from oslo_utils import uuidutils
import webob

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.compute import utils as compute_utils
from nova import exception
from nova.i18n import _
from nova.i18n import _LW
from nova import network


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'floating_ips')


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
        result['instance_id'] = floating_ip['fixed_ip']['instance_uuid']
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
        return common.get_instance(self.compute_api, context, instance_id)


def disassociate_floating_ip(self, context, instance, address):
    try:
        self.network_api.disassociate_floating_ip(context, instance, address)
    except exception.Forbidden:
        raise webob.exc.HTTPForbidden()
    except exception.CannotDisassociateAutoAssignedFloatingIP:
        msg = _('Cannot disassociate auto assigned floating IP')
        raise webob.exc.HTTPForbidden(explanation=msg)


class FloatingIPController(object):
    """The Floating IPs API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(FloatingIPController, self).__init__()

    def show(self, req, id):
        """Return data about the given floating IP."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except (exception.NotFound, exception.InvalidID):
            msg = _("Floating IP not found for ID %s") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        return _translate_floating_ip_view(floating_ip)

    def index(self, req):
        """Return a list of floating IPs allocated to a project."""
        context = req.environ['nova.context']
        authorize(context)

        floating_ips = self.network_api.get_floating_ips_by_project(context)

        return _translate_floating_ips_view(floating_ips)

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
                msg = _("No more floating IPs in pool %s.") % pool
            else:
                msg = _("No more floating IPs available.")
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.FloatingIpLimitExceeded:
            if pool:
                msg = _("IP allocation over quota in pool %s.") % pool
            else:
                msg = _("IP allocation over quota.")
            raise webob.exc.HTTPForbidden(explanation=msg)
        except exception.FloatingIpPoolNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.FloatingIpBadRequest as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())

        return _translate_floating_ip_view(ip)

    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)

        # get the floating ip object
        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except (exception.NotFound, exception.InvalidID):
            msg = _("Floating IP not found for ID %s") % id
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
            msg = _('Cannot disassociate auto assigned floating IP')
            raise webob.exc.HTTPForbidden(explanation=msg)
        return webob.Response(status_int=202)


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
            LOG.warning(
                _LW('Info cache is %r during associate'), instance.info_cache,
                instance=instance)
            msg = _('No nw_info cache associated with instance')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        fixed_ips = cached_nwinfo.fixed_ips()
        if not fixed_ips:
            msg = _('No fixed IPs associated to instance')
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
            try:
                fixed_address = next(ip['address'] for ip in fixed_ips
                                     if netaddr.valid_ipv4(ip['address']))
            except StopIteration:
                msg = _('Unable to associate floating IP %(address)s '
                        'to any fixed IPs for instance %(id)s. '
                        'Instance has no fixed IPv4 addresses to '
                        'associate.') % (
                        {'address': address, 'id': id})
                raise webob.exc.HTTPBadRequest(explanation=msg)
            if len(fixed_ips) > 1:
                LOG.warning(_LW('multiple fixed_ips exist, using the first '
                                'IPv4 fixed_ip: %s'), fixed_address)

        try:
            self.network_api.associate_floating_ip(context, instance,
                                  floating_address=address,
                                  fixed_address=fixed_address)
        except exception.FloatingIpAssociated:
            msg = _('floating IP is already associated')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.NoFloatingIpInterface:
            msg = _('l3driver call to add floating IP failed')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.FloatingIpNotFoundForAddress:
            msg = _('floating IP not found')
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.Forbidden as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        except Exception as e:
            msg = _('Unable to associate floating IP %(address)s to '
                    'fixed IP %(fixed_address)s for instance %(id)s. '
                    'Error: %(error)s') % (
                    {'address': address, 'fixed_address': fixed_address,
                     'id': id, 'error': e})
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
            msg = _("floating IP not found")
            raise webob.exc.HTTPNotFound(explanation=msg)

        # get the associated instance object (if any)
        instance = get_instance_by_floating_ip_addr(self, context, address)

        # disassociate if associated
        if (instance and
            floating_ip.get('fixed_ip_id') and
            (uuidutils.is_uuid_like(id) and
             [instance.uuid == id] or
             [instance.id == id])[0]):
            try:
                disassociate_floating_ip(self, context, instance, address)
            except exception.FloatingIpNotAssociated:
                msg = _('Floating IP is not associated')
                raise webob.exc.HTTPBadRequest(explanation=msg)
            return webob.Response(status_int=202)
        else:
            msg = _("Floating IP %(address)s is not associated with instance "
                    "%(id)s.") % {'address': address, 'id': id}
            raise webob.exc.HTTPConflict(explanation=msg)


class Floating_ips(extensions.ExtensionDescriptor):
    """Floating IPs support."""

    name = "FloatingIps"
    alias = "os-floating-ips"
    namespace = "http://docs.openstack.org/compute/ext/floating_ips/api/v1.1"
    updated = "2011-06-16T00:00:00Z"

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
