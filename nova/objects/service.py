#    Copyright 2013 IBM Corp.
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

from oslo_log import log as logging
from oslo_utils import uuidutils
from oslo_utils import versionutils

from nova import availability_zones
from nova import context as nova_context
from nova.db import api as db
from nova import exception
from nova.notifications.objects import base as notification
from nova.notifications.objects import service as service_notification
from nova import objects
from nova.objects import base
from nova.objects import fields


LOG = logging.getLogger(__name__)


# NOTE(danms): This is the global service version counter
SERVICE_VERSION = 51


# NOTE(danms): This is our SERVICE_VERSION history. The idea is that any
# time we bump the version, we will put an entry here to record the change,
# along with any pertinent data. For things that we can programatically
# detect that need a bump, we put something in _collect_things() below to
# assemble a dict of things we can check. For example, we pretty much always
# want to consider the compute RPC API version a thing that requires a service
# bump so that we can drive version pins from it. We could include other
# service RPC versions at some point, minimum object versions, etc.
#
# The TestServiceVersion test will fail if the calculated set of
# things differs from the value in the last item of the list below,
# indicating that a version bump is needed.
#
# Also note that there are other reasons we may want to bump this,
# which will not be caught by the test. An example of this would be
# triggering (or disabling) an online data migration once all services
# in the cluster are at the same level.
#
# If a version bump is required for something mechanical, just document
# that generic thing here (like compute RPC version bumps). No need to
# replicate the details from compute/rpcapi.py here. However, for more
# complex service interactions, extra detail should be provided
SERVICE_VERSION_HISTORY = (
    # Version 0: Pre-history
    {'compute_rpc': '4.0'},

    # Version 1: Introduction of SERVICE_VERSION
    {'compute_rpc': '4.4'},
    # Version 2: Compute RPC version 4.5
    {'compute_rpc': '4.5'},
    # Version 3: Compute RPC version 4.6
    {'compute_rpc': '4.6'},
    # Version 4: Add PciDevice.parent_addr (data migration needed)
    {'compute_rpc': '4.6'},
    # Version 5: Compute RPC version 4.7
    {'compute_rpc': '4.7'},
    # Version 6: Compute RPC version 4.8
    {'compute_rpc': '4.8'},
    # Version 7: Compute RPC version 4.9
    {'compute_rpc': '4.9'},
    # Version 8: Compute RPC version 4.10
    {'compute_rpc': '4.10'},
    # Version 9: Compute RPC version 4.11
    {'compute_rpc': '4.11'},
    # Version 10: Compute node conversion to Inventories
    {'compute_rpc': '4.11'},
    # Version 11: Compute RPC version 4.12
    {'compute_rpc': '4.12'},
    # Version 12: The network APIs and compute manager support a NetworkRequest
    # object where the network_id value is 'auto' or 'none'. BuildRequest
    # objects are populated by nova-api during instance boot.
    {'compute_rpc': '4.12'},
    # Version 13: Compute RPC version 4.13
    {'compute_rpc': '4.13'},
    # Version 14: The compute manager supports setting device tags.
    {'compute_rpc': '4.13'},
    # Version 15: Indicate that nova-conductor will stop a boot if BuildRequest
    # is deleted before RPC to nova-compute.
    {'compute_rpc': '4.13'},
    # Version 16: Indicate that nova-compute will refuse to start if it doesn't
    # have a placement section configured.
    {'compute_rpc': '4.13'},
    # Version 17: Add 'reserve_volume' to the boot from volume flow and
    # remove 'check_attach'. The service version bump is needed to fall back to
    # the old check in the API as the old computes fail if the volume is moved
    # to 'attaching' state by reserve.
    {'compute_rpc': '4.13'},
    # Version 18: Compute RPC version 4.14
    {'compute_rpc': '4.14'},
    # Version 19: Compute RPC version 4.15
    {'compute_rpc': '4.15'},
    # Version 20: Compute RPC version 4.16
    {'compute_rpc': '4.16'},
    # Version 21: Compute RPC version 4.17
    {'compute_rpc': '4.17'},
    # Version 22: A marker for the behaviour change of auto-healing code on the
    # compute host regarding allocations against an instance
    {'compute_rpc': '4.17'},
    # Version 23: Compute hosts allow pre-creation of the migration object
    # for cold migration.
    {'compute_rpc': '4.18'},
    # Version 24: Add support for Cinder v3 attach/detach API.
    {'compute_rpc': '4.18'},
    # Version 25: Compute hosts allow migration-based allocations
    # for live migration.
    {'compute_rpc': '4.18'},
    # Version 26: Adds a 'host_list' parameter to build_and_run_instance()
    {'compute_rpc': '4.19'},
    # Version 27: Compute RPC version 4.20; adds multiattach argument to
    # reserve_block_device_name().
    {'compute_rpc': '4.20'},
    # Version 28: Adds a 'host_list' parameter to prep_resize()
    {'compute_rpc': '4.21'},
    # Version 29: Compute RPC version 4.22
    {'compute_rpc': '4.22'},
    # Version 30: Compute RPC version 5.0
    {'compute_rpc': '5.0'},
    # Version 31: The compute manager checks if 'trusted_certs' are supported
    {'compute_rpc': '5.0'},
    # Version 32: Add 'file_backed_memory' support. The service version bump is
    # needed to allow the destination of a live migration to reject the
    # migration if 'file_backed_memory' is enabled and the source does not
    # support 'file_backed_memory'
    {'compute_rpc': '5.0'},
    # Version 33: Add support for check on the server group with
    # 'max_server_per_host' rules
    {'compute_rpc': '5.0'},
    # Version 34: Adds support to abort queued/preparing live migrations.
    {'compute_rpc': '5.0'},
    # Version 35: Indicates that nova-compute supports live migration with
    # ports bound early on the destination host using VIFMigrateData.
    {'compute_rpc': '5.0'},
    # Version 36: Indicates that nova-compute supports specifying volume
    # type when booting a volume-backed server.
    {'compute_rpc': '5.0'},
    # Version 37: prep_resize takes a RequestSpec object
    {'compute_rpc': '5.1'},
    # Version 38: set_host_enabled reflects COMPUTE_STATUS_DISABLED trait
    {'compute_rpc': '5.1'},
    # Version 39: resize_instance, finish_resize, revert_resize,
    # finish_revert_resize, unshelve_instance takes a RequestSpec object
    {'compute_rpc': '5.2'},
    # Version 40: Add migration and limits parameters to
    # check_can_live_migrate_destination(), new
    # drop_move_claim_at_destination() method, and numa_live_migration
    # parameter to check_can_live_migrate_source()
    {'compute_rpc': '5.3'},
    # Version 41: Add cache_images() to compute rpcapi (version 5.4)
    {'compute_rpc': '5.4'},
    # Version 42: Compute RPC version 5.5; +prep_snapshot_based_resize_at_dest
    {'compute_rpc': '5.5'},
    # Version 43: Compute RPC version 5.6: prep_snapshot_based_resize_at_source
    {'compute_rpc': '5.6'},
    # Version 44: Compute RPC version 5.7: finish_snapshot_based_resize_at_dest
    {'compute_rpc': '5.7'},
    # Version 45: Compute RPC v5.8: confirm_snapshot_based_resize_at_source
    {'compute_rpc': '5.8'},
    # Version 46: Compute RPC v5.9: revert_snapshot_based_resize_at_dest
    {'compute_rpc': '5.9'},
    # Version 47: Compute RPC v5.10:
    # finish_revert_snapshot_based_resize_at_source
    {'compute_rpc': '5.10'},
    # Version 48: Drivers report COMPUTE_SAME_HOST_COLD_MIGRATE trait.
    {'compute_rpc': '5.10'},
    # Version 49: Compute now support server move operations with qos ports
    {'compute_rpc': '5.10'},
    # Version 50: Compute RPC v5.11:
    # Add accel_uuids (accelerator requests) param to build_and_run_instance
    {'compute_rpc': '5.11'},
    # Version 51: Add support for live migration with vpmem
    {'compute_rpc': '5.11'},
)


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class Service(base.NovaPersistentObject, base.NovaObject,
              base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added compute_node nested object
    # Version 1.2: String attributes updated to support unicode
    # Version 1.3: ComputeNode version 1.5
    # Version 1.4: Added use_slave to get_by_compute_host
    # Version 1.5: ComputeNode version 1.6
    # Version 1.6: ComputeNode version 1.7
    # Version 1.7: ComputeNode version 1.8
    # Version 1.8: ComputeNode version 1.9
    # Version 1.9: ComputeNode version 1.10
    # Version 1.10: Changes behaviour of loading compute_node
    # Version 1.11: Added get_by_host_and_binary
    # Version 1.12: ComputeNode version 1.11
    # Version 1.13: Added last_seen_up
    # Version 1.14: Added forced_down
    # Version 1.15: ComputeNode version 1.12
    # Version 1.16: Added version
    # Version 1.17: ComputeNode version 1.13
    # Version 1.18: ComputeNode version 1.14
    # Version 1.19: Added get_minimum_version()
    # Version 1.20: Added get_minimum_version_multi()
    # Version 1.21: Added uuid
    # Version 1.22: Added get_by_uuid()
    VERSION = '1.22'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(),
        'host': fields.StringField(nullable=True),
        'binary': fields.StringField(nullable=True),
        'topic': fields.StringField(nullable=True),
        'report_count': fields.IntegerField(),
        'disabled': fields.BooleanField(),
        'disabled_reason': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'compute_node': fields.ObjectField('ComputeNode'),
        'last_seen_up': fields.DateTimeField(nullable=True),
        'forced_down': fields.BooleanField(),
        'version': fields.IntegerField(),
    }

    _MIN_VERSION_CACHE = {}
    _SERVICE_VERSION_CACHING = False

    def __init__(self, *args, **kwargs):
        # NOTE(danms): We're going against the rules here and overriding
        # init. The reason is that we want to *ensure* that we're always
        # setting the current service version on our objects, overriding
        # whatever else might be set in the database, or otherwise (which
        # is the normal reason not to override init).
        #
        # We also need to do this here so that it's set on the client side
        # all the time, such that create() and save() operations will
        # include the current service version.
        if 'version' in kwargs:
            raise exception.ObjectActionError(
                action='init',
                reason='Version field is immutable')

        super(Service, self).__init__(*args, **kwargs)
        self.version = SERVICE_VERSION

    def obj_make_compatible_from_manifest(self, primitive, target_version,
                                          version_manifest):
        super(Service, self).obj_make_compatible_from_manifest(
            primitive, target_version, version_manifest)
        _target_version = versionutils.convert_version_to_tuple(target_version)
        if _target_version < (1, 21) and 'uuid' in primitive:
            del primitive['uuid']
        if _target_version < (1, 16) and 'version' in primitive:
            del primitive['version']
        if _target_version < (1, 14) and 'forced_down' in primitive:
            del primitive['forced_down']
        if _target_version < (1, 13) and 'last_seen_up' in primitive:
            del primitive['last_seen_up']
        if _target_version < (1, 10):
            # service.compute_node was not lazy-loaded, we need to provide it
            # when called
            self._do_compute_node(self._context, primitive,
                                  version_manifest)

    def _do_compute_node(self, context, primitive, version_manifest):
        try:
            target_version = version_manifest['ComputeNode']
            # NOTE(sbauza): Ironic deployments can have multiple
            # nodes for the same service, but for keeping same behaviour,
            # returning only the first elem of the list
            compute = objects.ComputeNodeList.get_all_by_host(
                context, primitive['host'])[0]
        except Exception:
            return
        primitive['compute_node'] = compute.obj_to_primitive(
            target_version=target_version,
            version_manifest=version_manifest)

    @staticmethod
    def _from_db_object(context, service, db_service):
        allow_missing = ('availability_zone',)
        for key in service.fields:
            if key in allow_missing and key not in db_service:
                continue
            if key == 'compute_node':
                #  NOTE(sbauza); We want to only lazy-load compute_node
                continue
            elif key == 'version':
                # NOTE(danms): Special handling of the version field, since
                # it is read_only and set in our init.
                setattr(service, base.get_attrname(key), db_service[key])
            elif key == 'uuid' and not db_service.get(key):
                # Leave uuid off the object if undefined in the database
                # so that it will be generated below.
                continue
            else:
                service[key] = db_service[key]

        service._context = context
        service.obj_reset_changes()

        return service

    def obj_load_attr(self, attrname):
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        LOG.debug("Lazy-loading '%(attr)s' on %(name)s id %(id)s",
                  {'attr': attrname,
                   'name': self.obj_name(),
                   'id': self.id,
                   })
        if attrname != 'compute_node':
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)
        if self.binary == 'nova-compute':
            # Only n-cpu services have attached compute_node(s)
            compute_nodes = objects.ComputeNodeList.get_all_by_host(
                self._context, self.host)
        else:
            # NOTE(sbauza); Previous behaviour was raising a ServiceNotFound,
            # we keep it for backwards compatibility
            raise exception.ServiceNotFound(service_id=self.id)
        # NOTE(sbauza): Ironic deployments can have multiple nodes
        # for the same service, but for keeping same behaviour, returning only
        # the first elem of the list
        self.compute_node = compute_nodes[0]

    @base.remotable_classmethod
    def get_by_id(cls, context, service_id):
        db_service = db.service_get(context, service_id)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, service_uuid):
        db_service = db.service_get_by_uuid(context, service_uuid)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_host_and_topic(cls, context, host, topic):
        db_service = db.service_get_by_host_and_topic(context, host, topic)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_host_and_binary(cls, context, host, binary):
        try:
            db_service = db.service_get_by_host_and_binary(context,
                                                           host, binary)
        except exception.HostBinaryNotFound:
            return
        return cls._from_db_object(context, cls(), db_service)

    @staticmethod
    @db.select_db_reader_mode
    def _db_service_get_by_compute_host(context, host, use_slave=False):
        return db.service_get_by_compute_host(context, host)

    @base.remotable_classmethod
    def get_by_compute_host(cls, context, host, use_slave=False):
        db_service = cls._db_service_get_by_compute_host(context, host,
                                                         use_slave=use_slave)
        return cls._from_db_object(context, cls(), db_service)

    # NOTE(ndipanov): This is deprecated and should be removed on the next
    # major version bump
    @base.remotable_classmethod
    def get_by_args(cls, context, host, binary):
        db_service = db.service_get_by_host_and_binary(context, host, binary)
        return cls._from_db_object(context, cls(), db_service)

    def _check_minimum_version(self):
        """Enforce that we are not older that the minimum version.

        This is a loose check to avoid creating or updating our service
        record if we would do so with a version that is older that the current
        minimum of all services. This could happen if we were started with
        older code by accident, either due to a rollback or an old and
        un-updated node suddenly coming back onto the network.

        There is technically a race here between the check and the update,
        but since the minimum version should always roll forward and never
        backwards, we don't need to worry about doing it atomically. Further,
        the consequence for getting this wrong is minor, in that we'll just
        fail to send messages that other services understand.
        """
        if not self.obj_attr_is_set('version'):
            return
        if not self.obj_attr_is_set('binary'):
            return
        minver = self.get_minimum_version(self._context, self.binary)
        if minver > self.version:
            raise exception.ServiceTooOld(thisver=self.version,
                                          minver=minver)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        self._check_minimum_version()
        updates = self.obj_get_changes()

        if 'uuid' not in updates:
            updates['uuid'] = uuidutils.generate_uuid()
            self.uuid = updates['uuid']

        db_service = db.service_create(self._context, updates)
        self._from_db_object(self._context, self, db_service)
        self._send_notification(fields.NotificationAction.CREATE)

    @base.remotable
    def save(self):
        updates = self.obj_get_changes()
        updates.pop('id', None)
        self._check_minimum_version()
        db_service = db.service_update(self._context, self.id, updates)
        self._from_db_object(self._context, self, db_service)

        self._send_status_update_notification(updates)

    def _send_status_update_notification(self, updates):
        # Note(gibi): We do not trigger notification on version as that field
        # is always dirty, which would cause that nova sends notification on
        # every other field change. See the comment in save() too.
        if set(updates.keys()).intersection(
                {'disabled', 'disabled_reason', 'forced_down'}):
            self._send_notification(fields.NotificationAction.UPDATE)

    def _send_notification(self, action):
        payload = service_notification.ServiceStatusPayload(self)
        service_notification.ServiceStatusNotification(
            publisher=notification.NotificationPublisher.from_service_obj(
                self),
            event_type=notification.EventType(
                object='service',
                action=action),
            priority=fields.NotificationPriority.INFO,
            payload=payload).emit(self._context)

    @base.remotable
    def destroy(self):
        db.service_destroy(self._context, self.id)
        self._send_notification(fields.NotificationAction.DELETE)

    @classmethod
    def enable_min_version_cache(cls):
        cls.clear_min_version_cache()
        cls._SERVICE_VERSION_CACHING = True

    @classmethod
    def clear_min_version_cache(cls):
        cls._MIN_VERSION_CACHE = {}

    @staticmethod
    @db.select_db_reader_mode
    def _db_service_get_minimum_version(context, binaries, use_slave=False):
        return db.service_get_minimum_version(context, binaries)

    @base.remotable_classmethod
    def get_minimum_version_multi(cls, context, binaries, use_slave=False):
        if not all(binary.startswith('nova-') for binary in binaries):
            LOG.warning('get_minimum_version called with likely-incorrect '
                        'binaries `%s\'', ','.join(binaries))
            raise exception.ObjectActionError(action='get_minimum_version',
                                              reason='Invalid binary prefix')

        if (not cls._SERVICE_VERSION_CACHING or
              any(binary not in cls._MIN_VERSION_CACHE
                  for binary in binaries)):
            min_versions = cls._db_service_get_minimum_version(
                context, binaries, use_slave=use_slave)
            if min_versions:
                min_versions = {binary: version or 0
                                for binary, version in
                                min_versions.items()}
                cls._MIN_VERSION_CACHE.update(min_versions)
        else:
            min_versions = {binary: cls._MIN_VERSION_CACHE[binary]
                            for binary in binaries}

        if min_versions:
            version = min(min_versions.values())
        else:
            version = 0
        # NOTE(danms): Since our return value is not controlled by object
        # schema, be explicit here.
        version = int(version)

        return version

    @base.remotable_classmethod
    def get_minimum_version(cls, context, binary, use_slave=False):
        return cls.get_minimum_version_multi(context, [binary],
                                             use_slave=use_slave)


