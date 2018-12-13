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

"""Handles database requests from other nova services."""

import contextlib
import copy
import functools
import sys

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import versionutils
import six

from nova import availability_zones
from nova.compute import instance_actions
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute.utils import wrap_instance_event
from nova.compute import vm_states
from nova.conductor.tasks import live_migrate
from nova.conductor.tasks import migrate
from nova import context as nova_context
from nova.db import base
from nova import exception
from nova.i18n import _
from nova import image
from nova import manager
from nova import network
from nova import notifications
from nova import objects
from nova.objects import base as nova_object
from nova.objects import fields
from nova import profiler
from nova import rpc
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import servicegroup
from nova import utils
from nova.volume import cinder

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


def targets_cell(fn):
    """Wrap a method and automatically target the instance's cell.

    This decorates a method with signature func(self, context, instance, ...)
    and automatically targets the context with the instance's cell
    mapping. It does this by looking up the InstanceMapping.
    """
    @functools.wraps(fn)
    def wrapper(self, context, *args, **kwargs):
        instance = kwargs.get('instance') or args[0]
        try:
            im = objects.InstanceMapping.get_by_instance_uuid(
                context, instance.uuid)
        except exception.InstanceMappingNotFound:
            LOG.error('InstanceMapping not found, unable to target cell',
                      instance=instance)
            im = None
        else:
            LOG.debug('Targeting cell %(cell)s for conductor method %(meth)s',
                      {'cell': im.cell_mapping.identity,
                       'meth': fn.__name__})
            # NOTE(danms): Target our context to the cell for the rest of
            # this request, so that none of the subsequent code needs to
            # care about it.
            nova_context.set_target_cell(context, im.cell_mapping)
        return fn(self, context, *args, **kwargs)
    return wrapper


class ConductorManager(manager.Manager):
    """Mission: Conduct things.

    The methods in the base API for nova-conductor are various proxy operations
    performed on behalf of the nova-compute service running on compute nodes.
    Compute nodes are not allowed to directly access the database, so this set
    of methods allows them to get specific work done without locally accessing
    the database.

    The nova-conductor service also exposes an API in the 'compute_task'
    namespace.  See the ComputeTaskManager class for details.
    """

    target = messaging.Target(version='3.0')

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)
        self.compute_task_mgr = ComputeTaskManager()
        self.additional_endpoints.append(self.compute_task_mgr)

    # NOTE(hanlind): This can be removed in version 4.0 of the RPC API
    def provider_fw_rule_get_all(self, context):
        # NOTE(hanlind): Simulate an empty db result for compat reasons.
        return []

    def _object_dispatch(self, target, method, args, kwargs):
        """Dispatch a call to an object method.

        This ensures that object methods get called and any exception
        that is raised gets wrapped in an ExpectedException for forwarding
        back to the caller (without spamming the conductor logs).
        """
        try:
            # NOTE(danms): Keep the getattr inside the try block since
            # a missing method is really a client problem
            return getattr(target, method)(*args, **kwargs)
        except Exception:
            raise messaging.ExpectedException()

    def object_class_action_versions(self, context, objname, objmethod,
                                     object_versions, args, kwargs):
        objclass = nova_object.NovaObject.obj_class_from_name(
            objname, object_versions[objname])
        args = tuple([context] + list(args))
        result = self._object_dispatch(objclass, objmethod, args, kwargs)
        # NOTE(danms): The RPC layer will convert to primitives for us,
        # but in this case, we need to honor the version the client is
        # asking for, so we do it before returning here.
        # NOTE(hanlind): Do not convert older than requested objects,
        # see bug #1596119.
        if isinstance(result, nova_object.NovaObject):
            target_version = object_versions[objname]
            requested_version = versionutils.convert_version_to_tuple(
                target_version)
            actual_version = versionutils.convert_version_to_tuple(
                result.VERSION)
            do_backport = requested_version < actual_version
            other_major_version = requested_version[0] != actual_version[0]
            if do_backport or other_major_version:
                result = result.obj_to_primitive(
                    target_version=target_version,
                    version_manifest=object_versions)
        return result

    def object_action(self, context, objinst, objmethod, args, kwargs):
        """Perform an action on an object."""
        oldobj = objinst.obj_clone()
        result = self._object_dispatch(objinst, objmethod, args, kwargs)
        updates = dict()
        # NOTE(danms): Diff the object with the one passed to us and
        # generate a list of changes to forward back
        for name, field in objinst.fields.items():
            if not objinst.obj_attr_is_set(name):
                # Avoid demand-loading anything
                continue
            if (not oldobj.obj_attr_is_set(name) or
                    getattr(oldobj, name) != getattr(objinst, name)):
                updates[name] = field.to_primitive(objinst, name,
                                                   getattr(objinst, name))
        # This is safe since a field named this would conflict with the
        # method anyway
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

    def object_backport_versions(self, context, objinst, object_versions):
        target = object_versions[objinst.obj_name()]
        LOG.debug('Backporting %(obj)s to %(ver)s with versions %(manifest)s',
                  {'obj': objinst.obj_name(),
                   'ver': target,
                   'manifest': ','.join(
                       ['%s=%s' % (name, ver)
                       for name, ver in object_versions.items()])})
        return objinst.obj_to_primitive(target_version=target,
                                        version_manifest=object_versions)

    def reset(self):
        objects.Service.clear_min_version_cache()


@contextlib.contextmanager
def try_target_cell(context, cell):
    """If cell is not None call func with context.target_cell.

    This is a method to help during the transition period. Currently
    various mappings may not exist if a deployment has not migrated to
    cellsv2. If there is no mapping call the func as normal, otherwise
    call it in a target_cell context.
    """
    if cell:
        with nova_context.target_cell(context, cell) as cell_context:
            yield cell_context
    else:
        yield context


@contextlib.contextmanager
def obj_target_cell(obj, cell):
    """Run with object's context set to a specific cell"""
    with try_target_cell(obj._context, cell) as target:
        with obj.obj_alternate_context(target):
            yield target


