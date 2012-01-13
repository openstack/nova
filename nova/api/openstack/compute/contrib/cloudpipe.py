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
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.openstack.compute.contrib.cloudpipe")


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
        self.auth_manager = manager.AuthManager()
        self.cloudpipe = pipelib.CloudPipe()
        self.setup()

    def setup(self):
        """Ensure the keychains and folders exist."""
        # TODO(todd): this was copyed from api.ec2.cloud
        # FIXME(ja): this should be moved to a nova-manage command,
        # if not setup throw exceptions instead of running
        # Create keys folder, if it doesn't exist
        if not os.path.exists(FLAGS.keys_path):
            os.makedirs(FLAGS.keys_path)
        # Gen root CA, if we don't have one
        root_ca_path = os.path.join(FLAGS.ca_path, FLAGS.ca_file)
        if not os.path.exists(root_ca_path):
            genrootca_sh_path = os.path.join(os.path.dirname(__file__),
                                             os.path.pardir,
                                             os.path.pardir,
                                             'CA',
                                             'genrootca.sh')

            start = os.getcwd()
            if not os.path.exists(FLAGS.ca_path):
                os.makedirs(FLAGS.ca_path)
            os.chdir(FLAGS.ca_path)
            # TODO(vish): Do this with M2Crypto instead
            utils.runthis(_("Generating root CA: %s"), "sh", genrootca_sh_path)
            os.chdir(start)

    def _get_cloudpipe_for_project(self, context, project_id):
        """Get the cloudpipe instance for a project ID."""
        # NOTE(todd): this should probably change to compute_api.get_all
        #             or db.instance_get_project_vpn
        for instance in db.instance_get_all_by_project(context, project_id):
            if (instance['image_id'] == str(FLAGS.vpn_image_id)
                and instance['vm_state'] != vm_states.DELETED):
                return instance

    def _vpn_dict(self, project, vpn_instance):
        rv = {'project_id': project.id,
              'public_ip': project.vpn_ip,
              'public_port': project.vpn_port}
        if vpn_instance:
            rv['instance_id'] = vpn_instance['uuid']
            rv['created_at'] = utils.isotime(vpn_instance['created_at'])
            address = vpn_instance.get('fixed_ip', None)
            if address:
                rv['internal_ip'] = address['address']
            if project.vpn_ip and project.vpn_port:
                if utils.vpn_ping(project.vpn_ip, project.vpn_port):
                    rv['state'] = 'running'
                else:
                    rv['state'] = 'down'
            else:
                rv['state'] = 'invalid'
        else:
            rv['state'] = 'pending'
        return rv

    @wsgi.serializers(xml=CloudpipeTemplate)
    def create(self, req, body):
        """Create a new cloudpipe instance, if none exists.

        Parameters: {cloudpipe: {project_id: XYZ}}
        """

        ctxt = req.environ['nova.context']
        params = body.get('cloudpipe', {})
        project_id = params.get('project_id', ctxt.project_id)
        instance = self._get_cloudpipe_for_project(ctxt, project_id)
        if not instance:
            proj = self.auth_manager.get_project(project_id)
            user_id = proj.project_manager_id
            try:
                self.cloudpipe.launch_vpn_instance(project_id, user_id)
            except db.NoMoreNetworks:
                msg = _("Unable to claim IP for VPN instances, ensure it "
                        "isn't running, and try again in a few minutes")
                raise exception.ApiError(msg)
            instance = self._get_cloudpipe_for_project(ctxt, proj)
        return {'instance_id': instance['uuid']}

    @wsgi.serializers(xml=CloudpipesTemplate)
    def index(self, req):
        """Show admins the list of running cloudpipe instances."""
        context = req.environ['nova.context']
        vpns = []
        # TODO(todd): could use compute_api.get_all with admin context?
        for project in self.auth_manager.get_projects():
            instance = self._get_cloudpipe_for_project(context, project.id)
            vpns.append(self._vpn_dict(project, instance))
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
    admin_only = True

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('os-cloudpipe',
                                           CloudpipeController())
        resources.append(res)
        return resources
