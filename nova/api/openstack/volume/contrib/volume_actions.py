#   Copyright 2012 OpenStack, LLC.
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

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import common as rpc_common
from nova import utils
from nova import volume


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def authorize(context, action_name):
    action = 'volume_actions:%s' % action_name
    extensions.extension_authorizer('volume', action)(context)


class VolumeToImageSerializer(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('os-volume_upload_image',
                                       selector='os-volume_upload_image')
        root.set('id')
        root.set('updated_at')
        root.set('status')
        root.set('display_description')
        root.set('size')
        root.set('volume_type')
        root.set('image_id')
        root.set('container_format')
        root.set('disk_format')
        root.set('image_name')
        return xmlutil.MasterTemplate(root, 1)


class VolumeToImageDeserializer(wsgi.XMLDeserializer):
    """Deserializer to handle xml-formatted requests"""
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        action_node = dom.childNodes[0]
        action_name = action_node.tagName

        action_data = {}
        attributes = ["force", "image_name", "container_format", "disk_format"]
        for attr in attributes:
            if action_node.hasAttribute(attr):
                action_data[attr] = action_node.getAttribute(attr)
        if 'force' in action_data and action_data['force'] == 'True':
            action_data['force'] = True
        return {'body': {action_name: action_data}}


class VolumeActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeActionsController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    @wsgi.response(202)
    @wsgi.action('os-volume_upload_image')
    @wsgi.serializers(xml=VolumeToImageSerializer)
    @wsgi.deserializers(xml=VolumeToImageDeserializer)
    def _volume_upload_image(self, req, id, body):
        """Uploads the specified volume to image service."""
        context = req.environ['nova.context']
        try:
            params = body['os-volume_upload_image']
        except (TypeError, KeyError):
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if not params.get("image_name"):
            msg = _("No image_name was specified in request.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        force = params.get('force', False)
        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound, error:
            raise webob.exc.HTTPNotFound(explanation=unicode(error))
        authorize(context, "upload_image")
        image_metadata = {"container_format": params.get("container_format",
                                                         "bare"),
                          "disk_format": params.get("disk_format", "raw"),
                          "name": params["image_name"]}
        try:
            response = self.volume_api.copy_volume_to_image(context,
                                                            volume,
                                                            image_metadata,
                                                            force)
        except exception.InvalidVolume, error:
            raise webob.exc.HTTPBadRequest(explanation=unicode(error))
        except ValueError, error:
            raise webob.exc.HTTPBadRequest(explanation=unicode(error))
        except rpc_common.RemoteError as error:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': error.exc_type,
                                                 'err_msg': error.value}
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return {'os-volume_upload_image': response}


class Volume_actions(extensions.ExtensionDescriptor):
    """Enable volume actions
    """

    name = "VolumeActions"
    alias = "os-volume-actions"
    namespace = "http://docs.openstack.org/volume/ext/volume-actions/api/v1.1"
    updated = "2012-05-31T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeActionsController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]
