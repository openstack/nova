# Copyright (c) 2013 NTT DOCOMO, INC.
# Copyright 2014 IBM Corporation.
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

"""The bare-metal admin extension."""

from oslo_utils import importutils
import webob

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import nova.conf
from nova.i18n import _
from nova.policies import baremetal_nodes as bn_policies

ironic_client = importutils.try_import('ironicclient.client')
ironic_exc = importutils.try_import('ironicclient.exc')

node_fields = ['id', 'cpus', 'local_gb', 'memory_mb', 'pm_address',
               'pm_user', 'service_host', 'terminal_port', 'instance_uuid']

node_ext_fields = ['uuid', 'task_state', 'updated_at', 'pxe_config_path']

interface_fields = ['id', 'address', 'datapath_id', 'port_no']

CONF = nova.conf.CONF


def _check_ironic_client_enabled():
    """Check whether Ironic is installed or not."""
    if ironic_client is None:
        common.raise_feature_not_supported()


def _get_ironic_client():
    """return an Ironic client."""
    # TODO(NobodyCam): Fix insecure setting
    kwargs = {'os_username': CONF.ironic.admin_username,
              'os_password': CONF.ironic.admin_password,
              'os_auth_url': CONF.ironic.admin_url,
              'os_tenant_name': CONF.ironic.admin_tenant_name,
              'os_service_type': 'baremetal',
              'os_endpoint_type': 'public',
              'insecure': 'true',
              'ironic_url': CONF.ironic.api_endpoint}
    # NOTE(mriedem): The 1 api_version arg here is the only valid value for
    # the client, but it's not even used so it doesn't really matter. The
    # ironic client wrapper in the virt driver actually uses a hard-coded
    # microversion via the os_ironic_api_version kwarg.
    icli = ironic_client.get_client(1, **kwargs)
    return icli


def _no_ironic_proxy(cmd):
    raise webob.exc.HTTPBadRequest(
                    explanation=_("Command Not supported. Please use Ironic "
                                  "command %(cmd)s to perform this "
                                  "action.") % {'cmd': cmd})


class BareMetalNodeController(wsgi.Controller):
    """The Bare-Metal Node API controller for the OpenStack API."""

    def _node_dict(self, node_ref):
        d = {}
        for f in node_fields:
            d[f] = node_ref.get(f)
        for f in node_ext_fields:
            d[f] = node_ref.get(f)
        return d

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((404, 501))
    def index(self, req):
        context = req.environ['nova.context']
        context.can(bn_policies.BASE_POLICY_NAME)
        nodes = []
        # proxy command to Ironic
        _check_ironic_client_enabled()
        icli = _get_ironic_client()
        ironic_nodes = icli.node.list(detail=True)
        for inode in ironic_nodes:
            node = {'id': inode.uuid,
                    'interfaces': [],
                    'host': 'IRONIC MANAGED',
                    'task_state': inode.provision_state,
                    'cpus': inode.properties.get('cpus', 0),
                    'memory_mb': inode.properties.get('memory_mb', 0),
                    'disk_gb': inode.properties.get('local_gb', 0)}
            nodes.append(node)
        return {'nodes': nodes}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors((404, 501))
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(bn_policies.BASE_POLICY_NAME)
        # proxy command to Ironic
        _check_ironic_client_enabled()
        icli = _get_ironic_client()
        try:
            inode = icli.node.get(id)
        except ironic_exc.NotFound:
            msg = _("Node %s could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        iports = icli.node.list_ports(id)
        node = {'id': inode.uuid,
                'interfaces': [],
                'host': 'IRONIC MANAGED',
                'task_state': inode.provision_state,
                'cpus': inode.properties.get('cpus', 0),
                'memory_mb': inode.properties.get('memory_mb', 0),
                'disk_gb': inode.properties.get('local_gb', 0),
                'instance_uuid': inode.instance_uuid}
        for port in iports:
            node['interfaces'].append({'address': port.address})
        return {'node': node}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(400)
    def create(self, req, body):
        _no_ironic_proxy("node-create")

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(400)
    def delete(self, req, id):
        _no_ironic_proxy("node-delete")

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action('add_interface')
    @extensions.expected_errors(400)
    def _add_interface(self, req, id, body):
        _no_ironic_proxy("port-create")

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action('remove_interface')
    @extensions.expected_errors(400)
    def _remove_interface(self, req, id, body):
        _no_ironic_proxy("port-delete")
