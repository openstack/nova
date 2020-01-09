# Copyright 2013 Red Hat, Inc.
# Copyright 2014 IBM Corp.
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

"""The Assisted volume snapshots extension."""

from oslo_serialization import jsonutils
import six
from webob import exc

from nova.api.openstack.compute.schemas import assisted_volume_snapshots
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.policies import assisted_volume_snapshots as avs_policies


class AssistedVolumeSnapshotsController(wsgi.Controller):
    """The Assisted volume snapshots API controller for the OpenStack API."""

    def __init__(self):
        super(AssistedVolumeSnapshotsController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.expected_errors(400)
    @validation.schema(assisted_volume_snapshots.snapshots_create)
    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['nova.context']
        context.can(avs_policies.POLICY_ROOT % 'create', target={})

        snapshot = body['snapshot']
        create_info = snapshot['create_info']
        volume_id = snapshot['volume_id']

        try:
            return self.compute_api.volume_snapshot_create(context, volume_id,
                                                           create_info)
        except (exception.VolumeBDMNotFound,
                exception.VolumeBDMIsMultiAttach,
                exception.InvalidVolume) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except (exception.InstanceInvalidState,
                exception.InstanceNotReady) as e:
            # TODO(mriedem) InstanceInvalidState and InstanceNotReady would
            # normally result in a 409 but that would require bumping the
            # microversion, which we should just do in a single microversion
            # across all APIs when we fix status code wrinkles.
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @wsgi.response(204)
    @validation.query_schema(assisted_volume_snapshots.delete_query_275,
                             '2.75')
    @validation.query_schema(assisted_volume_snapshots.delete_query, '2.0',
                             '2.74')
    @wsgi.expected_errors((400, 404))
    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['nova.context']
        context.can(avs_policies.POLICY_ROOT % 'delete', target={})

        delete_metadata = {}
        delete_metadata.update(req.GET)

        try:
            delete_info = jsonutils.loads(delete_metadata['delete_info'])
            volume_id = delete_info['volume_id']
        except (KeyError, ValueError) as e:
            raise exc.HTTPBadRequest(explanation=six.text_type(e))

        try:
            self.compute_api.volume_snapshot_delete(context, volume_id,
                    id, delete_info)
        except (exception.VolumeBDMNotFound,
                exception.InvalidVolume) as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        except exception.NotFound as e:
            return exc.HTTPNotFound(explanation=e.format_message())
        except (exception.InstanceInvalidState,
                exception.InstanceNotReady) as e:
            # TODO(mriedem) InstanceInvalidState and InstanceNotReady would
            # normally result in a 409 but that would require bumping the
            # microversion, which we should just do in a single microversion
            # across all APIs when we fix status code wrinkles.
            raise exc.HTTPBadRequest(explanation=e.format_message())
