# Copyright (c) 2013 NTT DOCOMO, INC.
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

"""The bare-metal admin extension with Ironic Proxy."""

from oslo.config import cfg
from oslo.utils import importutils
import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _
from nova.openstack.common import log as logging

ironic_client = importutils.try_import('ironicclient.client')

authorize = extensions.extension_authorizer('compute', 'baremetal_nodes')

node_fields = ['id', 'cpus', 'local_gb', 'memory_mb', 'pm_address',
               'pm_user', 'service_host', 'terminal_port', 'instance_uuid']

node_ext_fields = ['uuid', 'task_state', 'updated_at', 'pxe_config_path']

interface_fields = ['id', 'address', 'datapath_id', 'port_no']

CONF = cfg.CONF

CONF.import_opt('api_version',
                'nova.virt.ironic.driver',
                group='ironic')
CONF.import_opt('api_endpoint',
                'nova.virt.ironic.driver',
                group='ironic')
CONF.import_opt('admin_username',
                'nova.virt.ironic.driver',
                group='ironic')
CONF.import_opt('admin_password',
                'nova.virt.ironic.driver',
                group='ironic')
CONF.import_opt('admin_tenant_name',
                'nova.virt.ironic.driver',
                group='ironic')
CONF.import_opt('compute_driver', 'nova.virt.driver')

LOG = logging.getLogger(__name__)


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
    ironicclient = ironic_client.get_client(CONF.ironic.api_version, **kwargs)
    return ironicclient


def _no_ironic_proxy(cmd):
    raise webob.exc.HTTPBadRequest(
                    explanation=_("Command Not supported. Please use Ironic "
                                  "command %(cmd)s to perform this "
                                  "action.") % {'cmd': cmd})


class BareMetalNodeController(wsgi.Controller):
    """The Bare-Metal Node API controller for the OpenStack API.

    Ironic is used for the following commands:
        'baremetal-node-list'
        'baremetal-node-show'
    """

    def __init__(self, ext_mgr=None, *args, **kwargs):
        super(BareMetalNodeController, self).__init__(*args, **kwargs)
        self.ext_mgr = ext_mgr

    def _node_dict(self, node_ref):
        d = {}
        for f in node_fields:
            d[f] = node_ref.get(f)
        if self.ext_mgr.is_loaded('os-baremetal-ext-status'):
            for f in node_ext_fields:
                d[f] = node_ref.get(f)
        return d

    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        nodes = []
        # proxy command to Ironic
        ironicclient = _get_ironic_client()
        ironic_nodes = ironicclient.node.list(detail=True)
        for inode in ironic_nodes:
            node = {'id': inode.uuid,
                    'interfaces': [],
                    'host': 'IRONIC MANAGED',
                    'task_state': inode.provision_state,
                    'cpus': inode.properties['cpus'],
                    'memory_mb': inode.properties['memory_mb'],
                    'disk_gb': inode.properties['local_gb']}
            nodes.append(node)
        return {'nodes': nodes}

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        # proxy command to Ironic
        icli = _get_ironic_client()
        inode = icli.node.get(id)
        iports = icli.node.list_ports(id)
        node = {'id': inode.uuid,
                'interfaces': [],
                'host': 'IRONIC MANAGED',
                'task_state': inode.provision_state,
                'cpus': inode.properties['cpus'],
                'memory_mb': inode.properties['memory_mb'],
                'disk_gb': inode.properties['local_gb'],
                'instance_uuid': inode.instance_uuid}
        for port in iports:
            node['interfaces'].append({'address': port.address})
        return {'node': node}

    def create(self, req, body):
        _no_ironic_proxy("port-create")

    def delete(self, req, id):
        _no_ironic_proxy("port-create")

    @wsgi.action('add_interface')
    def _add_interface(self, req, id, body):
        _no_ironic_proxy("port-create")

    @wsgi.action('remove_interface')
    def _remove_interface(self, req, id, body):
        _no_ironic_proxy("port-delete")


class Baremetal_nodes(extensions.ExtensionDescriptor):
    """Admin-only bare-metal node administration."""

    name = "BareMetalNodes"
    alias = "os-baremetal-nodes"
    namespace = "http://docs.openstack.org/compute/ext/baremetal_nodes/api/v2"
    updated = "2013-01-04T00:00:00Z"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('os-baremetal-nodes',
                BareMetalNodeController(self.ext_mgr),
                member_actions={"action": "POST", })
        resources.append(res)
        return resources
