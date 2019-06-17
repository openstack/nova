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

import webob
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import attach_interfaces
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova import network
from nova import objects
from nova.policies import attach_interfaces as ai_policies


def _translate_interface_attachment_view(context, port_info, show_tag=False):
    """Maps keys for interface attachment details view.

    :param port_info: dict of port details from the networking service
    :param show_tag: If True, includes the "tag" key in the returned dict,
        else the "tag" entry is omitted (default: False)
    :returns: dict of a subset of details about the port and optionally the
        tag associated with the VirtualInterface record in the nova database
    """
    info = {
        'net_id': port_info['network_id'],
        'port_id': port_info['id'],
        'mac_addr': port_info['mac_address'],
        'port_state': port_info['status'],
        'fixed_ips': port_info.get('fixed_ips', None),
        }
    if show_tag:
        # Get the VIF for this port (if one exists - VirtualInterface records
        # did not exist for neutron ports until the Newton release).
        vif = objects.VirtualInterface.get_by_uuid(context, port_info['id'])
        info['tag'] = vif.tag if vif else None
    return info


class InterfaceAttachmentController(wsgi.Controller):
    """The interface attachment API controller for the OpenStack API."""

    def __init__(self):
        super(InterfaceAttachmentController, self).__init__()
        self.compute_api = compute.API()
        self.network_api = network.API()

    @wsgi.expected_errors((404, 501))
    def index(self, req, server_id):
        """Returns the list of interface attachments for a given instance."""
        context = req.environ['nova.context']
        context.can(ai_policies.BASE_POLICY_NAME)

        instance = common.get_instance(self.compute_api, context, server_id)
        search_opts = {'device_id': instance.uuid}

        try:
            data = self.network_api.list_ports(context, **search_opts)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()

        # If showing tags, get the VirtualInterfaceList for the server and
        # map VIFs by port ID. Note that VirtualInterface records did not
        # exist for neutron ports until the Newton release so it's OK if we
        # are missing records for old servers.
        show_tag = api_version_request.is_supported(req, '2.70')
        tag_per_port_id = {}
        if show_tag:
            vifs = objects.VirtualInterfaceList.get_by_instance_uuid(
                context, server_id)
            tag_per_port_id = {vif.uuid: vif.tag for vif in vifs}

        results = []
        ports = data.get('ports', [])
        for port in ports:
            # Note that we do not pass show_tag=show_tag to
            # _translate_interface_attachment_view because we are handling it
            # ourselves here since we have the list of VIFs which is better
            # for performance than doing a DB query per port.
            info = _translate_interface_attachment_view(context, port)
            if show_tag:
                info['tag'] = tag_per_port_id.get(port['id'])
            results.append(info)

        return {'interfaceAttachments': results}

    @wsgi.expected_errors((403, 404))
    def show(self, req, server_id, id):
        """Return data about the given interface attachment."""
        context = req.environ['nova.context']
        context.can(ai_policies.BASE_POLICY_NAME)

        port_id = id
        # NOTE(mriedem): We need to verify the instance actually exists from
        # the server_id even though we're not using the instance for anything,
        # just the port id.
        common.get_instance(self.compute_api, context, server_id)

        try:
            port_info = self.network_api.show_port(context, port_id)
        except exception.PortNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.Forbidden as e:
            raise exc.HTTPForbidden(explanation=e.format_message())

        if port_info['port']['device_id'] != server_id:
            msg = _("Instance %(instance)s does not have a port with id "
                    "%(port)s") % {'instance': server_id, 'port': port_id}
            raise exc.HTTPNotFound(explanation=msg)

        return {'interfaceAttachment':
                _translate_interface_attachment_view(
                    context, port_info['port'],
                    show_tag=api_version_request.is_supported(req, '2.70'))}

    @wsgi.expected_errors((400, 403, 404, 409, 500, 501))
    @validation.schema(attach_interfaces.create, '2.0', '2.48')
    @validation.schema(attach_interfaces.create_v249, '2.49')
    def create(self, req, server_id, body):
        """Attach an interface to an instance."""
        context = req.environ['nova.context']
        context.can(ai_policies.BASE_POLICY_NAME)
        context.can(ai_policies.POLICY_ROOT % 'create')

        network_id = None
        port_id = None
        req_ip = None
        tag = None
        if body:
            attachment = body['interfaceAttachment']
            network_id = attachment.get('net_id', None)
            port_id = attachment.get('port_id', None)
            tag = attachment.get('tag', None)
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

        instance = common.get_instance(self.compute_api, context, server_id)
        try:
            vif = self.compute_api.attach_interface(context,
                instance, network_id, port_id, req_ip, tag=tag)
        except (exception.InterfaceAttachFailedNoNetwork,
                exception.NetworkAmbiguous,
                exception.NoMoreFixedIps,
                exception.PortNotUsable,
                exception.AttachInterfaceNotSupported,
                exception.SecurityGroupCannotBeApplied,
                exception.NetworkInterfaceTaggedAttachNotSupported,
                exception.NetworksWithQoSPolicyNotSupported) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except (exception.InstanceIsLocked,
                exception.FixedIpAlreadyInUse,
                exception.PortInUse) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except (exception.PortNotFound,
                exception.NetworkNotFound) as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.PortLimitExceeded as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        except exception.InterfaceAttachFailed as e:
            raise webob.exc.HTTPInternalServerError(
                explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'attach_interface', server_id)

        return self.show(req, server_id, vif['id'])

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409, 501))
    def delete(self, req, server_id, id):
        """Detach an interface from an instance."""
        context = req.environ['nova.context']
        context.can(ai_policies.BASE_POLICY_NAME)
        context.can(ai_policies.POLICY_ROOT % 'delete')
        port_id = id

        instance = common.get_instance(self.compute_api, context, server_id,
                                       expected_attrs=['device_metadata'])
        try:
            self.compute_api.detach_interface(context,
                instance, port_id=port_id)
        except exception.PortNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except NotImplementedError:
            common.raise_feature_not_supported()
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'detach_interface', server_id)
