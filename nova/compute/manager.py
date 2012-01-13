# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Handles all processes relating to instances (guest vms).

The :py:class:`ComputeManager` class is a :py:class:`nova.manager.Manager` that
handles RPC calls relating to creating instances.  It is responsible for
building a disk image, launching it via the underlying virtualization driver,
responding to calls to check its state, attaching persistent storage, and
terminating it.

**Related Flags**

:instances_path:  Where instances are kept on disk
:compute_driver:  Name of class that is used to handle virtualization, loaded
                  by :func:`nova.utils.import_object`

"""

import functools
import os
import socket
import sys
import tempfile
import time

from eventlet import greenthread

from nova import block_device
import nova.context
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import task_states
from nova.compute.utils import notify_usage_exists
from nova.compute import vm_states
from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import manager
from nova import network
from nova.notifier import api as notifier
from nova import rpc
from nova import utils
from nova.virt import driver
from nova import volume


FLAGS = flags.FLAGS
flags.DEFINE_string('instances_path', '$state_path/instances',
                    'where instances are stored on disk')
flags.DEFINE_string('compute_driver', 'nova.virt.connection.get_connection',
                    'Driver to use for controlling virtualization')
flags.DEFINE_string('console_host', socket.gethostname(),
                    'Console proxy host to use to connect to instances on'
                    'this host.')
flags.DEFINE_integer('live_migration_retry_count', 30,
                     "Retry count needed in live_migration."
                     " sleep 1 sec for each count")
flags.DEFINE_integer("reboot_timeout", 0,
                     "Automatically hard reboot an instance if it has been "
                     "stuck in a rebooting state longer than N seconds."
                     " Set to 0 to disable.")
flags.DEFINE_integer("rescue_timeout", 0,
                     "Automatically unrescue an instance after N seconds."
                     " Set to 0 to disable.")
flags.DEFINE_integer("resize_confirm_window", 0,
                     "Automatically confirm resizes after N seconds."
                     " Set to 0 to disable.")
flags.DEFINE_integer('host_state_interval', 120,
                     'Interval in seconds for querying the host status')
flags.DEFINE_integer("running_deleted_instance_timeout", 0,
                     "Number of seconds after being deleted when a"
                     " still-running instance should be considered"
                     " eligible for cleanup.")
flags.DEFINE_integer("running_deleted_instance_poll_interval", 30,
                     "Number of periodic scheduler ticks to wait between"
                     " runs of the cleanup task.")
flags.DEFINE_string("running_deleted_instance_action", "noop",
                     "Action to take if a running deleted instance is"
                     " detected. Valid options are 'noop', 'log', and"
                     " 'reap'. Set to 'noop' to disable.")

LOG = logging.getLogger('nova.compute.manager')


def publisher_id(host=None):
    return notifier.publisher_id("compute", host)


def checks_instance_lock(function):
    """Decorator to prevent action against locked instances for non-admins."""
    @functools.wraps(function)
    def decorated_function(self, context, instance_uuid, *args, **kwargs):
        LOG.info(_("check_instance_lock: decorating: |%s|"), function,
                 context=context)
        LOG.info(_("check_instance_lock: arguments: |%(self)s| |%(context)s|"
                " |%(instance_uuid)s|") % locals(), context=context)
        locked = self.get_lock(context, instance_uuid)
        admin = context.is_admin
        LOG.info(_("check_instance_lock: locked: |%s|"), locked,
                 context=context)
        LOG.info(_("check_instance_lock: admin: |%s|"), admin,
                 context=context)

        # if admin or unlocked call function otherwise log error
        if admin or not locked:
            LOG.info(_("check_instance_lock: executing: |%s|"), function,
                     context=context)
            function(self, context, instance_uuid, *args, **kwargs)
        else:
            LOG.error(_("check_instance_lock: not executing |%s|"),
                      function, context=context)
            return False

    return decorated_function


def wrap_instance_fault(function):
    """Wraps a method to catch exceptions related to instances.

    This decorator wraps a method to catch any exceptions having to do with
    an instance that may get thrown. It then logs an instance fault in the db.
    """
    @functools.wraps(function)
    def decorated_function(self, context, instance_uuid, *args, **kwargs):
        try:
            return function(self, context, instance_uuid, *args, **kwargs)
        except exception.InstanceNotFound:
            raise
        except Exception, e:
            with utils.save_and_reraise_exception():
                self.add_instance_fault_from_exc(context, instance_uuid, e)

    return decorated_function


def _get_image_meta(context, image_ref):
    image_service, image_id = nova.image.get_image_service(context, image_ref)
    return image_service.show(context, image_id)


class ComputeManager(manager.SchedulerDependentManager):
    """Manages the running instances from creation to destruction."""

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        # TODO(vish): sync driver creation logic with the rest of the system
        #             and re-document the module docstring
        if not compute_driver:
            compute_driver = FLAGS.compute_driver
        try:
            self.driver = utils.check_isinstance(
                                        utils.import_object(compute_driver),
                                        driver.ComputeDriver)
        except ImportError as e:
            LOG.error(_("Unable to load the virtualization driver: %s") % (e))
            sys.exit(1)

        self.network_api = network.API()
        self.volume_api = volume.API()
        self.network_manager = utils.import_object(FLAGS.network_manager)
        self._last_host_check = 0
        self._last_bw_usage_poll = 0
        super(ComputeManager, self).__init__(service_name="compute",
                                             *args, **kwargs)

    def _instance_update(self, context, instance_id, **kwargs):
        """Update an instance in the database using kwargs as value."""
        return self.db.instance_update(context, instance_id, kwargs)

    def init_host(self):
        """Initialization for a standalone compute service."""
        self.driver.init_host(host=self.host)
        context = nova.context.get_admin_context()
        instances = self.db.instance_get_all_by_host(context, self.host)
        for instance in instances:
            instance_uuid = instance['uuid']
            db_state = instance['power_state']
            drv_state = self._get_power_state(context, instance)

            expect_running = db_state == power_state.RUNNING \
                             and drv_state != db_state

            LOG.debug(_('Current state of %(instance_uuid)s is %(drv_state)s, '
                        'state in DB is %(db_state)s.'), locals())

            if (expect_running and FLAGS.resume_guests_state_on_host_boot)\
               or FLAGS.start_guests_on_host_boot:
                LOG.info(_('Rebooting instance %(instance_uuid)s after '
                            'nova-compute restart.'), locals())
                self.reboot_instance(context, instance['uuid'])
            elif drv_state == power_state.RUNNING:
                # Hyper-V and VMWareAPI drivers will raise an exception
                try:
                    net_info = self._get_instance_nw_info(context, instance)
                    self.driver.ensure_filtering_rules_for_instance(instance,
                                                                    net_info)
                except NotImplementedError:
                    LOG.warning(_('Hypervisor driver does not '
                            'support firewall rules'))

    def _get_power_state(self, context, instance):
        """Retrieve the power state for the given instance."""
        LOG.debug(_('Checking state of %s'), instance['uuid'])
        try:
            return self.driver.get_info(instance['name'])["state"]
        except exception.NotFound:
            return power_state.FAILED

    def get_console_topic(self, context, **kwargs):
        """Retrieves the console host for a project on this host.

        Currently this is just set in the flags for each compute host.

        """
        #TODO(mdragon): perhaps make this variable by console_type?
        return self.db.queue_get_for(context,
                                     FLAGS.console_topic,
                                     FLAGS.console_host)

    def get_console_pool_info(self, context, console_type):
        return self.driver.get_console_pool_info(console_type)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_security_group_rules(self, context, security_group_id,
                                     **kwargs):
        """Tell the virtualization driver to refresh security group rules.

        Passes straight through to the virtualization driver.

        """
        return self.driver.refresh_security_group_rules(security_group_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_security_group_members(self, context,
                                       security_group_id, **kwargs):
        """Tell the virtualization driver to refresh security group members.

        Passes straight through to the virtualization driver.

        """
        return self.driver.refresh_security_group_members(security_group_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def refresh_provider_fw_rules(self, context, **_kwargs):
        """This call passes straight through to the virtualization driver."""
        return self.driver.refresh_provider_fw_rules()

    def _get_instance_nw_info(self, context, instance):
        """Get a list of dictionaries of network data of an instance.
        Returns an empty list if stub_network flag is set."""
        network_info = []
        if not FLAGS.stub_network:
            network_info = self.network_api.get_instance_nw_info(context,
                                                                 instance)
        return network_info

    def _setup_block_device_mapping(self, context, instance):
        """setup volumes for block device mapping"""
        block_device_mapping = []
        swap = None
        ephemerals = []
        for bdm in self.db.block_device_mapping_get_all_by_instance(
            context, instance['id']):
            LOG.debug(_("setting up bdm %s"), bdm)

            if bdm['no_device']:
                continue
            if bdm['virtual_name']:
                virtual_name = bdm['virtual_name']
                device_name = bdm['device_name']
                assert block_device.is_swap_or_ephemeral(virtual_name)
                if virtual_name == 'swap':
                    swap = {'device_name': device_name,
                            'swap_size': bdm['volume_size']}
                elif block_device.is_ephemeral(virtual_name):
                    eph = {'num': block_device.ephemeral_num(virtual_name),
                           'virtual_name': virtual_name,
                           'device_name': device_name,
                           'size': bdm['volume_size']}
                    ephemerals.append(eph)
                continue

            if ((bdm['snapshot_id'] is not None) and
                (bdm['volume_id'] is None)):
                # TODO(yamahata): default name and description
                snapshot = self.volume_api.get_snapshot(context,
                                                        bdm['snapshot_id'])
                vol = self.volume_api.create(context, bdm['volume_size'],
                                             '', '', snapshot)
                # TODO(yamahata): creating volume simultaneously
                #                 reduces creation time?
                self.volume_api.wait_creation(context, vol)
                self.db.block_device_mapping_update(
                    context, bdm['id'], {'volume_id': vol['id']})
                bdm['volume_id'] = vol['id']

            if bdm['volume_id'] is not None:
                volume = self.volume_api.get(context, bdm['volume_id'])
                self.volume_api.check_attach(context, volume)
                cinfo = self._attach_volume_boot(context,
                                                 instance,
                                                 volume,
                                                 bdm['device_name'])
                self.db.block_device_mapping_update(
                        context, bdm['id'],
                        {'connection_info': utils.dumps(cinfo)})
                block_device_mapping.append({'connection_info': cinfo,
                                             'mount_device':
                                             bdm['device_name']})

        return (swap, ephemerals, block_device_mapping)

    def _is_instance_terminated(self, instance_uuid):
        """Instance in DELETING task state or not found in DB"""
        context = nova.context.get_admin_context()
        try:
            instance = self.db.instance_get_by_uuid(context, instance_uuid)
            if instance['task_state'] == task_states.DELETING:
                return True
            return False
        except Exception:
            return True

    def _shutdown_instance_even_if_deleted(self, context, instance_uuid):
        """Call terminate_instance even for already deleted instances"""
        LOG.info(_("Going to force the deletion of the vm %(instance_uuid)s, "
                   "even if it is deleted") % locals())
        try:
            try:
                self.terminate_instance(context, instance_uuid)
            except exception.InstanceNotFound:
                LOG.info(_("Instance %(instance_uuid)s did not exist in the "
                         "DB, but I will shut it down anyway using a special "
                         "context") % locals())
                ctxt = nova.context.get_admin_context(True)
                self.terminate_instance(ctxt, instance_uuid)
        except Exception as ex:
            LOG.info(_("exception terminating the instance "
                     "%(instance_uuid)s") % locals())

    def _run_instance(self, context, instance_uuid,
                      requested_networks=None,
                      injected_files=[],
                      admin_password=None,
                      **kwargs):
        """Launch a new instance with specified options."""
        context = context.elevated()
        try:
            instance = self.db.instance_get_by_uuid(context, instance_uuid)
            self._check_instance_not_already_created(context, instance)
            image_meta = self._check_image_size(context, instance)
            self._start_building(context, instance)
            network_info = self._allocate_network(context, instance,
                                                  requested_networks)
            try:
                block_device_info = self._prep_block_device(context, instance)
                instance = self._spawn(context, instance, image_meta,
                                       network_info, block_device_info,
                                       injected_files, admin_password)
            except Exception:
                with utils.save_and_reraise_exception():
                    self._deallocate_network(context, instance)
            self._notify_about_instance_usage(instance)
            if self._is_instance_terminated(instance_uuid):
                raise exception.InstanceNotFound
        except exception.InstanceNotFound:
            LOG.exception(_("Instance %s not found.") % instance_uuid)
            # assuming the instance was already deleted, run "delete" again
            # just in case
            self._shutdown_instance_even_if_deleted(context, instance_uuid)
            return
        except Exception as e:
            with utils.save_and_reraise_exception():
                self._instance_update(context, instance_uuid,
                                      vm_state=vm_states.ERROR)

    def _check_instance_not_already_created(self, context, instance):
        """Ensure an instance with the same name is not already present."""
        if instance['name'] in self.driver.list_instances():
            raise exception.Error(_("Instance has already been created"))

    def _check_image_size(self, context, instance):
        """Ensure image is smaller than the maximum size allowed by the
        instance_type.

        The image stored in Glance is potentially compressed, so we use two
        checks to ensure that the size isn't exceeded:

            1) This one - checks compressed size, this a quick check to
               eliminate any images which are obviously too large

            2) Check uncompressed size in nova.virt.xenapi.vm_utils. This
               is a slower check since it requires uncompressing the entire
               image, but is accurate because it reflects the image's
               actual size.
        """
        image_meta = _get_image_meta(context, instance['image_ref'])

        try:
            size_bytes = image_meta['size']
        except KeyError:
            # Size is not a required field in the image service (yet), so
            # we are unable to rely on it being there even though it's in
            # glance.

            # TODO(jk0): Should size be required in the image service?
            return image_meta

        instance_type_id = instance['instance_type_id']
        instance_type = instance_types.get_instance_type(instance_type_id)
        allowed_size_gb = instance_type['local_gb']

        # NOTE(jk0): Since libvirt uses local_gb as a secondary drive, we
        # need to handle potential situations where local_gb is 0. This is
        # the default for m1.tiny.
        if allowed_size_gb == 0:
            return image_meta

        allowed_size_bytes = allowed_size_gb * 1024 * 1024 * 1024

        image_id = image_meta['id']
        LOG.debug(_("image_id=%(image_id)s, image_size_bytes="
                    "%(size_bytes)d, allowed_size_bytes="
                    "%(allowed_size_bytes)d") % locals())

        if size_bytes > allowed_size_bytes:
            LOG.info(_("Image '%(image_id)s' size %(size_bytes)d exceeded"
                       " instance_type allowed size "
                       "%(allowed_size_bytes)d")
                       % locals())
            raise exception.ImageTooLarge()

        return image_meta

    def _start_building(self, context, instance):
        """Save the host and launched_on fields and log appropriately."""
        LOG.audit(_("instance %s: starting..."), instance['uuid'],
                  context=context)
        self._instance_update(context, instance['uuid'],
                              host=self.host, launched_on=self.host,
                              vm_state=vm_states.BUILDING,
                              task_state=None)

    def _allocate_network(self, context, instance, requested_networks):
        """Allocate networks for an instance and return the network info"""
        if FLAGS.stub_network:
            msg = _("Skipping network allocation for instance %s")
            LOG.debug(msg % instance['uuid'])
            return []
        self._instance_update(context, instance['uuid'],
                              vm_state=vm_states.BUILDING,
                              task_state=task_states.NETWORKING)
        is_vpn = instance['image_ref'] == str(FLAGS.vpn_image_id)
        try:
            network_info = self.network_api.allocate_for_instance(
                                context, instance, vpn=is_vpn,
                                requested_networks=requested_networks)
        except Exception:
            msg = _("Instance %s failed network setup")
            LOG.exception(msg % instance['uuid'])
            raise
        LOG.debug(_("instance network_info: |%s|"), network_info)
        return network_info

    def _prep_block_device(self, context, instance):
        """Set up the block device for an instance with error logging"""
        self._instance_update(context, instance['uuid'],
                              vm_state=vm_states.BUILDING,
                              task_state=task_states.BLOCK_DEVICE_MAPPING)
        try:
            mapping = self._setup_block_device_mapping(context, instance)
            swap, ephemerals, block_device_mapping = mapping
        except Exception:
            msg = _("Instance %s failed block device setup")
            LOG.exception(msg % instance['uuid'])
            raise
        return {'root_device_name': instance['root_device_name'],
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

    def _spawn(self, context, instance, image_meta, network_info,
               block_device_info, injected_files, admin_pass):
        """Spawn an instance with error logging and update its power state"""
        self._instance_update(context, instance['uuid'],
                              vm_state=vm_states.BUILDING,
                              task_state=task_states.SPAWNING)
        instance['injected_files'] = injected_files
        instance['admin_pass'] = admin_pass
        try:
            self.driver.spawn(context, instance, image_meta,
                              network_info, block_device_info)
        except Exception:
            msg = _("Instance %s failed to spawn")
            LOG.exception(msg % instance['uuid'])
            raise

        current_power_state = self._get_power_state(context, instance)
        return self._instance_update(context, instance['uuid'],
                                     power_state=current_power_state,
                                     vm_state=vm_states.ACTIVE,
                                     task_state=None,
                                     launched_at=utils.utcnow())

    def _notify_about_instance_usage(self, instance):
        usage_info = utils.usage_from_instance(instance)
        notifier.notify('compute.%s' % self.host,
                        'compute.instance.create',
                        notifier.INFO, usage_info)

    def _deallocate_network(self, context, instance):
        if not FLAGS.stub_network:
            msg = _("deallocating network for instance: %s")
            LOG.debug(msg % instance['uuid'])
            self.network_api.deallocate_for_instance(context, instance)

    def _get_instance_volume_bdms(self, context, instance_id):
        bdms = self.db.block_device_mapping_get_all_by_instance(context,
                                                                instance_id)
        return [bdm for bdm in bdms if bdm['volume_id']]

    def _get_instance_volume_bdm(self, context, instance_id, volume_id):
        bdms = self._get_instance_volume_bdms(context, instance_id)
        for bdm in bdms:
            # NOTE(vish): Comparing as strings because the os_api doesn't
            #             convert to integer and we may wish to support uuids
            #             in the future.
            if str(bdm['volume_id']) == str(volume_id):
                return bdm

    def _get_instance_volume_block_device_info(self, context, instance_id):
        bdms = self._get_instance_volume_bdms(context, instance_id)
        block_device_mapping = []
        for bdm in bdms:
            cinfo = utils.loads(bdm['connection_info'])
            block_device_mapping.append({'connection_info': cinfo,
                                         'mount_device':
                                         bdm['device_name']})
        # NOTE(vish): The mapping is passed in so the driver can disconnect
        #             from remote volumes if necessary
        return {'block_device_mapping': block_device_mapping}

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def run_instance(self, context, instance_uuid, **kwargs):
        self._run_instance(context, instance_uuid, **kwargs)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def start_instance(self, context, instance_uuid):
        """Starting an instance on this host."""
        # TODO(yamahata): injected_files isn't supported.
        #                 Anyway OSAPI doesn't support stop/start yet
        # FIXME(vish): I've kept the files during stop instance, but
        #              I think start will fail due to the files still
        self._run_instance(context, instance_uuid)

    def _shutdown_instance(self, context, instance, action_str):
        """Shutdown an instance on this host."""
        context = context.elevated()
        instance_id = instance['id']
        instance_uuid = instance['uuid']
        LOG.audit(_("%(action_str)s instance %(instance_uuid)s") %
                  {'action_str': action_str, 'instance_uuid': instance_uuid},
                  context=context)

        network_info = self._get_instance_nw_info(context, instance)
        if not FLAGS.stub_network:
            self.network_api.deallocate_for_instance(context, instance)

        if instance['power_state'] == power_state.SHUTOFF:
            self.db.instance_destroy(context, instance_id)
            raise exception.Error(_('trying to destroy already destroyed'
                                    ' instance: %s') % instance_uuid)
        # NOTE(vish) get bdms before destroying the instance
        bdms = self._get_instance_volume_bdms(context, instance_id)
        block_device_info = self._get_instance_volume_block_device_info(
            context, instance_id)
        self.driver.destroy(instance, network_info, block_device_info)
        for bdm in bdms:
            try:
                # NOTE(vish): actual driver detach done in driver.destroy, so
                #             just tell nova-volume that we are done with it.
                volume = self.volume_api.get(context, bdm['volume_id'])
                self.volume_api.terminate_connection(context,
                                                     volume,
                                                     FLAGS.my_ip)
                self.volume_api.detach(context, volume)
            except exception.DiskNotFound as exc:
                LOG.warn(_("Ignoring DiskNotFound: %s") % exc)

    def _cleanup_volumes(self, context, instance_id):
        bdms = self.db.block_device_mapping_get_all_by_instance(context,
                                                                instance_id)
        for bdm in bdms:
            LOG.debug(_("terminating bdm %s") % bdm)
            if bdm['volume_id'] and bdm['delete_on_termination']:
                volume = self.volume_api.get(context, bdm['volume_id'])
                self.volume_api.delete(context, volume)
            # NOTE(vish): bdms will be deleted on instance destroy

    def _delete_instance(self, context, instance):
        """Delete an instance on this host."""
        instance_id = instance['id']
        self._shutdown_instance(context, instance, 'Terminating')
        self._cleanup_volumes(context, instance_id)
        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.DELETED,
                              task_state=None,
                              terminated_at=utils.utcnow())

        self.db.instance_destroy(context, instance_id)

        usage_info = utils.usage_from_instance(instance)
        notifier.notify('compute.%s' % self.host,
                        'compute.instance.delete',
                        notifier.INFO, usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def terminate_instance(self, context, instance_uuid):
        """Terminate an instance on this host."""
        elevated = context.elevated()
        instance = self.db.instance_get_by_uuid(elevated, instance_uuid)
        notify_usage_exists(instance, current_period=True)
        self._delete_instance(context, instance)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def stop_instance(self, context, instance_uuid):
        """Stopping an instance on this host."""
        instance = self.db.instance_get_by_uuid(context, instance_uuid)
        self._shutdown_instance(context, instance, 'Stopping')
        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.STOPPED,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def power_off_instance(self, context, instance_uuid):
        """Power off an instance on this host."""
        instance = self.db.instance_get_by_uuid(context, instance_uuid)
        self.driver.power_off(instance)
        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance_uuid,
                              power_state=current_power_state,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def power_on_instance(self, context, instance_uuid):
        """Power on an instance on this host."""
        instance = self.db.instance_get_by_uuid(context, instance_uuid)
        self.driver.power_on(instance)
        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance_uuid,
                              power_state=current_power_state,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def rebuild_instance(self, context, instance_uuid, **kwargs):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        :param context: `nova.RequestContext` object
        :param instance_uuid: Instance Identifier (UUID)
        :param injected_files: Files to inject
        :param new_pass: password to set on rebuilt instance
        """
        context = context.elevated()

        LOG.audit(_("Rebuilding instance %s"), instance_uuid, context=context)

        instance = self.db.instance_get_by_uuid(context, instance_uuid)
        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance_uuid,
                              power_state=current_power_state,
                              vm_state=vm_states.REBUILDING,
                              task_state=None)

        network_info = self._get_instance_nw_info(context, instance)
        self.driver.destroy(instance, network_info)

        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.REBUILDING,
                              task_state=task_states.BLOCK_DEVICE_MAPPING)

        instance.injected_files = kwargs.get('injected_files', [])
        network_info = self.network_api.get_instance_nw_info(context,
                                                             instance)
        bd_mapping = self._setup_block_device_mapping(context, instance)

        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.REBUILDING,
                              task_state=task_states.SPAWNING)
        # pull in new password here since the original password isn't in the db
        instance.admin_pass = kwargs.get('new_pass',
                utils.generate_password(FLAGS.password_length))

        image_meta = _get_image_meta(context, instance['image_ref'])

        self.driver.spawn(context, instance, image_meta,
                          network_info, bd_mapping)

        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance_uuid,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None,
                              launched_at=utils.utcnow())

        usage_info = utils.usage_from_instance(instance)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.rebuild',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def reboot_instance(self, context, instance_uuid, reboot_type="SOFT"):
        """Reboot an instance on this host."""
        LOG.audit(_("Rebooting instance %s"), instance_uuid, context=context)
        context = context.elevated()
        instance = self.db.instance_get_by_uuid(context, instance_uuid)

        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance_uuid,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE)

        if instance['power_state'] != power_state.RUNNING:
            state = instance['power_state']
            running = power_state.RUNNING
            LOG.warn(_('trying to reboot a non-running '
                     'instance: %(instance_uuid)s (state: %(state)s '
                     'expected: %(running)s)') % locals(),
                     context=context)

        network_info = self._get_instance_nw_info(context, instance)
        self.driver.reboot(instance, network_info, reboot_type)

        current_power_state = self._get_power_state(context, instance)
        self._instance_update(context,
                              instance_uuid,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def snapshot_instance(self, context, instance_uuid, image_id,
                          image_type='snapshot', backup_type=None,
                          rotation=None):
        """Snapshot an instance on this host.

        :param context: security context
        :param instance_uuid: nova.db.sqlalchemy.models.Instance.Uuid
        :param image_id: glance.db.sqlalchemy.models.Image.Id
        :param image_type: snapshot | backup
        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        """
        if image_type == "snapshot":
            task_state = task_states.IMAGE_SNAPSHOT
        elif image_type == "backup":
            task_state = task_states.IMAGE_BACKUP
        else:
            raise Exception(_('Image type not recognized %s') % image_type)

        context = context.elevated()
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_ref['id'],
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=task_state)

        LOG.audit(_('instance %s: snapshotting'), instance_uuid,
                  context=context)

        if instance_ref['power_state'] != power_state.RUNNING:
            state = instance_ref['power_state']
            running = power_state.RUNNING
            LOG.warn(_('trying to snapshot a non-running '
                       'instance: %(instance_uuid)s (state: %(state)s '
                       'expected: %(running)s)') % locals())

        try:
            self.driver.snapshot(context, instance_ref, image_id)
        finally:
            self._instance_update(context, instance_ref['id'], task_state=None)

        if image_type == 'snapshot' and rotation:
            raise exception.ImageRotationNotAllowed()

        elif image_type == 'backup' and rotation:
            self.rotate_backups(context, instance_uuid, backup_type, rotation)

        elif image_type == 'backup':
            raise exception.RotationRequiredForBackup()

    @wrap_instance_fault
    def rotate_backups(self, context, instance_uuid, backup_type, rotation):
        """Delete excess backups associated to an instance.

        Instances are allowed a fixed number of backups (the rotation number);
        this method deletes the oldest backups that exceed the rotation
        threshold.

        :param context: security context
        :param instance_uuid: string representing uuid of instance
        :param backup_type: daily | weekly
        :param rotation: int representing how many backups to keep around;
            None if rotation shouldn't be used (as in the case of snapshots)
        """
        # NOTE(jk0): Eventually extract this out to the ImageService?
        def fetch_images():
            images = []
            marker = None
            while True:
                batch = image_service.detail(context, filters=filters,
                        marker=marker, sort_key='created_at', sort_dir='desc')
                if not batch:
                    break
                images += batch
                marker = batch[-1]['id']
            return images

        image_service = nova.image.get_default_image_service()
        filters = {'property-image_type': 'backup',
                   'property-backup_type': backup_type,
                   'property-instance_uuid': instance_uuid}

        images = fetch_images()
        num_images = len(images)
        LOG.debug(_("Found %(num_images)d images (rotation: %(rotation)d)"
                    % locals()))
        if num_images > rotation:
            # NOTE(sirp): this deletes all backups that exceed the rotation
            # limit
            excess = len(images) - rotation
            LOG.debug(_("Rotating out %d backups" % excess))
            for i in xrange(excess):
                image = images.pop()
                image_id = image['id']
                LOG.debug(_("Deleting image %s" % image_id))
                image_service.delete(context, image_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def set_admin_password(self, context, instance_uuid, new_pass=None):
        """Set the root/admin password for an instance on this host.

        This is generally only called by API password resets after an
        image has been built.
        """

        context = context.elevated()

        if new_pass is None:
            # Generate a random password
            new_pass = utils.generate_password(FLAGS.password_length)

        max_tries = 10

        for i in xrange(max_tries):
            instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
            instance_id = instance_ref["id"]
            instance_state = instance_ref["power_state"]
            expected_state = power_state.RUNNING

            if instance_state != expected_state:
                self._instance_update(context, instance_id, task_state=None)
                raise exception.Error(_('Instance is not running'))
            else:
                try:
                    self.driver.set_admin_password(instance_ref, new_pass)
                    LOG.audit(_("Instance %s: Root password set"),
                                instance_ref["uuid"])
                    self._instance_update(context,
                                          instance_id,
                                          task_state=None)
                    break
                except NotImplementedError:
                    # NOTE(dprince): if the driver doesn't implement
                    # set_admin_password we break to avoid a loop
                    LOG.warn(_('set_admin_password is not implemented '
                             'by this driver.'))
                    self._instance_update(context,
                                          instance_id,
                                          task_state=None)
                    break
                except Exception, e:
                    # Catch all here because this could be anything.
                    LOG.exception(e)
                    if i == max_tries - 1:
                        self._instance_update(context,
                                              instance_id,
                                              task_state=None,
                                              vm_state=vm_states.ERROR)
                        # We create a new exception here so that we won't
                        # potentially reveal password information to the
                        # API caller.  The real exception is logged above
                        _msg = _('Error setting admin password')
                        raise exception.Error(_msg)
                    time.sleep(1)
                    continue

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def inject_file(self, context, instance_uuid, path, file_contents):
        """Write a file to the specified path in an instance on this host."""
        context = context.elevated()
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_state = instance_ref['power_state']
        expected_state = power_state.RUNNING
        if instance_state != expected_state:
            LOG.warn(_('trying to inject a file into a non-running '
                    'instance: %(instance_uuid)s (state: %(instance_state)s '
                    'expected: %(expected_state)s)') % locals())
        instance_uuid = instance_ref['uuid']
        msg = _('instance %(instance_uuid)s: injecting file to %(path)s')
        LOG.audit(msg % locals())
        self.driver.inject_file(instance_ref, path, file_contents)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def agent_update(self, context, instance_uuid, url, md5hash):
        """Update agent running on an instance on this host."""
        context = context.elevated()
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_state = instance_ref['power_state']
        expected_state = power_state.RUNNING
        if instance_state != expected_state:
            LOG.warn(_('trying to update agent on a non-running '
                    'instance: %(instance_uuid)s (state: %(instance_state)s '
                    'expected: %(expected_state)s)') % locals())
        instance_uuid = instance_ref['uuid']
        msg = _('instance %(instance_uuid)s: updating agent to %(url)s')
        LOG.audit(msg % locals())
        self.driver.agent_update(instance_ref, url, md5hash)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def rescue_instance(self, context, instance_uuid, **kwargs):
        """
        Rescue an instance on this host.
        :param rescue_password: password to set on rescue instance
        """

        LOG.audit(_('instance %s: rescuing'), instance_uuid, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_ref.admin_pass = kwargs.get('rescue_password',
                utils.generate_password(FLAGS.password_length))
        network_info = self._get_instance_nw_info(context, instance_ref)
        image_meta = _get_image_meta(context, instance_ref['image_ref'])

        self.driver.rescue(context, instance_ref, network_info, image_meta)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.RESCUED,
                              task_state=None,
                              power_state=current_power_state)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def unrescue_instance(self, context, instance_uuid):
        """Rescue an instance on this host."""
        LOG.audit(_('instance %s: unrescuing'), instance_uuid, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        network_info = self._get_instance_nw_info(context, instance_ref)

        self.driver.unrescue(instance_ref, network_info)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.ACTIVE,
                              task_state=None,
                              power_state=current_power_state)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def confirm_resize(self, context, instance_uuid, migration_id):
        """Destroys the source instance."""
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)

        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.confirm_migration(
                migration_ref, instance_ref, network_info)

        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.resize.confirm',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def revert_resize(self, context, instance_uuid, migration_id):
        """Destroys the new instance on the destination machine.

        Reverts the model changes, and powers on the old instance on the
        source machine.

        """
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)

        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.destroy(instance_ref, network_info)
        topic = self.db.queue_get_for(context, FLAGS.compute_topic,
                migration_ref['source_compute'])
        rpc.cast(context, topic,
                {'method': 'finish_revert_resize',
                 'args': {'instance_uuid': instance_ref['uuid'],
                          'migration_id': migration_ref['id']},
                })

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def finish_revert_resize(self, context, instance_uuid, migration_id):
        """Finishes the second half of reverting a resize.

        Power back on the source instance and revert the resized attributes
        in the database.

        """
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)

        old_instance_type = migration_ref['old_instance_type_id']
        instance_type = instance_types.get_instance_type(old_instance_type)

        # Just roll back the record. There's no need to resize down since
        # the 'old' VM already has the preferred attributes
        self._instance_update(context,
                              instance_ref["uuid"],
                              memory_mb=instance_type['memory_mb'],
                              host=migration_ref['source_compute'],
                              vcpus=instance_type['vcpus'],
                              local_gb=instance_type['local_gb'],
                              instance_type_id=instance_type['id'])

        self.driver.finish_revert_migration(instance_ref)
        self.db.migration_update(context, migration_id,
                {'status': 'reverted'})
        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.resize.revert',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def prep_resize(self, context, instance_uuid, instance_type_id):
        """Initiates the process of moving a running instance to another host.

        Possibly changes the RAM and disk size in the process.

        """
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)

        same_host = instance_ref['host'] == FLAGS.host
        if same_host and not FLAGS.allow_resize_to_same_host:
            self._instance_update(context,
                                  instance_uuid,
                                  vm_state=vm_states.ERROR)
            msg = _('destination same as source!')
            raise exception.MigrationError(msg)

        old_instance_type_id = instance_ref['instance_type_id']
        old_instance_type = instance_types.get_instance_type(
                old_instance_type_id)
        new_instance_type = instance_types.get_instance_type(instance_type_id)

        migration_ref = self.db.migration_create(context,
                {'instance_uuid': instance_ref['uuid'],
                 'source_compute': instance_ref['host'],
                 'dest_compute': FLAGS.host,
                 'dest_host': self.driver.get_host_ip_addr(),
                 'old_instance_type_id': old_instance_type['id'],
                 'new_instance_type_id': instance_type_id,
                 'status': 'pre-migrating'})

        LOG.audit(_('instance %s: migrating'), instance_ref['uuid'],
                context=context)
        topic = self.db.queue_get_for(context, FLAGS.compute_topic,
                instance_ref['host'])
        rpc.cast(context, topic,
                {'method': 'resize_instance',
                 'args': {'instance_uuid': instance_ref['uuid'],
                          'migration_id': migration_ref['id']}})

        usage_info = utils.usage_from_instance(instance_ref,
                              new_instance_type=new_instance_type['name'],
                              new_instance_type_id=new_instance_type['id'])
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.resize.prep',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def resize_instance(self, context, instance_uuid, migration_id):
        """Starts the migration of a running instance to another host."""
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)
        instance_type_ref = self.db.instance_type_get(context,
                migration_ref.new_instance_type_id)

        self.db.migration_update(context,
                                 migration_id,
                                 {'status': 'migrating'})

        try:
            disk_info = self.driver.migrate_disk_and_power_off(
                    context, instance_ref, migration_ref['dest_host'],
                    instance_type_ref)
        except Exception, error:
            with utils.save_and_reraise_exception():
                msg = _('%s. Setting instance vm_state to ERROR')
                LOG.error(msg % error)
                self._instance_update(context,
                                      instance_uuid,
                                      vm_state=vm_states.ERROR)

        self.db.migration_update(context,
                                 migration_id,
                                 {'status': 'post-migrating'})

        service = self.db.service_get_by_host_and_topic(
                context, migration_ref['dest_compute'], FLAGS.compute_topic)
        topic = self.db.queue_get_for(context,
                                      FLAGS.compute_topic,
                                      migration_ref['dest_compute'])
        params = {'migration_id': migration_id,
                  'disk_info': disk_info,
                  'instance_uuid': instance_ref['uuid']}
        rpc.cast(context, topic, {'method': 'finish_resize',
                                  'args': params})

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def finish_resize(self, context, instance_uuid, migration_id, disk_info):
        """Completes the migration process.

        Sets up the newly transferred disk and turns on the instance at its
        new host machine.

        """
        migration_ref = self.db.migration_get(context, migration_id)

        resize_instance = False
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)
        old_instance_type_id = migration_ref['old_instance_type_id']
        new_instance_type_id = migration_ref['new_instance_type_id']
        if old_instance_type_id != new_instance_type_id:
            instance_type = instance_types.get_instance_type(
                    new_instance_type_id)
            self.db.instance_update(context, instance_ref.uuid,
                   dict(instance_type_id=instance_type['id'],
                        memory_mb=instance_type['memory_mb'],
                        vcpus=instance_type['vcpus'],
                        local_gb=instance_type['local_gb']))
            resize_instance = True

        instance_ref = self.db.instance_get_by_uuid(context,
                                            instance_ref.uuid)

        network_info = self._get_instance_nw_info(context, instance_ref)

        # Have to look up image here since we depend on disk_format later
        image_meta = _get_image_meta(context, instance_ref['image_ref'])

        try:
            self.driver.finish_migration(context, migration_ref, instance_ref,
                                         disk_info, network_info, image_meta,
                                         resize_instance)
        except Exception, error:
            with utils.save_and_reraise_exception():
                msg = _('%s. Setting instance vm_state to ERROR')
                LOG.error(msg % error)
                self._instance_update(context,
                                      instance_uuid,
                                      vm_state=vm_states.ERROR)

        self._instance_update(context,
                              instance_uuid,
                              vm_state=vm_states.ACTIVE,
                              host=migration_ref['dest_compute'],
                              task_state=task_states.RESIZE_VERIFY)

        self.db.migration_update(context, migration_id,
                {'status': 'finished', })

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def add_fixed_ip_to_instance(self, context, instance_uuid, network_id):
        """Calls network_api to add new fixed_ip to instance
        then injects the new network info and resets instance networking.

        """
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_id = instance_ref['id']
        self.network_api.add_fixed_ip_to_instance(context, instance_id,
                                                  self.host, network_id)
        usage = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                        'compute.instance.create_ip',
                        notifier.INFO, usage)

        self.inject_network_info(context, instance_ref['uuid'])
        self.reset_network(context, instance_ref['uuid'])

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def remove_fixed_ip_from_instance(self, context, instance_uuid, address):
        """Calls network_api to remove existing fixed_ip from instance
        by injecting the altered network info and resetting
        instance networking.
        """
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_id = instance_ref['id']
        self.network_api.remove_fixed_ip_from_instance(context, instance_id,
                                                       address)
        usage = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                        'compute.instance.delete_ip',
                        notifier.INFO, usage)

        self.inject_network_info(context, instance_ref['uuid'])
        self.reset_network(context, instance_ref['uuid'])

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def pause_instance(self, context, instance_uuid):
        """Pause an instance on this host."""
        LOG.audit(_('instance %s: pausing'), instance_uuid, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        self.driver.pause(instance_ref)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_ref['id'],
                              power_state=current_power_state,
                              vm_state=vm_states.PAUSED,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def unpause_instance(self, context, instance_uuid):
        """Unpause a paused instance on this host."""
        LOG.audit(_('instance %s: unpausing'), instance_uuid, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        self.driver.unpause(instance_ref)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_ref['id'],
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def host_power_action(self, context, host=None, action=None):
        """Reboots, shuts down or powers up the host."""
        return self.driver.host_power_action(host, action)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def set_host_enabled(self, context, host=None, enabled=None):
        """Sets the specified host's ability to accept new instances."""
        return self.driver.set_host_enabled(host, enabled)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_diagnostics(self, context, instance_uuid):
        """Retrieve diagnostics for an instance on this host."""
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        if instance_ref["power_state"] == power_state.RUNNING:
            LOG.audit(_("instance %s: retrieving diagnostics"), instance_uuid,
                      context=context)
            return self.driver.get_diagnostics(instance_ref)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def suspend_instance(self, context, instance_uuid):
        """Suspend the given instance."""
        LOG.audit(_('instance %s: suspending'), instance_uuid, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        self.driver.suspend(instance_ref)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_ref['id'],
                              power_state=current_power_state,
                              vm_state=vm_states.SUSPENDED,
                              task_state=None)

        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host, 'compute.instance.suspend',
                notifier.INFO, usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def resume_instance(self, context, instance_uuid):
        """Resume the given suspended instance."""
        LOG.audit(_('instance %s: resuming'), instance_uuid, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        self.driver.resume(instance_ref)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_ref['id'],
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host, 'compute.instance.resume',
                notifier.INFO, usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def lock_instance(self, context, instance_uuid):
        """Lock the given instance."""
        context = context.elevated()

        LOG.debug(_('instance %s: locking'), instance_uuid, context=context)
        self.db.instance_update(context, instance_uuid, {'locked': True})

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def unlock_instance(self, context, instance_uuid):
        """Unlock the given instance."""
        context = context.elevated()

        LOG.debug(_('instance %s: unlocking'), instance_uuid, context=context)
        self.db.instance_update(context, instance_uuid, {'locked': False})

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_lock(self, context, instance_uuid):
        """Return the boolean state of the given instance's lock."""
        context = context.elevated()
        LOG.debug(_('instance %s: getting locked state'), instance_uuid,
                  context=context)
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return instance_ref['locked']

    @checks_instance_lock
    @wrap_instance_fault
    def reset_network(self, context, instance_uuid):
        """Reset networking on the given instance."""
        instance = self.db.instance_get_by_uuid(context, instance_uuid)
        LOG.debug(_('instance %s: reset network'), instance_uuid,
                                                   context=context)
        self.driver.reset_network(instance)

    @checks_instance_lock
    @wrap_instance_fault
    def inject_network_info(self, context, instance_uuid):
        """Inject network info for the given instance."""
        LOG.debug(_('instance %s: inject network info'), instance_uuid,
                                                         context=context)
        instance = self.db.instance_get_by_uuid(context, instance_uuid)
        network_info = self._get_instance_nw_info(context, instance)
        LOG.debug(_("network_info to inject: |%s|"), network_info)

        self.driver.inject_network_info(instance, network_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_console_output(self, context, instance_uuid, tail_length=None):
        """Send the console output for the given instance."""
        context = context.elevated()
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        LOG.audit(_("Get console output for instance %s"), instance_uuid,
                  context=context)
        output = self.driver.get_console_output(instance_ref)

        if tail_length is not None:
            output = self._tail_log(output, tail_length)

        return output.decode('utf-8', 'replace').encode('ascii', 'replace')

    def _tail_log(self, log, length):
        try:
            length = int(length)
        except ValueError:
            length = 0

        if length == 0:
            return ''
        else:
            return '\n'.join(log.split('\n')[-int(length):])

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_ajax_console(self, context, instance_uuid):
        """Return connection information for an ajax console."""
        context = context.elevated()
        LOG.debug(_("instance %s: getting ajax console"), instance_uuid)
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return self.driver.get_ajax_console(instance_ref)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @wrap_instance_fault
    def get_vnc_console(self, context, instance_uuid):
        """Return connection information for a vnc console."""
        context = context.elevated()
        LOG.debug(_("instance %s: getting vnc console"), instance_uuid)
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        return self.driver.get_vnc_console(instance_ref)

    def _attach_volume_boot(self, context, instance, volume, mountpoint):
        """Attach a volume to an instance at boot time. So actual attach
        is done by instance creation"""

        instance_id = instance['id']
        instance_uuid = instance['uuid']
        volume_id = volume['id']
        context = context.elevated()
        msg = _("instance %(instance_uuid)s: booting with "
                "volume %(volume_id)s at %(mountpoint)s")
        LOG.audit(msg % locals(), context=context)
        address = FLAGS.my_ip
        connection_info = self.volume_api.initialize_connection(context,
                                                                volume,
                                                                address)
        self.volume_api.attach(context, volume, instance_id, mountpoint)
        return connection_info

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def attach_volume(self, context, instance_uuid, volume_id, mountpoint):
        """Attach a volume to an instance."""
        volume = self.volume_api.get(context, volume_id)
        context = context.elevated()
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_id = instance_ref['id']
        msg = _("instance %(instance_uuid)s: attaching volume %(volume_id)s"
                " to %(mountpoint)s")
        LOG.audit(msg % locals(), context=context)
        address = FLAGS.my_ip
        connection_info = self.volume_api.initialize_connection(context,
                                                                volume,
                                                                address)
        try:
            self.driver.attach_volume(connection_info,
                                      instance_ref['name'],
                                      mountpoint)
        except Exception:  # pylint: disable=W0702
            with utils.save_and_reraise_exception():
                msg = _("instance %(instance_uuid)s: attach failed"
                        " %(mountpoint)s, removing")
                LOG.exception(msg % locals(), context=context)
                self.volume_api.terminate_connection(context,
                                                     volume,
                                                     address)

        self.volume_api.attach(context, volume, instance_id, mountpoint)
        values = {
            'instance_id': instance_id,
            'connection_info': utils.dumps(connection_info),
            'device_name': mountpoint,
            'delete_on_termination': False,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': volume_id,
            'volume_size': None,
            'no_device': None}
        self.db.block_device_mapping_create(context, values)
        return True

    def _detach_volume(self, context, instance, bdm):
        """Do the actual driver detach using block device mapping."""
        instance_name = instance['name']
        instance_uuid = instance['uuid']
        mp = bdm['device_name']
        volume_id = bdm['volume_id']

        LOG.audit(_("Detach volume %(volume_id)s from mountpoint %(mp)s"
                " on instance %(instance_uuid)s") % locals(), context=context)

        if instance_name not in self.driver.list_instances():
            LOG.warn(_("Detaching volume from unknown instance %s"),
                     instance_uuid, context=context)
        self.driver.detach_volume(utils.loads(bdm['connection_info']),
                                  instance_name,
                                  mp)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    @wrap_instance_fault
    def detach_volume(self, context, instance_uuid, volume_id):
        """Detach a volume from an instance."""
        instance_ref = self.db.instance_get_by_uuid(context, instance_uuid)
        instance_id = instance_ref['id']
        bdm = self._get_instance_volume_bdm(context, instance_id, volume_id)
        self._detach_volume(context, instance_ref, bdm)
        volume = self.volume_api.get(context, volume_id)
        self.volume_api.terminate_connection(context, volume, FLAGS.my_ip)
        self.volume_api.detach(context.elevated(), volume)
        self.db.block_device_mapping_destroy_by_instance_and_volume(
            context, instance_id, volume_id)
        return True

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def remove_volume_connection(self, context, instance_id, volume_id):
        """Remove a volume connection using the volume api"""
        # NOTE(vish): We don't want to actually mark the volume
        #             detached, or delete the bdm, just remove the
        #             connection from this host.
        try:
            instance_ref = self.db.instance_get(context, instance_id)
            bdm = self._get_instance_volume_bdm(context,
                                                instance_id,
                                                volume_id)
            self._detach_volume(context, instance_ref, bdm)
            volume = self.volume_api.get(context, volume_id)
            self.volume_api.terminate_connection(context, volume, FLAGS.my_ip)
        except exception.NotFound:
            pass

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def compare_cpu(self, context, cpu_info):
        """Checks that the host cpu is compatible with a cpu given by xml.

        :param context: security context
        :param cpu_info: json string obtained from virConnect.getCapabilities
        :returns: See driver.compare_cpu

        """
        return self.driver.compare_cpu(cpu_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def create_shared_storage_test_file(self, context):
        """Makes tmpfile under FLAGS.instance_path.

        This method enables compute nodes to recognize that they mounts
        same shared storage. (create|check|creanup)_shared_storage_test_file()
        is a pair.

        :param context: security context
        :returns: tmpfile name(basename)

        """
        dirpath = FLAGS.instances_path
        fd, tmp_file = tempfile.mkstemp(dir=dirpath)
        LOG.debug(_("Creating tmpfile %s to notify to other "
                    "compute nodes that they should mount "
                    "the same storage.") % tmp_file)
        os.close(fd)
        return os.path.basename(tmp_file)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def check_shared_storage_test_file(self, context, filename):
        """Confirms existence of the tmpfile under FLAGS.instances_path.
           Cannot confirm tmpfile return False.

        :param context: security context
        :param filename: confirm existence of FLAGS.instances_path/thisfile

        """
        tmp_file = os.path.join(FLAGS.instances_path, filename)
        if not os.path.exists(tmp_file):
            return False
        else:
            return True

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def cleanup_shared_storage_test_file(self, context, filename):
        """Removes existence of the tmpfile under FLAGS.instances_path.

        :param context: security context
        :param filename: remove existence of FLAGS.instances_path/thisfile

        """
        tmp_file = os.path.join(FLAGS.instances_path, filename)
        os.remove(tmp_file)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def update_available_resource(self, context):
        """See comments update_resource_info.

        :param context: security context
        :returns: See driver.update_available_resource()

        """
        return self.driver.update_available_resource(context, self.host)

    def get_instance_disk_info(self, context, instance_name):
        """Getting infomation of instance's current disk.

        Implementation nova.virt.libvirt.connection.

        :param context: security context
        :param instance_name: instance name

        """
        return self.driver.get_instance_disk_info(instance_name)

    def pre_live_migration(self, context, instance_id, time=None,
                           block_migration=False, disk=None):
        """Preparations for live migration at dest host.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param block_migration: if true, prepare for block migration

        """
        if not time:
            time = greenthread

        # Getting instance info
        instance_ref = self.db.instance_get(context, instance_id)

        # If any volume is mounted, prepare here.
        block_device_info = \
            self._get_instance_volume_block_device_info(context, instance_id)
        if not block_device_info['block_device_mapping']:
            LOG.info(_("%s has no volume."), instance_ref['uuid'])

        self.driver.pre_live_migration(block_device_info)

        # Bridge settings.
        # Call this method prior to ensure_filtering_rules_for_instance,
        # since bridge is not set up, ensure_filtering_rules_for instance
        # fails.
        #
        # Retry operation is necessary because continuously request comes,
        # concorrent request occurs to iptables, then it complains.
        network_info = self._get_instance_nw_info(context, instance_ref)

        fixed_ips = [nw_info[1]['ips'] for nw_info in network_info]
        if not fixed_ips:
            raise exception.FixedIpNotFoundForInstance(instance_id=instance_id)

        max_retry = FLAGS.live_migration_retry_count
        for cnt in range(max_retry):
            try:
                self.driver.plug_vifs(instance_ref, network_info)
                break
            except exception.ProcessExecutionError:
                if cnt == max_retry - 1:
                    raise
                else:
                    LOG.warn(_("plug_vifs() failed %(cnt)d."
                               "Retry up to %(max_retry)d for %(hostname)s.")
                               % locals())
                    time.sleep(1)

        # Creating filters to hypervisors and firewalls.
        # An example is that nova-instance-instance-xxx,
        # which is written to libvirt.xml(Check "virsh nwfilter-list")
        # This nwfilter is necessary on the destination host.
        # In addition, this method is creating filtering rule
        # onto destination host.
        self.driver.ensure_filtering_rules_for_instance(instance_ref,
                                                        network_info)

        # Preparation for block migration
        if block_migration:
            self.driver.pre_block_migration(context,
                                            instance_ref,
                                            disk)

    def live_migration(self, context, instance_id,
                       dest, block_migration=False):
        """Executing live migration.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param dest: destination host
        :param block_migration: if true, prepare for block migration

        """
        # Get instance for error handling.
        instance_ref = self.db.instance_get(context, instance_id)

        try:
            # Checking volume node is working correctly when any volumes
            # are attached to instances.
            if self._get_instance_volume_bdms(context, instance_id):
                rpc.call(context,
                          FLAGS.volume_topic,
                          {"method": "check_for_export",
                           "args": {'instance_id': instance_id}})

            if block_migration:
                disk = self.driver.get_instance_disk_info(instance_ref.name)
            else:
                disk = None

            rpc.call(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": "pre_live_migration",
                      "args": {'instance_id': instance_id,
                               'block_migration': block_migration,
                               'disk': disk}})

        except Exception:
            with utils.save_and_reraise_exception():
                instance_uuid = instance_ref['uuid']
                msg = _("Pre live migration for %(instance_uuid)s failed at"
                        " %(dest)s")
                LOG.exception(msg % locals())
                self.rollback_live_migration(context, instance_ref, dest,
                                             block_migration)

        # Executing live migration
        # live_migration might raises exceptions, but
        # nothing must be recovered in this version.
        self.driver.live_migration(context, instance_ref, dest,
                                   self.post_live_migration,
                                   self.rollback_live_migration,
                                   block_migration)

    def post_live_migration(self, ctxt, instance_ref,
                            dest, block_migration=False):
        """Post operations for live migration.

        This method is called from live_migration
        and mainly updating database record.

        :param ctxt: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param dest: destination host
        :param block_migration: if true, prepare for block migration

        """

        LOG.info(_('post_live_migration() is started..'))
        instance_id = instance_ref['id']
        instance_uuid = instance_ref['uuid']

        # Detaching volumes.
        for bdm in self._get_instance_volume_bdms(ctxt, instance_id):
            # NOTE(vish): We don't want to actually mark the volume
            #             detached, or delete the bdm, just remove the
            #             connection from this host.
            self.remove_volume_connection(ctxt, instance_id,
                                          bdm['volume_id'])

        # Releasing vlan.
        # (not necessary in current implementation?)

        network_info = self._get_instance_nw_info(ctxt, instance_ref)
        # Releasing security group ingress rule.
        self.driver.unfilter_instance(instance_ref, network_info)

        # Database updating.
        try:
            # Not return if floating_ip is not found, otherwise,
            # instance never be accessible..
            floating_ip = self.db.instance_get_floating_address(ctxt,
                                                         instance_id)
            if not floating_ip:
                LOG.info(_('No floating_ip is found for %s.'), instance_uuid)
            else:
                floating_ip_ref = self.db.floating_ip_get_by_address(ctxt,
                                                              floating_ip)
                self.db.floating_ip_update(ctxt,
                                           floating_ip_ref['address'],
                                           {'host': dest})
        except exception.NotFound:
            LOG.info(_('No floating_ip is found for %s.'), instance_uuid)
        except Exception, e:
            LOG.error(_("Live migration: Unexpected error: "
                        "%(instance_uuid)s cannot inherit floating "
                        "ip.\n%(e)s") % (locals()))

        # Define domain at destination host, without doing it,
        # pause/suspend/terminate do not work.
        rpc.call(ctxt,
                 self.db.queue_get_for(ctxt, FLAGS.compute_topic, dest),
                     {"method": "post_live_migration_at_destination",
                      "args": {'instance_id': instance_ref['id'],
                               'block_migration': block_migration}})

        # Restore instance state
        current_power_state = self._get_power_state(ctxt, instance_ref)
        self._instance_update(ctxt,
                              instance_ref["id"],
                              host=dest,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

        # Restore volume state
        for volume_ref in instance_ref['volumes']:
            self.volume_api.update(ctxt, volume_ref, {'status': 'in-use'})

        # No instance booting at source host, but instance dir
        # must be deleted for preparing next block migration
        if block_migration:
            self.driver.destroy(instance_ref, network_info)
        else:
            # self.driver.destroy() usually performs  vif unplugging
            # but we must do it explicitly here when block_migration
            # is false, as the network devices at the source must be
            # torn down
            self.driver.unplug_vifs(instance_ref, network_info)

        LOG.info(_('Migrating %(instance_uuid)s to %(dest)s finished'
                   ' successfully.') % locals())
        LOG.info(_("You may see the error \"libvirt: QEMU error: "
                   "Domain not found: no domain with matching name.\" "
                   "This error can be safely ignored."))

    def post_live_migration_at_destination(self, context,
                                instance_id, block_migration=False):
        """Post operations for live migration .

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param block_migration: if true, prepare for block migration

        """
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.info(_('Post operation of migraton started for %s .')
                 % instance_ref['uuid'])
        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.post_live_migration_at_destination(context,
                                                       instance_ref,
                                                       network_info,
                                                       block_migration)

    def rollback_live_migration(self, context, instance_ref,
                                dest, block_migration):
        """Recovers Instance/volume state from migrating -> running.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param dest:
            This method is called from live migration src host.
            This param specifies destination host.
        :param block_migration: if true, prepare for block migration

        """
        host = instance_ref['host']
        self._instance_update(context,
                              instance_ref['id'],
                              host=host,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

        for bdm in self._get_instance_volume_bdms(context, instance_ref['id']):
            volume_id = bdm['volume_id']
            volume = self.volume_api.get(context, volume_id)
            self.volume_api.update(context, volume, {'status': 'in-use'})
            self.volume_api.remove_from_compute(context,
                                                volume,
                                                instance_ref['id'],
                                                dest)

        # Block migration needs empty image at destination host
        # before migration starts, so if any failure occurs,
        # any empty images has to be deleted.
        if block_migration:
            rpc.cast(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": "rollback_live_migration_at_destination",
                      "args": {'instance_id': instance_ref['id']}})

    def rollback_live_migration_at_destination(self, context, instance_id):
        """ Cleaning up image directory that is created pre_live_migration.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        """
        instance_ref = self.db.instance_get(context, instance_id)
        network_info = self._get_instance_nw_info(context, instance_ref)

        # NOTE(vish): The mapping is passed in so the driver can disconnect
        #             from remote volumes if necessary
        block_device_info = \
            self._get_instance_volume_block_device_info(context, instance_id)
        self.driver.destroy(instance_ref, network_info,
                            block_device_info, True)

    @manager.periodic_task
    def _poll_rebooting_instances(self, context):
        if FLAGS.reboot_timeout > 0:
            self.driver.poll_rebooting_instances(FLAGS.reboot_timeout)

    @manager.periodic_task
    def _poll_rescued_instances(self, context):
        if FLAGS.rescue_timeout > 0:
            self.driver.poll_rescued_instances(FLAGS.rescue_timeout)

    @manager.periodic_task
    def _poll_unconfirmed_resizes(self, context):
        if FLAGS.resize_confirm_window > 0:
            self.driver.poll_unconfirmed_resizes(FLAGS.resize_confirm_window)

    @manager.periodic_task
    def _poll_bandwidth_usage(self, context, start_time=None, stop_time=None):
        if not start_time:
            start_time = utils.current_audit_period()[1]

        curr_time = time.time()
        if curr_time - self._last_bw_usage_poll > FLAGS.bandwith_poll_interval:
            self._last_bw_usage_poll = curr_time
            LOG.info(_("Updating bandwidth usage cache"))

            try:
                bw_usage = self.driver.get_all_bw_usage(start_time, stop_time)
            except NotImplementedError:
                # NOTE(mdragon): Not all hypervisors have bandwidth polling
                # implemented yet.  If they don't it doesn't break anything,
                # they just don't get the info in the usage events.
                return

            for usage in bw_usage:
                vif = usage['virtual_interface']
                self.db.bw_usage_update(context,
                                        vif.instance_id,
                                        vif.network.label,
                                        start_time,
                                        usage['bw_in'], usage['bw_out'])

    @manager.periodic_task
    def _report_driver_status(self, context):
        curr_time = time.time()
        if curr_time - self._last_host_check > FLAGS.host_state_interval:
            self._last_host_check = curr_time
            LOG.info(_("Updating host status"))
            # This will grab info about the host and queue it
            # to be sent to the Schedulers.
            self.update_service_capabilities(
                self.driver.get_host_stats(refresh=True))

    @manager.periodic_task
    def _sync_power_states(self, context):
        """Align power states between the database and the hypervisor.

        The hypervisor is authoritative for the power_state data, so we
        simply loop over all known instances for this host and update the
        power_state according to the hypervisor. If the instance is not found
        then it will be set to power_state.NOSTATE, because it doesn't exist
        on the hypervisor.

        """
        vm_instances = self.driver.list_instances_detail()
        vm_instances = dict((vm.name, vm) for vm in vm_instances)
        db_instances = self.db.instance_get_all_by_host(context, self.host)

        num_vm_instances = len(vm_instances)
        num_db_instances = len(db_instances)

        if num_vm_instances != num_db_instances:
            LOG.info(_("Found %(num_db_instances)s in the database and "
                       "%(num_vm_instances)s on the hypervisor.") % locals())

        for db_instance in db_instances:
            name = db_instance["name"]
            db_power_state = db_instance['power_state']
            vm_instance = vm_instances.get(name)

            if vm_instance is None:
                vm_power_state = power_state.NOSTATE
            else:
                vm_power_state = vm_instance.state

            if vm_power_state == db_power_state:
                continue

            if (vm_power_state in (power_state.NOSTATE, power_state.SHUTOFF)
                and db_instance['vm_state'] == vm_states.ACTIVE):
                self._instance_update(context,
                                      db_instance["id"],
                                      power_state=vm_power_state,
                                      vm_state=vm_states.SHUTOFF)
            else:
                self._instance_update(context,
                                      db_instance["id"],
                                      power_state=vm_power_state)

    @manager.periodic_task
    def _reclaim_queued_deletes(self, context):
        """Reclaim instances that are queued for deletion."""
        if FLAGS.reclaim_instance_interval <= 0:
            LOG.debug(_("FLAGS.reclaim_instance_interval <= 0, skipping..."))
            return

        instances = self.db.instance_get_all_by_host(context, self.host)
        for instance in instances:
            old_enough = (not instance.deleted_at or utils.is_older_than(
                    instance.deleted_at,
                    FLAGS.reclaim_instance_interval))
            soft_deleted = instance.vm_state == vm_states.SOFT_DELETE

            if soft_deleted and old_enough:
                instance_uuid = instance['uuid']
                LOG.info(_("Reclaiming deleted instance %(instance_uuid)s"),
                         locals())
                self._delete_instance(context, instance)

    def add_instance_fault_from_exc(self, context, instance_uuid, fault):
        """Adds the specified fault to the database."""
        if hasattr(fault, "code"):
            code = fault.code
        else:
            code = 500

        values = {
            'instance_uuid': instance_uuid,
            'code': code,
            'message': fault.__class__.__name__,
            'details': fault.message,
        }
        self.db.instance_fault_create(context, values)

    @manager.periodic_task(
        ticks_between_runs=FLAGS.running_deleted_instance_poll_interval)
    def _cleanup_running_deleted_instances(self, context):
        """Cleanup any instances which are erroneously still running after
        having been deleted.

        Valid actions to take are:

            1. noop - do nothing
            2. log - log which instances are erroneously running
            3. reap - shutdown and cleanup any erroneously running instances

        The use-case for this cleanup task is: for various reasons, it may be
        possible for the database to show an instance as deleted but for that
        instance to still be running on a host machine (see bug
        https://bugs.launchpad.net/nova/+bug/911366).

        This cleanup task is a cross-hypervisor utility for finding these
        zombied instances and either logging the discrepancy (likely what you
        should do in production), or automatically reaping the instances (more
        appropriate for dev environments).
        """
        action = FLAGS.running_deleted_instance_action

        if action == "noop":
            return

        present_name_labels = set(self.driver.list_instances())

        # NOTE(sirp): admin contexts don't ordinarily return deleted records
        with utils.temporary_mutation(context, read_deleted="yes"):
            instances = self.db.instance_get_all_by_host(context, self.host)
            for instance in instances:
                present = instance.name in present_name_labels
                erroneously_running = instance.deleted and present
                old_enough = (not instance.deleted_at or utils.is_older_than(
                        instance.deleted_at,
                        FLAGS.running_deleted_instance_timeout))

                if erroneously_running and old_enough:
                    instance_id = instance['id']
                    instance_uuid = instance['uuid']
                    name_label = instance['name']

                    if action == "log":
                        LOG.warning(_("Detected instance %(instance_uuid)s"
                                      " with name label '%(name_label)s' which"
                                      " is marked as DELETED but still present"
                                      " on host."), locals())

                    elif action == 'reap':
                        LOG.info(_("Destroying instance %(instance_uuid)s with"
                                   " name label '%(name_label)s' which is"
                                   " marked as DELETED but still present on"
                                   " host."), locals())
                        self._shutdown_instance(
                                context, instance, 'Terminating', True)
                        self._cleanup_volumes(context, instance_id)
                    else:
                        raise Exception(_("Unrecognized value '%(action)s'"
                                          " for FLAGS.running_deleted_"
                                          "instance_action"), locals())
