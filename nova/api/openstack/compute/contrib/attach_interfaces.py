# Copyright 2012 SINA Inc.
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

"""The instance interfaces extension."""

import netaddr
import six
import webob
from webob import exc

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova import compute
from nova import exception
from nova.i18n import _
from nova import network
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'attach_interfaces')


def _translate_interface_attachment_view(port_info):
    """Maps keys for interface attachment details view."""
    return {
        'net_id': port_info['network_id'],
        'port_id': port_info['id'],
        'mac_addr': port_info['mac_address'],
        'port_state': port_info['status'],
        'fixed_ips': port_info.get('fixed_ips', None),
        }


class InterfaceAttachmentController(object):
    """The interface attachment API controller for the OpenStack API."""

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(InterfaceAttachmentController, self).__init__()

    def index(self, req, server_id):
        """Returns the list of interface attachments for a given instance."""
        return self._items(req, server_id,
            entity_maker=_translate_interface_attachment_view)

    def show(self, req, server_id, id):
        """Return data about the given interface attachment."""
        context = req.environ['nova.context']
        authorize(context)

        port_id = id
        # NOTE(mriedem): We need to verify the instance actually exists from
        # the server_id even though we're not using the instance for anything,
        # just the port id.
        common.get_instance(self.compute_api, context, server_id)

        try:
            port_info = self.network_api.show_port(context, port_id)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.Forbidden as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

        if port_info['port']['device_id'] != server_id:
            msg = _("Instance %(instance)s does not have a port with id "
                    "%(port)s") % {'instance': server_id, 'port': port_id}
            raise exc.HTTPNotFound(explanation=msg)

        return {'interfaceAttachment': _translate_interface_attachment_view(
                port_info['port'])}

    def create(self, req, server_id, body):
        """Attach an interface to an instance."""
        context = req.environ['nova.context']
        authorize(context)

        network_id = None
        port_id = None
        req_ip = None
        if body:
            attachment = body['interfaceAttachment']
            network_id = attachment.get('net_id', None)
            port_id = attachment.get('port_id', None)
            try:
                req_ip = attachment['fixed_ips'][0]['ip_address']
            except Exception:
                pass

        if network_id and port_id:
            msg = _("Must not input both network_id and port_id")
            raise exc.HTTPBadRequest(explanation=msg)
        if req_ip and not network_id:
            msg = _("Must input network_id when request IP address")
            raise exc.HTTPBadRequest(explanation=msg)

        if req_ip:
            try:
                netaddr.IPAddress(req_ip)
            except netaddr.AddrFormatError as e:
                raise exc.HTTPBadRequest(explanation=six.text_type(e))

        try:
            instance = common.get_instance(self.compute_api,
                                           context, server_id,
                                           want_objects=True)
            LOG.audit(_("Attach interface"), instance=instance)
            vif = self.compute_api.attach_interface(context,
                instance, network_id, port_id, req_ip)
        except (exception.PortNotFound,
                exception.FixedIpAlreadyInUse,
                exception.PortInUse,
                exception.NetworkDuplicated,
                exception.NetworkAmbiguous,
                exception.NetworkNotFound) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Network driver does not support this function.")
            raise webob.exc.HTTPNotImplemented(explanation=msg)
        except exception.InterfaceAttachFailed as e:
            msg = _("Failed to attach interface")
            raise webob.exc.HTTPInternalServerError(explanation=msg)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'attach_interface', server_id)

        return self.show(req, server_id, vif['id'])

    def delete(self, req, server_id, id):
        """Detach an interface from an instance."""
        context = req.environ['nova.context']
        authorize(context)
        port_id = id
        instance = common.get_instance(self.compute_api,
                                       context, server_id,
                                       want_objects=True)
        LOG.audit(_("Detach interface %s"), port_id, instance=instance)
        try:
            self.compute_api.detach_interface(context,
                instance, port_id=port_id)
        except exception.PortNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Network driver does not support this function.")
            raise webob.exc.HTTPNotImplemented(explanation=msg)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'detach_interface', server_id)

        return webob.Response(status_int=202)

    def _items(self, req, server_id, entity_maker):
        """Returns a list of attachments, transformed through entity_maker."""
        context = req.environ['nova.context']
        authorize(context)
        instance = common.get_instance(self.compute_api, context, server_id,
                                       want_objects=True)
        results = []
        search_opts = {'device_id': instance.uuid}

        try:
            data = self.network_api.list_ports(context, **search_opts)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except NotImplementedError:
            msg = _("Network driver does not support this function.")
            raise webob.exc.HTTPNotImplemented(explanation=msg)

        ports = data.get('ports', [])
        results = [entity_maker(port) for port in ports]

        return {'interfaceAttachments': results}


class Attach_interfaces(extensions.ExtensionDescriptor):
    """Attach interface support."""

    name = "AttachInterfaces"
    alias = "os-attach-interfaces"
    namespace = "http://docs.openstack.org/compute/ext/interfaces/api/v1.1"
    updated = "2012-07-22T00:00:00Z"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-interface',
                                           InterfaceAttachmentController(),
                                           parent=dict(
                                                member_name='server',
                                                collection_name='servers'))
        resources.append(res)

        return resources