def get_minimum_version_all_cells(context, binaries, require_all=False):
    """Get the minimum service version, checking all cells.

    This attempts to calculate the minimum service version for a set
    of binaries across all the cells in the system. If require_all
    is False, then any cells that fail to report a version will be
    ignored (assuming they won't be candidates for scheduling and thus
    excluding them from the minimum version calculation is reasonable).
    If require_all is True, then a failing cell will cause this to raise
    exception.CellTimeout, as would be appropriate for gating some
    data migration until everything is new enough.

    Note that services that do not report a positive version are excluded
    from this, as it crosses all cells which will naturally not have all
    services.
    """

    if not all(binary.startswith('nova-') for binary in binaries):
        LOG.warning('get_minimum_version_all_cells called with '
                    'likely-incorrect binaries `%s\'', ','.join(binaries))
        raise exception.ObjectActionError(
            action='get_minimum_version_all_cells',
            reason='Invalid binary prefix')

    # NOTE(danms): Instead of using Service.get_minimum_version_multi(), we
    # replicate the call directly to the underlying DB method here because
    # we want to defeat the caching and we need to filter non-present
    # services differently from the single-cell method.

    results = nova_context.scatter_gather_all_cells(
        context,
        Service._db_service_get_minimum_version,
        binaries)

    min_version = None
    for cell_uuid, result in results.items():
        if result is nova_context.did_not_respond_sentinel:
            LOG.warning('Cell %s did not respond when getting minimum '
                        'service version', cell_uuid)
            if require_all:
                raise exception.CellTimeout()
        elif isinstance(result, Exception):
            LOG.warning('Failed to get minimum service version for cell %s',
                        cell_uuid)
            if require_all:
                # NOTE(danms): Okay, this isn't necessarily a timeout, but
                # it's functionally the same from the caller's perspective
                # and we logged the fact that it was actually a failure
                # for the forensic investigator during the scatter/gather
                # routine.
                raise exception.CellTimeout()
        else:
            # NOTE(danms): Don't consider a zero or None result as the minimum
            # since we're crossing cells and will likely not have all the
            # services being probed.
            relevant_versions = [version for version in result.values()
                                 if version]
            if relevant_versions:
                min_version_cell = min(relevant_versions)
                min_version = (min(min_version, min_version_cell)
                               if min_version else min_version_cell)

    # NOTE(danms): If we got no matches at all (such as at first startup)
    # then report that as zero to be consistent with the other such
    # methods.
    return min_version or 0


