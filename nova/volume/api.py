# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Handles all requests relating to volumes.
"""

import functools

from nova.db import base
from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova.openstack.common import timeutils
import nova.policy
from nova import quota
from nova.scheduler import rpcapi as scheduler_rpcapi

volume_host_opt = cfg.BoolOpt('snapshot_same_host',
        default=True,
        help='Create volume from snapshot at the host where snapshot resides')

FLAGS = flags.FLAGS
FLAGS.register_opt(volume_host_opt)
flags.DECLARE('storage_availability_zone', 'nova.volume.manager')

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, volume)
    """
    @functools.wraps(func)
    def wrapped(self, context, target_obj, *args, **kwargs):
        check_policy(context, func.__name__, target_obj)
        return func(self, context, target_obj, *args, **kwargs)

    return wrapped


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    target.update(target_obj or {})
    _action = 'volume:%s' % action
    nova.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume manager."""

    def __init__(self, **kwargs):
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        super(API, self).__init__(**kwargs)

    def create(self, context, size, name, description, snapshot=None,
                     volume_type=None, metadata=None, availability_zone=None):
        check_policy(context, 'create')
        if snapshot is not None:
            if snapshot['status'] != "available":
                msg = _("status must be available")
                raise exception.InvalidSnapshot(reason=msg)
            if not size:
                size = snapshot['volume_size']

            snapshot_id = snapshot['id']
        else:
            snapshot_id = None

        def as_int(s):
            try:
                return int(s)
            except ValueError:
                return s

        # tolerate size as stringified int
        size = as_int(size)

        if not isinstance(size, int) or size <= 0:
            msg = (_("Volume size '%s' must be an integer and greater than 0")
                   % size)
            raise exception.InvalidInput(reason=msg)
        try:
            reservations = QUOTAS.reserve(context, volumes=1, gigabytes=size)
        except exception.OverQuota as e:
            overs = e.kwargs['overs']
            usages = e.kwargs['usages']
            quotas = e.kwargs['quotas']

            def _consumed(name):
                return (usages[name]['reserved'] + usages[name]['in_use'])

            pid = context.project_id
            if 'gigabytes' in overs:
                consumed = _consumed('gigabytes')
                quota = quotas['gigabytes']
                LOG.warn(_("Quota exceeded for %(pid)s, tried to create "
                           "%(size)sG volume (%(consumed)dG of %(quota)dG "
                           "already consumed)") % locals())
                raise exception.VolumeSizeTooLarge()
            elif 'volumes' in overs:
                consumed = _consumed('volumes')
                LOG.warn(_("Quota exceeded for %(pid)s, tried to create "
                           "volume (%(consumed)d volumes already consumed)")
                           % locals())
                raise exception.VolumeLimitExceeded(allowed=quotas['volumes'])

        if availability_zone is None:
            availability_zone = FLAGS.storage_availability_zone

        if volume_type is None:
            volume_type_id = None
        else:
            volume_type_id = volume_type.get('id', None)

        options = {
            'size': size,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'snapshot_id': snapshot_id,
            'availability_zone': availability_zone,
            'status': "creating",
            'attach_status': "detached",
            'display_name': name,
            'display_description': description,
            'volume_type_id': volume_type_id,
            'metadata': metadata,
            }

        volume = self.db.volume_create(context, options)
        self._cast_create_volume(context, volume['id'],
                                 snapshot_id, reservations)
        return volume

    def _cast_create_volume(self, context, volume_id,
                            snapshot_id, reservations):

        # NOTE(Rongze Zhu): It is a simple solution for bug 1008866
        # If snapshot_id is set, make the call create volume directly to
        # the volume host where the snapshot resides instead of passing it
        # through the scheduer. So snapshot can be copy to new volume.

        if snapshot_id and FLAGS.snapshot_same_host:
            snapshot_ref = self.db.snapshot_get(context, snapshot_id)
            src_volume_ref = self.db.volume_get(context,
                                                snapshot_ref['volume_id'])
            topic = rpc.queue_get_for(context,
                                      FLAGS.volume_topic,
                                      src_volume_ref['host'])
            rpc.cast(context,
                     topic,
                     {"method": "create_volume",
                      "args": {"volume_id": volume_id,
                               "snapshot_id": snapshot_id}})
        else:
            self.scheduler_rpcapi.create_volume(
                context, volume_id, snapshot_id, reservations)

    @wrap_check_policy
    def delete(self, context, volume):
        volume_id = volume['id']
        if not volume['host']:
            # NOTE(vish): scheduling failed, so delete it
            self.db.volume_destroy(context, volume_id)
            return
        if volume['status'] not in ["available", "error"]:
            msg = _("Volume status must be available or error")
            raise exception.InvalidVolume(reason=msg)

        snapshots = self.db.snapshot_get_all_for_volume(context, volume_id)
        if len(snapshots):
            msg = _("Volume still has %d dependent snapshots") % len(snapshots)
            raise exception.InvalidVolume(reason=msg)

        now = timeutils.utcnow()
        self.db.volume_update(context, volume_id, {'status': 'deleting',
                                                   'terminated_at': now})
        host = volume['host']
        rpc.cast(context,
                 rpc.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "delete_volume",
                  "args": {"volume_id": volume_id}})

    def get(self, context, volume_id):
        rv = self.db.volume_get(context, volume_id)
        volume = dict(rv.iteritems())
        check_policy(context, 'get', volume)
        return volume

    def get_all(self, context, search_opts=None):
        check_policy(context, 'get_all')

        if search_opts is None:
            search_opts = {}

        if (context.is_admin and 'all_tenants' in search_opts):
            # Need to remove all_tenants to pass the filtering below.
            del search_opts['all_tenants']
            volumes = self.db.volume_get_all(context)
        else:
            volumes = self.db.volume_get_all_by_project(context,
                                                        context.project_id)
        if search_opts:
            LOG.debug(_("Searching by: %s") % str(search_opts))

            def _check_metadata_match(volume, searchdict):
                volume_metadata = {}
                for i in volume.get('volume_metadata'):
                    volume_metadata[i['key']] = i['value']

                for k, v in searchdict.iteritems():
                    if (k not in volume_metadata.keys() or
                        volume_metadata[k] != v):
                        return False
                return True

            # search_option to filter_name mapping.
            filter_mapping = {'metadata': _check_metadata_match}

            result = []
            for volume in volumes:
                # go over all filters in the list
                for opt, values in search_opts.iteritems():
                    try:
                        filter_func = filter_mapping[opt]
                    except KeyError:
                        # no such filter - ignore it, go to next filter
                        continue
                    else:
                        if filter_func(volume, values):
                            result.append(volume)
                            break
            volumes = result
        return volumes

    def get_snapshot(self, context, snapshot_id):
        check_policy(context, 'get_snapshot')
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def get_all_snapshots(self, context, search_opts=None):
        check_policy(context, 'get_all_snapshots')

        search_opts = search_opts or {}

        if (context.is_admin and 'all_tenants' in search_opts):
            # Need to remove all_tenants to pass the filtering below.
            del search_opts['all_tenants']
            return self.db.snapshot_get_all(context)
        else:
            return self.db.snapshot_get_all_by_project(context,
                                                       context.project_id)

    @wrap_check_policy
    def check_attach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            msg = _("status must be available")
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == "attached":
            msg = _("already attached")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def check_detach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] == "available":
            msg = _("already detached")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def reserve_volume(self, context, volume):
        self.db.volume_update(context, volume['id'], {"status": "attaching"})

    @wrap_check_policy
    def unreserve_volume(self, context, volume):
        if volume['status'] == "attaching":
            self.db.volume_update(context,
                                  volume['id'],
                                  {"status": "available"})

    @wrap_check_policy
    def attach(self, context, volume, instance_uuid, mountpoint):
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                        {"method": "attach_volume",
                         "args": {"volume_id": volume['id'],
                                  "instance_uuid": instance_uuid,
                                  "mountpoint": mountpoint}})

    @wrap_check_policy
    def detach(self, context, volume):
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                 {"method": "detach_volume",
                  "args": {"volume_id": volume['id']}})

    @wrap_check_policy
    def initialize_connection(self, context, volume, connector):
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                        {"method": "initialize_connection",
                         "args": {"volume_id": volume['id'],
                                  "connector": connector}})

    @wrap_check_policy
    def terminate_connection(self, context, volume, connector):
        self.unreserve_volume(context, volume)
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                        {"method": "terminate_connection",
                         "args": {"volume_id": volume['id'],
                                  "connector": connector}})

    def _create_snapshot(self, context, volume, name, description,
                         force=False):
        check_policy(context, 'create_snapshot', volume)

        if ((not force) and (volume['status'] != "available")):
            msg = _("must be available")
            raise exception.InvalidVolume(reason=msg)

        options = {
            'volume_id': volume['id'],
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': "creating",
            'progress': '0%',
            'volume_size': volume['size'],
            'display_name': name,
            'display_description': description}

        snapshot = self.db.snapshot_create(context, options)
        host = volume['host']
        rpc.cast(context,
                 rpc.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "create_snapshot",
                  "args": {"volume_id": volume['id'],
                           "snapshot_id": snapshot['id']}})
        return snapshot

    def create_snapshot(self, context, volume, name, description):
        return self._create_snapshot(context, volume, name, description,
                                     False)

    def create_snapshot_force(self, context, volume, name, description):
        return self._create_snapshot(context, volume, name, description,
                                     True)

    @wrap_check_policy
    def delete_snapshot(self, context, snapshot):
        if snapshot['status'] not in ["available", "error"]:
            msg = _("Volume Snapshot status must be available or error")
            raise exception.InvalidVolume(reason=msg)
        self.db.snapshot_update(context, snapshot['id'],
                                {'status': 'deleting'})
        volume = self.db.volume_get(context, snapshot['volume_id'])
        host = volume['host']
        rpc.cast(context,
                 rpc.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "delete_snapshot",
                  "args": {"snapshot_id": snapshot['id']}})

    @wrap_check_policy
    def get_volume_metadata(self, context, volume):
        """Get all metadata associated with a volume."""
        rv = self.db.volume_metadata_get(context, volume['id'])
        return dict(rv.iteritems())

    @wrap_check_policy
    def delete_volume_metadata(self, context, volume, key):
        """Delete the given metadata item from a volume."""
        self.db.volume_metadata_delete(context, volume['id'], key)

    @wrap_check_policy
    def update_volume_metadata(self, context, volume, metadata, delete=False):
        """Updates or creates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            _metadata = self.get_volume_metadata(context, volume['id'])
            _metadata.update(metadata)

        self.db.volume_metadata_update(context, volume['id'], _metadata, True)
        return _metadata

    def get_volume_metadata_value(self, volume, key):
        """Get value of particular metadata key."""
        metadata = volume.get('volume_metadata')
        if metadata:
            for i in volume['volume_metadata']:
                if i['key'] == key:
                    return i['value']
        return None