@profiler.trace_cls("rpc")
class ComputeTaskManager(base.Base):
    """Namespace for compute methods.

    This class presents an rpc API for nova-conductor under the 'compute_task'
    namespace.  The methods here are compute operations that are invoked
    by the API service.  These methods see the operation to completion, which
    may involve coordinating activities on multiple compute nodes.
    """

    target = messaging.Target(namespace='compute_task', version='1.20')

    def __init__(self):
        super(ComputeTaskManager, self).__init__()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.volume_api = cinder.API()
        self.image_api = image.API()
        self.network_api = network.API()
        self.servicegroup_api = servicegroup.API()
        self.scheduler_client = scheduler_client.SchedulerClient()
        self.report_client = self.scheduler_client.reportclient
        self.notifier = rpc.get_notifier('compute', CONF.host)
        # Help us to record host in EventReporter
        self.host = CONF.host

    def reset(self):
        LOG.info('Reloading compute RPC API')
        compute_rpcapi.LAST_VERSION = None
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    # TODO(tdurakov): remove `live` parameter here on compute task api RPC
    # version bump to 2.x
    # TODO(danms): remove the `reservations` parameter here on compute task api
    # RPC version bump to 2.x
    @messaging.expected_exceptions(
        exception.NoValidHost,
        exception.ComputeServiceUnavailable,
        exception.ComputeHostNotFound,
        exception.InvalidHypervisorType,
        exception.InvalidCPUInfo,
        exception.UnableToMigrateToSelf,
        exception.DestinationHypervisorTooOld,
        exception.InvalidLocalStorage,
        exception.InvalidSharedStorage,
        exception.HypervisorUnavailable,
        exception.InstanceInvalidState,
        exception.MigrationPreCheckError,
        exception.UnsupportedPolicyException)
    @targets_cell
    @wrap_instance_event(prefix='conductor')
    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
            flavor, block_migration, disk_over_commit, reservations=None,
            clean_shutdown=True, request_spec=None, host_list=None):
        if instance and not isinstance(instance, nova_object.NovaObject):
            # NOTE(danms): Until v2 of the RPC API, we need to tolerate
            # old-world instance objects here
            attrs = ['metadata', 'system_metadata', 'info_cache',
                     'security_groups']
            instance = objects.Instance._from_db_object(
                context, objects.Instance(), instance,
                expected_attrs=attrs)
        # NOTE: Remove this when we drop support for v1 of the RPC API
        if flavor and not isinstance(flavor, objects.Flavor):
            # Code downstream may expect extra_specs to be populated since it
            # is receiving an object, so lookup the flavor to ensure this.
            flavor = objects.Flavor.get_by_id(context, flavor['id'])
        if live and not rebuild and not flavor:
            self._live_migrate(context, instance, scheduler_hint,
                               block_migration, disk_over_commit, request_spec)
        elif not live and not rebuild and flavor:
            instance_uuid = instance.uuid
            with compute_utils.EventReporter(context, 'cold_migrate',
                                             self.host, instance_uuid):
                self._cold_migrate(context, instance, flavor,
                                   scheduler_hint['filter_properties'],
                                   clean_shutdown, request_spec,
                                   host_list)
        else:
            raise NotImplementedError()

    def _cold_migrate(self, context, instance, flavor, filter_properties,
                      clean_shutdown, request_spec, host_list):
        image = utils.get_image_from_system_metadata(
            instance.system_metadata)

        # NOTE(sbauza): If a reschedule occurs when prep_resize(), then
        # it only provides filter_properties legacy dict back to the
        # conductor with no RequestSpec part of the payload.
        if not request_spec:
            # Make sure we hydrate a new RequestSpec object with the new flavor
            # and not the nested one from the instance
            request_spec = objects.RequestSpec.from_components(
                context, instance.uuid, image,
                flavor, instance.numa_topology, instance.pci_requests,
                filter_properties, None, instance.availability_zone,
                project_id=instance.project_id, user_id=instance.user_id)
        else:
            # NOTE(sbauza): Resizes means new flavor, so we need to update the
            # original RequestSpec object for make sure the scheduler verifies
            # the right one and not the original flavor
            request_spec.flavor = flavor

        task = self._build_cold_migrate_task(context, instance, flavor,
                request_spec, clean_shutdown, host_list)
        try:
            task.execute()
        except exception.NoValidHost as ex:
            vm_state = instance.vm_state
            if not vm_state:
                vm_state = vm_states.ACTIVE
            updates = {'vm_state': vm_state, 'task_state': None}
            self._set_vm_state_and_notify(context, instance.uuid,
                                          'migrate_server',
                                          updates, ex, request_spec)

            # if the flavor IDs match, it's migrate; otherwise resize
            if flavor.id == instance.instance_type_id:
                msg = _("No valid host found for cold migrate")
            else:
                msg = _("No valid host found for resize")
            raise exception.NoValidHost(reason=msg)
        except exception.UnsupportedPolicyException as ex:
            with excutils.save_and_reraise_exception():
                vm_state = instance.vm_state
                if not vm_state:
                    vm_state = vm_states.ACTIVE
                updates = {'vm_state': vm_state, 'task_state': None}
                self._set_vm_state_and_notify(context, instance.uuid,
                                              'migrate_server',
                                              updates, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                updates = {'vm_state': instance.vm_state,
                           'task_state': None}
                self._set_vm_state_and_notify(context, instance.uuid,
                                              'migrate_server',
                                              updates, ex, request_spec)
        # NOTE(sbauza): Make sure we persist the new flavor in case we had
        # a successful scheduler call if and only if nothing bad happened
        if request_spec.obj_what_changed():
            request_spec.save()

    def _set_vm_state_and_notify(self, context, instance_uuid, method, updates,
                                 ex, request_spec):
        scheduler_utils.set_vm_state_and_notify(
                context, instance_uuid, 'compute_task', method, updates,
                ex, request_spec)

    def _cleanup_allocated_networks(
            self, context, instance, requested_networks):
        try:
            # If we were told not to allocate networks let's save ourselves
            # the trouble of calling the network API.
            if not (requested_networks and requested_networks.no_allocate):
                self.network_api.deallocate_for_instance(
                    context, instance, requested_networks=requested_networks)
        except Exception:
            LOG.exception('Failed to deallocate networks', instance=instance)
            return

        instance.system_metadata['network_allocated'] = 'False'
        try:
            instance.save()
        except exception.InstanceNotFound:
            # NOTE: It's possible that we're cleaning up the networks
            # because the instance was deleted.  If that's the case then this
            # exception will be raised by instance.save()
            pass

    @targets_cell
    @wrap_instance_event(prefix='conductor')
    def live_migrate_instance(self, context, instance, scheduler_hint,
                              block_migration, disk_over_commit, request_spec):
        self._live_migrate(context, instance, scheduler_hint,
                           block_migration, disk_over_commit, request_spec)

    def _live_migrate(self, context, instance, scheduler_hint,
                      block_migration, disk_over_commit, request_spec):
        destination = scheduler_hint.get("host")

        def _set_vm_state(context, instance, ex, vm_state=None,
                          task_state=None):
            request_spec = {'instance_properties': {
                'uuid': instance.uuid, },
            }
            scheduler_utils.set_vm_state_and_notify(context,
                instance.uuid,
                'compute_task', 'migrate_server',
                dict(vm_state=vm_state,
                     task_state=task_state,
                     expected_task_state=task_states.MIGRATING,),
                ex, request_spec)

        migration = objects.Migration(context=context.elevated())
        migration.dest_compute = destination
        migration.status = 'accepted'
        migration.instance_uuid = instance.uuid
        migration.source_compute = instance.host
        migration.migration_type = 'live-migration'
        if instance.obj_attr_is_set('flavor'):
            migration.old_instance_type_id = instance.flavor.id
            migration.new_instance_type_id = instance.flavor.id
        else:
            migration.old_instance_type_id = instance.instance_type_id
            migration.new_instance_type_id = instance.instance_type_id
        migration.create()

        task = self._build_live_migrate_task(context, instance, destination,
                                             block_migration, disk_over_commit,
                                             migration, request_spec)
        try:
            task.execute()
        except (exception.NoValidHost,
                exception.ComputeHostNotFound,
                exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.InvalidCPUInfo,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.HypervisorUnavailable,
                exception.InstanceInvalidState,
                exception.MigrationPreCheckError,
                exception.MigrationSchedulerRPCError) as ex:
            with excutils.save_and_reraise_exception():
                # TODO(johngarbutt) - eventually need instance actions here
                _set_vm_state(context, instance, ex, instance.vm_state)
                migration.status = 'error'
                migration.save()
        except Exception as ex:
            LOG.error('Migration of instance %(instance_id)s to host'
                      ' %(dest)s unexpectedly failed.',
                      {'instance_id': instance.uuid, 'dest': destination},
                      exc_info=True)
            # Reset the task state to None to indicate completion of
            # the operation as it is done in case of known exceptions.
            _set_vm_state(context, instance, ex, vm_states.ERROR,
                          task_state=None)
            migration.status = 'error'
            migration.save()
            raise exception.MigrationError(reason=six.text_type(ex))

    def _build_live_migrate_task(self, context, instance, destination,
                                 block_migration, disk_over_commit, migration,
                                 request_spec=None):
        return live_migrate.LiveMigrationTask(context, instance,
                                              destination, block_migration,
                                              disk_over_commit, migration,
                                              self.compute_rpcapi,
                                              self.servicegroup_api,
                                              self.scheduler_client,
                                              request_spec)

    def _build_cold_migrate_task(self, context, instance, flavor, request_spec,
            clean_shutdown, host_list):
        return migrate.MigrationTask(context, instance, flavor,
                                     request_spec,
                                     clean_shutdown,
                                     self.compute_rpcapi,
                                     self.scheduler_client, host_list)

    def _destroy_build_request(self, context, instance):
        # The BuildRequest needs to be stored until the instance is mapped to
        # an instance table. At that point it will never be used again and
        # should be deleted.
        build_request = objects.BuildRequest.get_by_instance_uuid(
            context, instance.uuid)
        # TODO(alaski): Sync API updates of the build_request to the
        # instance before it is destroyed. Right now only locked_by can
        # be updated before this is destroyed.
        build_request.destroy()

    def _populate_instance_mapping(self, context, instance, host):
        try:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
                    context, instance.uuid)
        except exception.InstanceMappingNotFound:
            # NOTE(alaski): If nova-api is up to date this exception should
            # never be hit. But during an upgrade it's possible that an old
            # nova-api didn't create an instance_mapping during this boot
            # request.
            LOG.debug('Instance was not mapped to a cell, likely due '
                      'to an older nova-api service running.',
                      instance=instance)
            return None
        else:
            try:
                host_mapping = objects.HostMapping.get_by_host(context,
                        host.service_host)
            except exception.HostMappingNotFound:
                # NOTE(alaski): For now this exception means that a
                # deployment has not migrated to cellsv2 and we should
                # remove the instance_mapping that has been created.
                # Eventually this will indicate a failure to properly map a
                # host to a cell and we may want to reschedule.
                inst_mapping.destroy()
                return None
            else:
                inst_mapping.cell_mapping = host_mapping.cell_mapping
                inst_mapping.save()
        return inst_mapping

    def _validate_existing_attachment_ids(self, context, instance, bdms):
        """Ensure any attachment ids referenced by the bdms exist.

        New attachments will only be created if the attachment ids referenced
        by the bdms no longer exist. This can happen when an instance is
        rescheduled after a failure to spawn as cleanup code on the previous
        host will delete attachments before rescheduling.
        """
        for bdm in bdms:
            if bdm.is_volume and bdm.attachment_id:
                try:
                    self.volume_api.attachment_get(context, bdm.attachment_id)
                except exception.VolumeAttachmentNotFound:
                    attachment = self.volume_api.attachment_create(
                        context, bdm.volume_id, instance.uuid)
                    bdm.attachment_id = attachment['id']
                    bdm.save()

    # NOTE(danms): This is never cell-targeted because it is only used for
    # cellsv1 (which does not target cells directly) and n-cpu reschedules
    # (which go to the cell conductor and thus are always cell-specific).
    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping=None, legacy_bdm=True,
            request_spec=None, host_lists=None):
        # TODO(ndipanov): Remove block_device_mapping and legacy_bdm in version
        #                 2.0 of the RPC API.
        # TODO(danms): Remove this in version 2.0 of the RPC API
        if (requested_networks and
                not isinstance(requested_networks,
                               objects.NetworkRequestList)):
            requested_networks = objects.NetworkRequestList.from_tuples(
                requested_networks)
        # TODO(melwitt): Remove this in version 2.0 of the RPC API
        flavor = filter_properties.get('instance_type')
        if flavor and not isinstance(flavor, objects.Flavor):
            # Code downstream may expect extra_specs to be populated since it
            # is receiving an object, so lookup the flavor to ensure this.
            flavor = objects.Flavor.get_by_id(context, flavor['id'])
            filter_properties = dict(filter_properties, instance_type=flavor)

        # Older computes will not send a request_spec during reschedules, nor
        # will the API send the request_spec if using cells v1, so we need
        # to check and build our own if one is not provided.
        if request_spec is None:
            request_spec = scheduler_utils.build_request_spec(
                image, instances)
        else:
            # TODO(mriedem): This is annoying but to populate the local
            # request spec below using the filter_properties, we have to pass
            # in a primitive version of the request spec. Yes it's inefficient
            # and we can remove it once the populate_retry and
            # populate_filter_properties utility methods are converted to
            # work on a RequestSpec object rather than filter_properties.
            request_spec = request_spec.to_legacy_request_spec_dict()

        # 'host_lists' will be None in one of two cases: when running cellsv1,
        # or during a reschedule from a pre-Queens compute. In all other cases,
        # it will be a list of lists, though the lists may be empty if there
        # are no more hosts left in a rescheduling situation.
        is_reschedule = host_lists is not None
        try:
            # check retry policy. Rather ugly use of instances[0]...
            # but if we've exceeded max retries... then we really only
            # have a single instance.
            # TODO(sbauza): Provide directly the RequestSpec object
            # when populate_retry() accepts it
            scheduler_utils.populate_retry(
                filter_properties, instances[0].uuid)
            instance_uuids = [instance.uuid for instance in instances]
            spec_obj = objects.RequestSpec.from_primitives(
                    context, request_spec, filter_properties)
            LOG.debug("Rescheduling: %s", is_reschedule)
            if is_reschedule:
                # Make sure that we have a host, as we may have exhausted all
                # our alternates
                if not host_lists[0]:
                    # We have an empty list of hosts, so this instance has
                    # failed to build.
                    msg = ("Exhausted all hosts available for retrying build "
                           "failures for instance %(instance_uuid)s." %
                           {"instance_uuid": instances[0].uuid})
                    raise exception.MaxRetriesExceeded(reason=msg)
            else:
                # This is not a reschedule, so we need to call the scheduler to
                # get appropriate hosts for the request.
                host_lists = self._schedule_instances(context, spec_obj,
                        instance_uuids, return_alternates=True)
        except Exception as exc:
            # NOTE(mriedem): If we're rescheduling from a failed build on a
            # compute, "retry" will be set and num_attempts will be >1 because
            # populate_retry above will increment it. If the server build was
            # forced onto a host/node or [scheduler]/max_attempts=1, "retry"
            # won't be in filter_properties and we won't get here because
            # nova-compute will just abort the build since reschedules are
            # disabled in those cases.
            num_attempts = filter_properties.get(
                'retry', {}).get('num_attempts', 1)
            updates = {'vm_state': vm_states.ERROR, 'task_state': None}
            for instance in instances:
                self._set_vm_state_and_notify(
                    context, instance.uuid, 'build_instances', updates,
                    exc, request_spec)
                # If num_attempts > 1, we're in a reschedule and probably
                # either hit NoValidHost or MaxRetriesExceeded. Either way,
                # the build request should already be gone and we probably
                # can't reach the API DB from the cell conductor.
                if num_attempts <= 1:
                    try:
                        # If the BuildRequest stays around then instance
                        # show/lists will pull from it rather than the errored
                        # instance.
                        self._destroy_build_request(context, instance)
                    except exception.BuildRequestNotFound:
                        pass
                self._cleanup_allocated_networks(
                    context, instance, requested_networks)
            return

        elevated = context.elevated()
        for (instance, host_list) in six.moves.zip(instances, host_lists):
            host = host_list.pop(0)
            if is_reschedule:
                # If this runs in the superconductor, the first instance will
                # already have its resources claimed in placement. If this is a
                # retry, though, this is running in the cell conductor, and we
                # need to claim first to ensure that the alternate host still
                # has its resources available. Note that there are schedulers
                # that don't support Placement, so must assume that the host is
                # still available.
                host_available = False
                while host and not host_available:
                    if host.allocation_request:
                        alloc_req = jsonutils.loads(host.allocation_request)
                    else:
                        alloc_req = None
                    if alloc_req:
                        host_available = scheduler_utils.claim_resources(
                                elevated, self.report_client, spec_obj,
                                instance.uuid, alloc_req,
                                host.allocation_request_version)
                    else:
                        # Some deployments use different schedulers that do not
                        # use Placement, so they will not have an
                        # allocation_request to claim with. For those cases,
                        # there is no concept of claiming, so just assume that
                        # the host is valid.
                        host_available = True
                    if not host_available:
                        # Insufficient resources remain on that host, so
                        # discard it and try the next.
                        host = host_list.pop(0) if host_list else None
                if not host_available:
                    # No more available hosts for retrying the build.
                    msg = ("Exhausted all hosts available for retrying build "
                           "failures for instance %(instance_uuid)s." %
                           {"instance_uuid": instance.uuid})
                    raise exception.MaxRetriesExceeded(reason=msg)
            instance.availability_zone = (
                availability_zones.get_host_availability_zone(context,
                        host.service_host))
            try:
                # NOTE(danms): This saves the az change above, refreshes our
                # instance, and tells us if it has been deleted underneath us
                instance.save()
            except (exception.InstanceNotFound,
                    exception.InstanceInfoCacheNotFound):
                LOG.debug('Instance deleted during build', instance=instance)
                continue
            local_filter_props = copy.deepcopy(filter_properties)
            scheduler_utils.populate_filter_properties(local_filter_props,
                host)
            # Populate the request_spec with the local_filter_props information
            # like retries and limits. Note that at this point the request_spec
            # could have come from a compute via reschedule and it would
            # already have some things set, like scheduler_hints.
            local_reqspec = objects.RequestSpec.from_primitives(
                context, request_spec, local_filter_props)

            # The block_device_mapping passed from the api doesn't contain
            # instance specific information
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                    context, instance.uuid)

            # This is populated in scheduler_utils.populate_retry
            num_attempts = local_filter_props.get('retry',
                                                  {}).get('num_attempts', 1)
            if num_attempts <= 1:
                # If this is a reschedule the instance is already mapped to
                # this cell and the BuildRequest is already deleted so ignore
                # the logic below.
                inst_mapping = self._populate_instance_mapping(context,
                                                               instance,
                                                               host)
                try:
                    self._destroy_build_request(context, instance)
                except exception.BuildRequestNotFound:
                    # This indicates an instance delete has been requested in
                    # the API. Stop the build, cleanup the instance_mapping and
                    # potentially the block_device_mappings
                    # TODO(alaski): Handle block_device_mapping cleanup
                    if inst_mapping:
                        inst_mapping.destroy()
                    return
            else:
                # NOTE(lyarwood): If this is a reschedule then recreate any
                # attachments that were previously removed when cleaning up
                # after failures to spawn etc.
                self._validate_existing_attachment_ids(context, instance, bdms)

            alts = [(alt.service_host, alt.nodename) for alt in host_list]
            LOG.debug("Selected host: %s; Selected node: %s; Alternates: %s",
                    host.service_host, host.nodename, alts, instance=instance)

            self.compute_rpcapi.build_and_run_instance(context,
                    instance=instance, host=host.service_host, image=image,
                    request_spec=local_reqspec,
                    filter_properties=local_filter_props,
                    admin_password=admin_password,
                    injected_files=injected_files,
                    requested_networks=requested_networks,
                    security_groups=security_groups,
                    block_device_mapping=bdms, node=host.nodename,
                    limits=host.limits, host_list=host_list)

    def _schedule_instances(self, context, request_spec,
                            instance_uuids=None, return_alternates=False):
        scheduler_utils.setup_instance_group(context, request_spec)
        with timeutils.StopWatch() as timer:
            host_lists = self.scheduler_client.select_destinations(context,
                    request_spec, instance_uuids, return_objects=True,
                    return_alternates=return_alternates)
        LOG.debug('Took %0.2f seconds to select destinations for %s '
                  'instance(s).', timer.elapsed(), len(instance_uuids))
        return host_lists

    @targets_cell
    def unshelve_instance(self, context, instance, request_spec=None):
        sys_meta = instance.system_metadata

        def safe_image_show(ctx, image_id):
            if image_id:
                return self.image_api.get(ctx, image_id, show_deleted=False)
            else:
                raise exception.ImageNotFound(image_id='')

        if instance.vm_state == vm_states.SHELVED:
            instance.task_state = task_states.POWERING_ON
            instance.save(expected_task_state=task_states.UNSHELVING)
            self.compute_rpcapi.start_instance(context, instance)
        elif instance.vm_state == vm_states.SHELVED_OFFLOADED:
            image = None
            image_id = sys_meta.get('shelved_image_id')
            # No need to check for image if image_id is None as
            # "shelved_image_id" key is not set for volume backed
            # instance during the shelve process
            if image_id:
                with compute_utils.EventReporter(
                        context, 'get_image_info', self.host, instance.uuid):
                    try:
                        image = safe_image_show(context, image_id)
                    except exception.ImageNotFound as error:
                        instance.vm_state = vm_states.ERROR
                        instance.save()

                        reason = _('Unshelve attempted but the image %s '
                                   'cannot be found.') % image_id

                        LOG.error(reason, instance=instance)
                        compute_utils.add_instance_fault_from_exc(
                            context, instance, error, sys.exc_info(),
                            fault_message=reason)
                        raise exception.UnshelveException(
                            instance_id=instance.uuid, reason=reason)

            try:
                with compute_utils.EventReporter(context, 'schedule_instances',
                                                 self.host, instance.uuid):
                    if not request_spec:
                        # NOTE(sbauza): We were unable to find an original
                        # RequestSpec object - probably because the instance is
                        # old. We need to mock that the old way
                        filter_properties = {}
                        request_spec = scheduler_utils.build_request_spec(
                            image, [instance])
                        request_spec = objects.RequestSpec.from_primitives(
                            context, request_spec, filter_properties)
                    else:
                        # NOTE(sbauza): Force_hosts/nodes needs to be reset
                        # if we want to make sure that the next destination
                        # is not forced to be the original host
                        request_spec.reset_forced_destinations()
                        # TODO(sbauza): Provide directly the RequestSpec object
                        # when populate_filter_properties accepts it
                        filter_properties = request_spec.\
                            to_legacy_filter_properties_dict()
                    # NOTE(cfriesen): Ensure that we restrict the scheduler to
                    # the cell specified by the instance mapping.
                    instance_mapping = \
                        objects.InstanceMapping.get_by_instance_uuid(
                            context, instance.uuid)
                    LOG.debug('Requesting cell %(cell)s while unshelving',
                              {'cell': instance_mapping.cell_mapping.identity},
                              instance=instance)
                    if ('requested_destination' in request_spec and
                            request_spec.requested_destination):
                        request_spec.requested_destination.cell = (
                            instance_mapping.cell_mapping)
                    else:
                        request_spec.requested_destination = (
                            objects.Destination(
                                cell=instance_mapping.cell_mapping))

                    request_spec.ensure_project_and_user_id(instance)
                    request_spec.ensure_network_metadata(instance)
                    compute_utils.heal_reqspec_is_bfv(
                        context, request_spec, instance)
                    host_lists = self._schedule_instances(context,
                            request_spec, [instance.uuid],
                            return_alternates=False)
                    host_list = host_lists[0]
                    selection = host_list[0]
                    scheduler_utils.populate_filter_properties(
                            filter_properties, selection)
                    (host, node) = (selection.service_host, selection.nodename)
                    instance.availability_zone = (
                        availability_zones.get_host_availability_zone(
                            context, host))
                    self.compute_rpcapi.unshelve_instance(
                            context, instance, host, image=image,
                            filter_properties=filter_properties, node=node)
            except (exception.NoValidHost,
                    exception.UnsupportedPolicyException):
                instance.task_state = None
                instance.save()
                LOG.warning("No valid host found for unshelve instance",
                            instance=instance)
                return
            except Exception:
                with excutils.save_and_reraise_exception():
                    instance.task_state = None
                    instance.save()
                    LOG.error("Unshelve attempted but an error "
                              "has occurred", instance=instance)
        else:
            LOG.error('Unshelve attempted but vm_state not SHELVED or '
                      'SHELVED_OFFLOADED', instance=instance)
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

    def _allocate_for_evacuate_dest_host(self, context, instance, host,
                                         request_spec=None):
        # The user is forcing the destination host and bypassing the
        # scheduler. We need to copy the source compute node
        # allocations in Placement to the destination compute node.
        # Normally select_destinations() in the scheduler would do this
        # for us, but when forcing the target host we don't call the
        # scheduler.
        source_node = None  # This is used for error handling below.
        try:
            source_node = objects.ComputeNode.get_by_host_and_nodename(
                context, instance.host, instance.node)
            dest_node = (
                objects.ComputeNode.get_first_node_by_host_for_old_compat(
                    context, host, use_slave=True))
        except exception.ComputeHostNotFound as ex:
            with excutils.save_and_reraise_exception():
                self._set_vm_state_and_notify(
                    context, instance.uuid, 'rebuild_server',
                    {'vm_state': instance.vm_state,
                     'task_state': None}, ex, request_spec)
                if source_node:
                    LOG.warning('Specified host %s for evacuate was not '
                                'found.', host, instance=instance)
                else:
                    LOG.warning('Source host %s and node %s for evacuate was '
                                'not found.', instance.host, instance.node,
                                instance=instance)

        # TODO(mriedem): In Queens, call select_destinations() with a
        # skip_filters=True flag so the scheduler does the work of
        # claiming resources on the destination in Placement but still
        # bypass the scheduler filters, which honors the 'force' flag
        # in the API.
        try:
            scheduler_utils.claim_resources_on_destination(
                context, self.report_client, instance, source_node, dest_node)
        except exception.NoValidHost as ex:
            with excutils.save_and_reraise_exception():
                self._set_vm_state_and_notify(
                    context, instance.uuid, 'rebuild_server',
                    {'vm_state': instance.vm_state,
                     'task_state': None}, ex, request_spec)
                LOG.warning('Specified host %s for evacuate is '
                            'invalid.', host, instance=instance)

    @targets_cell
    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate, on_shared_storage,
                         preserve_ephemeral=False, host=None,
                         request_spec=None):

        with compute_utils.EventReporter(context, 'rebuild_server',
                                         self.host, instance.uuid):
            node = limits = None

            try:
                migration = objects.Migration.get_by_instance_and_status(
                    context, instance.uuid, 'accepted')
            except exception.MigrationNotFoundByStatus:
                LOG.debug("No migration record for the rebuild/evacuate "
                          "request.", instance=instance)
                migration = None

            # The host variable is passed in two cases:
            # 1. rebuild - the instance.host is passed to rebuild on the
            #       same host and bypass the scheduler *unless* a new image
            #       was specified
            # 2. evacuate with specified host and force=True - the specified
            #       host is passed and is meant to bypass the scheduler.
            # NOTE(mriedem): This could be a lot more straight-forward if we
            # had separate methods for rebuild and evacuate...
            if host:
                # We only create a new allocation on the specified host if
                # we're doing an evacuate since that is a move operation.
                if host != instance.host:
                    # If a destination host is forced for evacuate, create
                    # allocations against it in Placement.
                    self._allocate_for_evacuate_dest_host(
                        context, instance, host, request_spec)
            else:
                # At this point, the user is either:
                #
                # 1. Doing a rebuild on the same host (not evacuate) and
                #    specified a new image.
                # 2. Evacuating and specified a host but are not forcing it.
                #
                # In either case, the API passes host=None but sets up the
                # RequestSpec.requested_destination field for the specified
                # host.
                if not request_spec:
                    # NOTE(sbauza): We were unable to find an original
                    # RequestSpec object - probably because the instance is old
                    # We need to mock that the old way
                    filter_properties = {'ignore_hosts': [instance.host]}
                    # build_request_spec expects a primitive image dict
                    image_meta = nova_object.obj_to_primitive(
                        instance.image_meta)
                    request_spec = scheduler_utils.build_request_spec(
                        image_meta, [instance])
                    request_spec = objects.RequestSpec.from_primitives(
                        context, request_spec, filter_properties)
                elif recreate:
                    # NOTE(sbauza): Augment the RequestSpec object by excluding
                    # the source host for avoiding the scheduler to pick it
                    request_spec.ignore_hosts = request_spec.ignore_hosts or []
                    request_spec.ignore_hosts.append(instance.host)
                    # NOTE(sbauza): Force_hosts/nodes needs to be reset
                    # if we want to make sure that the next destination
                    # is not forced to be the original host
                    request_spec.reset_forced_destinations()
                try:
                    # if this is a rebuild of instance on the same host with
                    # new image.
                    if not recreate and orig_image_ref != image_ref:
                        self._validate_image_traits_for_rebuild(context,
                                                                instance,
                                                                image_ref)
                    request_spec.ensure_project_and_user_id(instance)
                    request_spec.ensure_network_metadata(instance)
                    compute_utils.heal_reqspec_is_bfv(
                        context, request_spec, instance)
                    host_lists = self._schedule_instances(context,
                            request_spec, [instance.uuid],
                            return_alternates=False)
                    host_list = host_lists[0]
                    selection = host_list[0]
                    host, node, limits = (selection.service_host,
                            selection.nodename, selection.limits)
                except (exception.NoValidHost,
                        exception.UnsupportedPolicyException) as ex:
                    if migration:
                        migration.status = 'error'
                        migration.save()
                    # Rollback the image_ref if a new one was provided (this
                    # only happens in the rebuild case, not evacuate).
                    if orig_image_ref and orig_image_ref != image_ref:
                        instance.image_ref = orig_image_ref
                        instance.save()
                    with excutils.save_and_reraise_exception():
                        self._set_vm_state_and_notify(context, instance.uuid,
                                'rebuild_server',
                                {'vm_state': vm_states.ERROR,
                                 'task_state': None}, ex, request_spec)
                        LOG.warning('Rebuild failed: %s',
                                    six.text_type(ex), instance=instance)

            compute_utils.notify_about_instance_usage(
                self.notifier, context, instance, "rebuild.scheduled")
            compute_utils.notify_about_instance_rebuild(
                context, instance, host,
                action=fields.NotificationAction.REBUILD_SCHEDULED,
                source=fields.NotificationSource.CONDUCTOR)

            instance.availability_zone = (
                availability_zones.get_host_availability_zone(
                    context, host))

            self.compute_rpcapi.rebuild_instance(context,
                    instance=instance,
                    new_pass=new_pass,
                    injected_files=injected_files,
                    image_ref=image_ref,
                    orig_image_ref=orig_image_ref,
                    orig_sys_metadata=orig_sys_metadata,
                    bdms=bdms,
                    recreate=recreate,
                    on_shared_storage=on_shared_storage,
                    preserve_ephemeral=preserve_ephemeral,
                    migration=migration,
                    host=host, node=node, limits=limits,
                    request_spec=request_spec)

    def _validate_image_traits_for_rebuild(self, context, instance, image_ref):
        """Validates that the traits specified in the image can be satisfied
        by the providers of the current allocations for the instance during
        rebuild of the instance. If the traits cannot be
        satisfied, fails the action by raising a NoValidHost exception.

        :raises: NoValidHost exception in case the traits on the providers
                 of the allocated resources for the instance do not match
                 the required traits on the image.
        """
        image_meta = objects.ImageMeta.from_image_ref(
            context, self.image_api, image_ref)
        if ('properties' not in image_meta or
                'traits_required' not in image_meta.properties or not
                image_meta.properties.traits_required):
            return

        image_traits = set(image_meta.properties.traits_required)

        # check any of the image traits are forbidden in flavor traits.
        # if so raise an exception
        extra_specs = instance.flavor.extra_specs
        forbidden_flavor_traits = set()
        for key, val in extra_specs.items():
            if key.startswith('trait'):
                # get the actual key.
                prefix, parsed_key = key.split(':', 1)
                if val == 'forbidden':
                    forbidden_flavor_traits.add(parsed_key)

        forbidden_traits = image_traits & forbidden_flavor_traits

        if forbidden_traits:
            raise exception.NoValidHost(
                reason=_("Image traits are part of forbidden "
                         "traits in flavor associated with the server. "
                         "Either specify a different image during rebuild "
                         "or create a new server with the specified image "
                         "and a compatible flavor."))
            return

        # If image traits are present, then validate against allocations.
        allocations = self.report_client.get_allocations_for_consumer(
            context, instance.uuid)
        instance_rp_uuids = list(allocations)

        # Get provider tree for the instance. We use the uuid of the host
        # on which the instance is rebuilding to get the provider tree.
        compute_node = objects.ComputeNode.get_by_host_and_nodename(
            context, instance.host, instance.node)

        # TODO(karimull): Call with a read-only version, when available.
        instance_rp_tree = (
            self.report_client.get_provider_tree_and_ensure_root(
                context, compute_node.uuid))

        traits_in_instance_rps = set()

        for rp_uuid in instance_rp_uuids:
            traits_in_instance_rps.update(
                instance_rp_tree.data(rp_uuid).traits)

        missing_traits = image_traits - traits_in_instance_rps

        if missing_traits:
            raise exception.NoValidHost(
                reason=_("Image traits cannot be "
                         "satisfied by the current resource providers. "
                         "Either specify a different image during rebuild "
                         "or create a new server with the specified image."))

    # TODO(avolkov): move method to bdm
    @staticmethod
    def _volume_size(instance_type, bdm):
        size = bdm.get('volume_size')
        # NOTE (ndipanov): inherit flavor size only for swap and ephemeral
        if (size is None and bdm.get('source_type') == 'blank' and
                bdm.get('destination_type') == 'local'):
            if bdm.get('guest_format') == 'swap':
                size = instance_type.get('swap', 0)
            else:
                size = instance_type.get('ephemeral_gb', 0)
        return size

    def _create_block_device_mapping(self, cell, instance_type, instance_uuid,
                                     block_device_mapping):
        """Create the BlockDeviceMapping objects in the db.

        This method makes a copy of the list in order to avoid using the same
        id field in case this is called for multiple instances.
        """
        LOG.debug("block_device_mapping %s", list(block_device_mapping),
                  instance_uuid=instance_uuid)
        instance_block_device_mapping = copy.deepcopy(block_device_mapping)
        for bdm in instance_block_device_mapping:
            bdm.volume_size = self._volume_size(instance_type, bdm)
            bdm.instance_uuid = instance_uuid
            with obj_target_cell(bdm, cell):
                bdm.update_or_create()
        return instance_block_device_mapping

    def _create_tags(self, context, instance_uuid, tags):
        """Create the Tags objects in the db."""
        if tags:
            tag_list = [tag.tag for tag in tags]
            instance_tags = objects.TagList.create(
                context, instance_uuid, tag_list)
            return instance_tags
        else:
            return tags

    def _bury_in_cell0(self, context, request_spec, exc,
                       build_requests=None, instances=None,
                       block_device_mapping=None,
                       tags=None):
        """Ensure all provided build_requests and instances end up in cell0.

        Cell0 is the fake cell we schedule dead instances to when we can't
        schedule them somewhere real. Requests that don't yet have instances
        will get a new instance, created in cell0. Instances that have not yet
        been created will be created in cell0. All build requests are destroyed
        after we're done. Failure to delete a build request will trigger the
        instance deletion, just like the happy path in
        schedule_and_build_instances() below.
        """
        try:
            cell0 = objects.CellMapping.get_by_uuid(
                context, objects.CellMapping.CELL0_UUID)
        except exception.CellMappingNotFound:
            # Not yet setup for cellsv2. Instances will need to be written
            # to the configured database. This will become a deployment
            # error in Ocata.
            LOG.error('No cell mapping found for cell0 while '
                      'trying to record scheduling failure. '
                      'Setup is incomplete.')
            return

        build_requests = build_requests or []
        instances = instances or []
        instances_by_uuid = {inst.uuid: inst for inst in instances}
        for build_request in build_requests:
            if build_request.instance_uuid not in instances_by_uuid:
                # This is an instance object with no matching db entry.
                instance = build_request.get_new_instance(context)
                instances_by_uuid[instance.uuid] = instance

        updates = {'vm_state': vm_states.ERROR, 'task_state': None}
        for instance in instances_by_uuid.values():
            with obj_target_cell(instance, cell0) as cctxt:
                instance.create()

                # NOTE(mnaser): In order to properly clean-up volumes after
                #               being buried in cell0, we need to store BDMs.
                if block_device_mapping:
                    self._create_block_device_mapping(
                       cell0, instance.flavor, instance.uuid,
                       block_device_mapping)

                self._create_tags(cctxt, instance.uuid, tags)

                # Use the context targeted to cell0 here since the instance is
                # now in cell0.
                self._set_vm_state_and_notify(
                    cctxt, instance.uuid, 'build_instances', updates,
                    exc, request_spec)
                try:
                    # We don't need the cell0-targeted context here because the
                    # instance mapping is in the API DB.
                    inst_mapping = \
                        objects.InstanceMapping.get_by_instance_uuid(
                            context, instance.uuid)
                    inst_mapping.cell_mapping = cell0
                    inst_mapping.save()
                except exception.InstanceMappingNotFound:
                    pass

        for build_request in build_requests:
            try:
                build_request.destroy()
            except exception.BuildRequestNotFound:
                # Instance was deleted before we finished scheduling
                inst = instances_by_uuid[build_request.instance_uuid]
                with obj_target_cell(inst, cell0):
                    inst.destroy()

    def schedule_and_build_instances(self, context, build_requests,
                                     request_specs, image,
                                     admin_password, injected_files,
                                     requested_networks, block_device_mapping,
                                     tags=None):
        # Add all the UUIDs for the instances
        instance_uuids = [spec.instance_uuid for spec in request_specs]
        try:
            host_lists = self._schedule_instances(context, request_specs[0],
                    instance_uuids, return_alternates=True)
        except Exception as exc:
            LOG.exception('Failed to schedule instances')
            self._bury_in_cell0(context, request_specs[0], exc,
                                build_requests=build_requests,
                                block_device_mapping=block_device_mapping,
                                tags=tags)
            return

        host_mapping_cache = {}
        cell_mapping_cache = {}
        instances = []
        host_az = {}  # host=az cache to optimize multi-create

        for (build_request, request_spec, host_list) in six.moves.zip(
                build_requests, request_specs, host_lists):
            instance = build_request.get_new_instance(context)
            # host_list is a list of one or more Selection objects, the first
            # of which has been selected and its resources claimed.
            host = host_list[0]
            # Convert host from the scheduler into a cell record
            if host.service_host not in host_mapping_cache:
                try:
                    host_mapping = objects.HostMapping.get_by_host(
                        context, host.service_host)
                    host_mapping_cache[host.service_host] = host_mapping
                except exception.HostMappingNotFound as exc:
                    LOG.error('No host-to-cell mapping found for selected '
                              'host %(host)s. Setup is incomplete.',
                              {'host': host.service_host})
                    self._bury_in_cell0(
                        context, request_spec, exc,
                        build_requests=[build_request], instances=[instance],
                        block_device_mapping=block_device_mapping,
                        tags=tags)
                    # This is a placeholder in case the quota recheck fails.
                    instances.append(None)
                    continue
            else:
                host_mapping = host_mapping_cache[host.service_host]

            cell = host_mapping.cell_mapping

            # Before we create the instance, let's make one final check that
            # the build request is still around and wasn't deleted by the user
            # already.
            try:
                objects.BuildRequest.get_by_instance_uuid(
                    context, instance.uuid)
            except exception.BuildRequestNotFound:
                # the build request is gone so we're done for this instance
                LOG.debug('While scheduling instance, the build request '
                          'was already deleted.', instance=instance)
                # This is a placeholder in case the quota recheck fails.
                instances.append(None)
                rc = self.scheduler_client.reportclient
                rc.delete_allocation_for_instance(context, instance.uuid)
                continue
            else:
                if host.service_host not in host_az:
                    host_az[host.service_host] = (
                        availability_zones.get_host_availability_zone(
                            context, host.service_host))
                instance.availability_zone = host_az[host.service_host]
                with obj_target_cell(instance, cell):
                    instance.create()
                    instances.append(instance)
                    cell_mapping_cache[instance.uuid] = cell

        # NOTE(melwitt): We recheck the quota after creating the
        # objects to prevent users from allocating more resources
        # than their allowed quota in the event of a race. This is
        # configurable because it can be expensive if strict quota
        # limits are not required in a deployment.
        if CONF.quota.recheck_quota:
            try:
                compute_utils.check_num_instances_quota(
                    context, instance.flavor, 0, 0,
                    orig_num_req=len(build_requests))
            except exception.TooManyInstances as exc:
                with excutils.save_and_reraise_exception():
                    self._cleanup_build_artifacts(context, exc, instances,
                                                  build_requests,
                                                  request_specs,
                                                  block_device_mapping, tags,
                                                  cell_mapping_cache)

        zipped = six.moves.zip(build_requests, request_specs, host_lists,
                              instances)
        for (build_request, request_spec, host_list, instance) in zipped:
            if instance is None:
                # Skip placeholders that were buried in cell0 or had their
                # build requests deleted by the user before instance create.
                continue
            cell = cell_mapping_cache[instance.uuid]
            # host_list is a list of one or more Selection objects, the first
            # of which has been selected and its resources claimed.
            host = host_list.pop(0)
            alts = [(alt.service_host, alt.nodename) for alt in host_list]
            LOG.debug("Selected host: %s; Selected node: %s; Alternates: %s",
                    host.service_host, host.nodename, alts, instance=instance)
            filter_props = request_spec.to_legacy_filter_properties_dict()
            scheduler_utils.populate_retry(filter_props, instance.uuid)
            scheduler_utils.populate_filter_properties(filter_props,
                                                       host)
            # TODO(melwitt): Maybe we should set_target_cell on the contexts
            # once we map to a cell, and remove these separate with statements.
            with obj_target_cell(instance, cell) as cctxt:
                # send a state update notification for the initial create to
                # show it going from non-existent to BUILDING
                # This can lazy-load attributes on instance.
                notifications.send_update_with_states(cctxt, instance, None,
                        vm_states.BUILDING, None, None, service="conductor")
                objects.InstanceAction.action_start(
                    cctxt, instance.uuid, instance_actions.CREATE,
                    want_result=False)
                instance_bdms = self._create_block_device_mapping(
                    cell, instance.flavor, instance.uuid, block_device_mapping)
                instance_tags = self._create_tags(cctxt, instance.uuid, tags)

            # TODO(Kevin Zheng): clean this up once instance.create() handles
            # tags; we do this so the instance.create notification in
            # build_and_run_instance in nova-compute doesn't lazy-load tags
            instance.tags = instance_tags if instance_tags \
                else objects.TagList()

            # Update mapping for instance. Normally this check is guarded by
            # a try/except but if we're here we know that a newer nova-api
            # handled the build process and would have created the mapping
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
                context, instance.uuid)
            inst_mapping.cell_mapping = cell
            inst_mapping.save()

            if not self._delete_build_request(
                    context, build_request, instance, cell, instance_bdms,
                    instance_tags):
                # The build request was deleted before/during scheduling so
                # the instance is gone and we don't have anything to build for
                # this one.
                continue

            # NOTE(danms): Compute RPC expects security group names or ids
            # not objects, so convert this to a list of names until we can
            # pass the objects.
            legacy_secgroups = [s.identifier
                                for s in request_spec.security_groups]
            with obj_target_cell(instance, cell) as cctxt:
                self.compute_rpcapi.build_and_run_instance(
                    cctxt, instance=instance, image=image,
                    request_spec=request_spec,
                    filter_properties=filter_props,
                    admin_password=admin_password,
                    injected_files=injected_files,
                    requested_networks=requested_networks,
                    security_groups=legacy_secgroups,
                    block_device_mapping=instance_bdms,
                    host=host.service_host, node=host.nodename,
                    limits=host.limits, host_list=host_list)

    def _cleanup_build_artifacts(self, context, exc, instances, build_requests,
                                 request_specs, block_device_mappings, tags,
                                 cell_mapping_cache):
        for (instance, build_request, request_spec) in six.moves.zip(
                instances, build_requests, request_specs):
            # Skip placeholders that were buried in cell0 or had their
            # build requests deleted by the user before instance create.
            if instance is None:
                continue
            updates = {'vm_state': vm_states.ERROR, 'task_state': None}
            cell = cell_mapping_cache[instance.uuid]
            with try_target_cell(context, cell) as cctxt:
                self._set_vm_state_and_notify(cctxt, instance.uuid,
                                              'build_instances', updates, exc,
                                              request_spec)

            # TODO(mnaser): The cell mapping should already be populated by
            #               this point to avoid setting it below here.
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
                context, instance.uuid)
            inst_mapping.cell_mapping = cell
            inst_mapping.save()

            # In order to properly clean-up volumes when deleting a server in
            # ERROR status with no host, we need to store BDMs in the same
            # cell.
            if block_device_mappings:
                self._create_block_device_mapping(
                    cell, instance.flavor, instance.uuid,
                    block_device_mappings)

            # Like BDMs, the server tags provided by the user when creating the
            # server should be persisted in the same cell so they can be shown
            # from the API.
            if tags:
                with nova_context.target_cell(context, cell) as cctxt:
                    self._create_tags(cctxt, instance.uuid, tags)

            # Be paranoid about artifacts being deleted underneath us.
            try:
                build_request.destroy()
            except exception.BuildRequestNotFound:
                pass
            try:
                request_spec.destroy()
            except exception.RequestSpecNotFound:
                pass

    def _delete_build_request(self, context, build_request, instance, cell,
                              instance_bdms, instance_tags):
        """Delete a build request after creating the instance in the cell.

        This method handles cleaning up the instance in case the build request
        is already deleted by the time we try to delete it.

        :param context: the context of the request being handled
        :type context: nova.context.RequestContext
        :param build_request: the build request to delete
        :type build_request: nova.objects.BuildRequest
        :param instance: the instance created from the build_request
        :type instance: nova.objects.Instance
        :param cell: the cell in which the instance was created
        :type cell: nova.objects.CellMapping
        :param instance_bdms: list of block device mappings for the instance
        :type instance_bdms: nova.objects.BlockDeviceMappingList
        :param instance_tags: list of tags for the instance
        :type instance_tags: nova.objects.TagList
        :returns: True if the build request was successfully deleted, False if
            the build request was already deleted and the instance is now gone.
        """
        try:
            build_request.destroy()
        except exception.BuildRequestNotFound:
            # This indicates an instance deletion request has been
            # processed, and the build should halt here. Clean up the
            # bdm, tags and instance record.
            with obj_target_cell(instance, cell) as cctxt:
                with compute_utils.notify_about_instance_delete(
                        self.notifier, cctxt, instance):
                    try:
                        instance.destroy()
                    except exception.InstanceNotFound:
                        pass
                    except exception.ObjectActionError:
                        # NOTE(melwitt): Instance became scheduled during
                        # the destroy, "host changed". Refresh and re-destroy.
                        try:
                            instance.refresh()
                            instance.destroy()
                        except exception.InstanceNotFound:
                            pass
            for bdm in instance_bdms:
                with obj_target_cell(bdm, cell):
                    try:
                        bdm.destroy()
                    except exception.ObjectActionError:
                        pass
            if instance_tags:
                with try_target_cell(context, cell) as target_ctxt:
                    try:
                        objects.TagList.destroy(target_ctxt, instance.uuid)
                    except exception.InstanceNotFound:
                        pass
            return False
        return True