@base.NovaObjectRegistry.register
class ServiceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              Service <= version 1.2
    # Version 1.1  Service version 1.3
    # Version 1.2: Service version 1.4
    # Version 1.3: Service version 1.5
    # Version 1.4: Service version 1.6
    # Version 1.5: Service version 1.7
    # Version 1.6: Service version 1.8
    # Version 1.7: Service version 1.9
    # Version 1.8: Service version 1.10
    # Version 1.9: Added get_by_binary() and Service version 1.11
    # Version 1.10: Service version 1.12
    # Version 1.11: Service version 1.13
    # Version 1.12: Service version 1.14
    # Version 1.13: Service version 1.15
    # Version 1.14: Service version 1.16
    # Version 1.15: Service version 1.17
    # Version 1.16: Service version 1.18
    # Version 1.17: Service version 1.19
    # Version 1.18: Added include_disabled parameter to get_by_binary()
    # Version 1.19: Added get_all_computes_by_hv_type()
    VERSION = '1.19'

    fields = {
        'objects': fields.ListOfObjectsField('Service'),
        }

    @base.remotable_classmethod
    def get_by_topic(cls, context, topic):
        db_services = db.service_get_all_by_topic(context, topic)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)

    # NOTE(paul-carlton2): In v2.0 of the object the include_disabled flag
    # will be removed so both enabled and disabled hosts are returned
    @base.remotable_classmethod
    def get_by_binary(cls, context, binary, include_disabled=False):
        db_services = db.service_get_all_by_binary(
            context, binary, include_disabled=include_disabled)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)

    @base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_services = db.service_get_all_by_host(context, host)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)

    @base.remotable_classmethod
    def get_all(cls, context, disabled=None, set_zones=False):
        db_services = db.service_get_all(context, disabled=disabled)
        if set_zones:
            db_services = availability_zones.set_availability_zones(
                context, db_services)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)

    @base.remotable_classmethod
    def get_all_computes_by_hv_type(cls, context, hv_type):
        db_services = db.service_get_all_computes_by_hv_type(
            context, hv_type, include_disabled=False)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)
