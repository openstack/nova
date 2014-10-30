#   Copyright 2013 OpenStack Foundation
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

"""The Extended Volumes API extension."""
from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas.v3 import extended_volumes
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception
from nova.i18n import _
from nova import objects
from nova import volume

ALIAS = "os-extended-volumes"
authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)
authorize_attach = extensions.extension_authorizer('compute',
                                                   'v3:%s:attach' % ALIAS)
authorize_detach = extensions.extension_authorizer('compute',
                                                   'v3:%s:detach' % ALIAS)
authorize_swap = extensions.extension_authorizer('compute',
                                                 'v3:%s:swap' % ALIAS)


class ExtendedVolumesController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedVolumesController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.volume_api = volume.API()

    def _extend_server(self, context, server, instance):
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance['uuid'])
        volume_ids = [bdm['volume_id'] for bdm in bdms if bdm['volume_id']]
        key = "%s:volumes_attached" % ExtendedVolumes.alias
        server[key] = [{'id': volume_id} for volume_id in volume_ids]

    @wsgi.response(202)
    @extensions.expected_errors((400, 404, 409))
    @wsgi.action('swap_volume_attachment')
    @validation.schema(extended_volumes.swap_volume_attachment)
    def swap(self, req, id, body):
        context = req.environ['nova.context']
        authorize_swap(context)

        old_volume_id = body['swap_volume_attachment']['old_volume_id']
        new_volume_id = body['swap_volume_attachment']['new_volume_id']

        try:
            old_volume = self.volume_api.get(context, old_volume_id)
            new_volume = self.volume_api.get(context, new_volume_id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        instance = common.get_instance(self.compute_api, context, id,
                                       want_objects=True)
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        found = False
        try:
            for bdm in bdms:
                if bdm.volume_id != old_volume_id:
                    continue
                try:
                    self.compute_api.swap_volume(context, instance, old_volume,
                                                 new_volume)
                    found = True
                    break
                except exception.VolumeUnattached:
                    # The volume is not attached.  Treat it as NotFound
                    # by falling through.
                    pass
                except exception.InvalidVolume as e:
                    raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                                                              'swap_volume',
                                                              id)

        if not found:
            msg = _("The volume was either invalid or not attached to the "
                    "instance.")
            raise exc.HTTPNotFound(explanation=msg)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance)

    @extensions.expected_errors((400, 404, 409))
    @wsgi.response(202)
    @wsgi.action('attach')
    @validation.schema(extended_volumes.attach)
    def attach(self, req, id, body):
        server_id = id
        context = req.environ['nova.context']
        authorize_attach(context)

        volume_id = body['attach']['volume_id']
        device = body['attach'].get('device')
        disk_bus = body['attach'].get('disk_bus')
        device_type = body['attach'].get('device_type')

        instance = common.get_instance(self.compute_api, context, server_id,
                                       want_objects=True)
        try:
            self.compute_api.attach_volume(context, instance,
                                           volume_id, device,
                                           disk_bus=disk_bus,
                                           device_type=device_type)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'attach_volume', server_id)
        except exception.InvalidVolume as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InvalidDevicePath as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @extensions.expected_errors((400, 403, 404, 409))
    @wsgi.response(202)
    @wsgi.action('detach')
    @validation.schema(extended_volumes.detach)
    def detach(self, req, id, body):
        server_id = id
        context = req.environ['nova.context']
        authorize_detach(context)

        volume_id = body['detach']['volume_id']

        instance = common.get_instance(self.compute_api, context, server_id,
                                       want_objects=True)
        try:
            volume = self.volume_api.get(context, volume_id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
        if not bdms:
            msg = _("Volume %(volume_id)s is not attached to the "
                    "instance %(server_id)s") % {'server_id': server_id,
                                                 'volume_id': volume_id}
            raise exc.HTTPNotFound(explanation=msg)

        for bdm in bdms:
            if bdm.volume_id != volume_id:
                continue
            if bdm.is_root:
                msg = _("Can't detach root device volume")
                raise exc.HTTPForbidden(explanation=msg)
            try:
                self.compute_api.detach_volume(context, instance, volume)
                break
            except exception.VolumeUnattached:
                # The volume is not attached.  Treat it as NotFound
                # by falling through.
                pass
            except exception.InvalidVolume as e:
                raise exc.HTTPBadRequest(explanation=e.format_message())
            except exception.InstanceIsLocked as e:
                raise exc.HTTPConflict(explanation=e.format_message())
            except exception.InstanceInvalidState as state_error:
                common.raise_http_conflict_for_instance_invalid_state(
                    state_error, 'detach_volume', server_id)
        else:
            msg = _("Volume %(volume_id)s is not attached to the "
                    "instance %(server_id)s") % {'server_id': server_id,
                                                 'volume_id': volume_id}
            raise exc.HTTPNotFound(explanation=msg)


class ExtendedVolumes(extensions.V3APIExtensionBase):
    """Extended Volumes support."""

    name = "ExtendedVolumes"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = ExtendedVolumesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
