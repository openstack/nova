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

"""The baremetal admin extension."""

from openstack import exceptions as sdk_exc
import webob

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import wsgi
import nova.conf
from nova.i18n import _
from nova.policies import baremetal_nodes as bn_policies
from nova import utils

CONF = nova.conf.CONF


def _no_ironic_proxy(cmd):
    msg = _(
        "Command Not supported. Please use Ironic "
        "command %(cmd)s to perform this action."
    )
    raise webob.exc.HTTPBadRequest(explanation=msg % {'cmd': cmd})


class BareMetalNodeController(wsgi.Controller):
    """The Bare-Metal Node API controller for the OpenStack API."""

    def __init__(self):
        super().__init__()

        self._ironic_connection = None

    @property
    def ironic_connection(self):
        if self._ironic_connection is None:
            # Ask get_sdk_adapter to raise ServiceUnavailable if the baremetal
            # service isn't ready yet. Consumers of ironic_connection are set
            # up to handle this and raise VirtDriverNotReady as appropriate.
            self._ironic_connection = utils.get_sdk_adapter(
                'baremetal',
                check_service=True,
            )
        return self._ironic_connection

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((404, 501))
    def index(self, req):
        context = req.environ['nova.context']
        context.can(bn_policies.BASE_POLICY_NAME % 'list', target={})

        nodes = []
        # proxy command to Ironic
        inodes = self.ironic_connection.nodes(details=True)
        for inode in inodes:
            node = {
                'id': inode.id,
                'interfaces': [],
                'host': 'IRONIC MANAGED',
                'task_state': inode.provision_state,
                'cpus': inode.properties.get('cpus', 0),
                'memory_mb': inode.properties.get('memory_mb', 0),
                'disk_gb': inode.properties.get('local_gb', 0),
            }
            nodes.append(node)

        return {'nodes': nodes}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((404, 501))
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(bn_policies.BASE_POLICY_NAME % 'show', target={})

        # proxy command to Ironic
        try:
            inode = self.ironic_connection.get_node(id)
        except sdk_exc.NotFoundException:
            msg = _("Node %s could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=msg)

        iports = self.ironic_connection.ports(node=id)
        node = {
            'id': inode.id,
            'interfaces': [],
            'host': 'IRONIC MANAGED',
            'task_state': inode.provision_state,
            'cpus': inode.properties.get('cpus', 0),
            'memory_mb': inode.properties.get('memory_mb', 0),
            'disk_gb': inode.properties.get('local_gb', 0),
            'instance_uuid': inode.instance_id,
        }
        for port in iports:
            node['interfaces'].append({'address': port.address})

        return {'node': node}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(400)
    def create(self, req, body):
        _no_ironic_proxy("node-create")

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(400)
    def delete(self, req, id):
        _no_ironic_proxy("node-delete")

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action('add_interface')
    @wsgi.expected_errors(400)
    def _add_interface(self, req, id, body):
        _no_ironic_proxy("port-create")

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.action('remove_interface')
    @wsgi.expected_errors(400)
    def _remove_interface(self, req, id, body):
        _no_ironic_proxy("port-delete")
