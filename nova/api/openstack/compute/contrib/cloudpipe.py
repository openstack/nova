#   Copyright 2011 Openstack, LLC.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""Connect your vlan to the world."""

import os

from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack import extensions
from nova.auth import manager
from nova.cloudpipe import pipelib
from nova import compute
from nova.compute import vm_states
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import network
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'cloudpipe')


class CloudpipeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        return xmlutil.MasterTemplate(xmlutil.make_flat_dict('cloudpipe'), 1)


class CloudpipesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('cloudpipes')
        elem = xmlutil.make_flat_dict('cloudpipe', selector='cloudpipes',
                                      subselector='cloudpipe')
        root.append(elem)
        return xmlutil.MasterTemplate(root, 1)


class CloudpipeController(object):
    """Handle creating and listing cloudpipe instances."""

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        self.auth_manager = manager.AuthManager()
        self.cloudpipe = pipelib.CloudPipe()
        self.setup()

    def setup(self):
        """Ensure the keychains and folders exist."""
        # NOTE(vish): One of the drawbacks of doing this in the api is
        #             the keys will only be on the api node that launched
        #             the cloudpipe.
        if not os.path.exists(FLAGS.keys_path):
            os.makedirs(FLAGS.keys_path)

    def _get_all_cloudpipes(self, context):
        """Get all cloudpipes"""
        return [instance for instance in self.compute_api.get_all(context)
                if instance['image_ref'] == str(FLAGS.vpn_image_id)
                and instance['vm_state'] != vm_states.DELETED]

    def _get_cloudpipe_for_project(self, context, project_id):
        """Get the cloudpipe instance for a project ID."""
        cloudpipes = self._get_all_cloudpipes(context) or [None]
        return cloudpipes[0]

    def _get_ip_and_port(self, instance):
        pass

    def _vpn_dict(self, context, project_id, instance):
        elevated = context.elevated()
        rv = {'project_id': project_id}
        if not instance:
            rv['state'] = 'pending'
            return rv
        rv['instance_id'] = instance['uuid']
        rv['created_at'] = utils.isotime(instance['created_at'])
        nw_info = common.get_nw_info_for_instance(elevated, instance)
        if not nw_info:
            return rv
        vif = nw_info[0]
        ips = [ip for ip in vif.fixed_ips() if ip['version'] == 4]
        if ips:
            rv['internal_ip'] = ips[0]['address']
        network = self.network_api.get(elevated, vif['network']['id'])
        if network:
            vpn_ip = network['vpn_public_address']
            vpn_port = network['vpn_public_port']
            rv['public_ip'] = vpn_ip
            rv['public_port'] = vpn_port
            if vpn_ip and vpn_port:
                if utils.vpn_ping(vpn_ip, vpn_port):
                    rv['state'] = 'running'
                else:
                    rv['state'] = 'down'
            else:
                rv['state'] = 'invalid'
        return rv

    @wsgi.serializers(xml=CloudpipeTemplate)
    def create(self, req, body):
        """Create a new cloudpipe instance, if none exists.

        Parameters: {cloudpipe: {'project_id': ''}}
        """

        context = req.environ['nova.context']
        authorize(context)
        params = body.get('cloudpipe', {})
        project_id = params.get('project_id', context.project_id)
        # NOTE(vish): downgrade to project context. Note that we keep
        #             the same token so we can still talk to glance
        context.project_id = project_id
        context.user_id = 'project-vpn'
        context.is_admin = False
        context.roles = []
        instance = self._get_cloudpipe_for_project(context, project_id)
        if not instance:
            try:
                result = self.cloudpipe.launch_vpn_instance(context)
                instance = result[0][0]
            except db.NoMoreNetworks:
                msg = _("Unable to claim IP for VPN instances, ensure it "
                        "isn't running, and try again in a few minutes")
                raise exception.HTTPBadRequest(explanation=msg)
        return {'instance_id': instance['uuid']}

    @wsgi.serializers(xml=CloudpipesTemplate)
    def index(self, req):
        """List running cloudpipe instances."""
        context = req.environ['nova.context']
        authorize(context)
        vpns = [self._vpn_dict(context, x['project_id'], x)
                for x in self._get_all_cloudpipes(context)]
        return {'cloudpipes': vpns}


class Cloudpipe(extensions.ExtensionDescriptor):
    """Adds actions to create cloudpipe instances.

    When running with the Vlan network mode, you need a mechanism to route
    from the public Internet to your vlans.  This mechanism is known as a
    cloudpipe.

    At the time of creating this class, only OpenVPN is supported.  Support for
    a SSH Bastion host is forthcoming.
    """

    name = "Cloudpipe"
    alias = "os-cloudpipe"
    namespace = "http://docs.openstack.org/compute/ext/cloudpipe/api/v1.1"
    updated = "2011-12-16T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('os-cloudpipe',
                                           CloudpipeController())
        resources.append(res)
        return resources
