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
:volume_manager:  Name of class that handles persistent storage, loaded by
                  :func:`nova.utils.import_object`

"""

import os
import socket
import sys
import tempfile
import time
import functools

from eventlet import greenthread

import nova.context
from nova import block_device
from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import manager
from nova import network
from nova import rpc
from nova import utils
from nova import volume
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova.notifier import api as notifier
from nova.compute.utils import terminate_volumes
from nova.virt import driver


FLAGS = flags.FLAGS
flags.DEFINE_string('instances_path', '$state_path/instances',
                    'where instances are stored on disk')
flags.DEFINE_string('compute_driver', 'nova.virt.connection.get_connection',
                    'Driver to use for controlling virtualization')
flags.DEFINE_string('stub_network', False,
                    'Stub network related code')
flags.DEFINE_integer('password_length', 12,
                    'Length of generated admin passwords')
flags.DEFINE_string('console_host', socket.gethostname(),
                    'Console proxy host to use to connect to instances on'
                    'this host.')
flags.DEFINE_integer('live_migration_retry_count', 30,
                     "Retry count needed in live_migration."
                     " sleep 1 sec for each count")
flags.DEFINE_integer("rescue_timeout", 0,
                     "Automatically unrescue an instance after N seconds."
                     " Set to 0 to disable.")
flags.DEFINE_integer('host_state_interval', 120,
                     'Interval in seconds for querying the host status')

LOG = logging.getLogger('nova.compute.manager')


def publisher_id(host=None):
    return notifier.publisher_id("compute", host)


def checks_instance_lock(function):
    """Decorator to prevent action against locked instances for non-admins."""
    @functools.wraps(function)
    def decorated_function(self, context, instance_id, *args, **kwargs):
        #TODO(anyone): this being called instance_id is forcing a slightly
        # confusing convention of pushing instance_uuids
        # through an "instance_id" key in the queue args dict when
        # casting through the compute API
        LOG.info(_("check_instance_lock: decorating: |%s|"), function,
                 context=context)
        LOG.info(_("check_instance_lock: arguments: |%(self)s| |%(context)s|"
                " |%(instance_id)s|") % locals(), context=context)
        locked = self.get_lock(context, instance_id)
        admin = context.is_admin
        LOG.info(_("check_instance_lock: locked: |%s|"), locked,
                 context=context)
        LOG.info(_("check_instance_lock: admin: |%s|"), admin,
                 context=context)

        # if admin or unlocked call function otherwise log error
        if admin or not locked:
            LOG.info(_("check_instance_lock: executing: |%s|"), function,
                     context=context)
            function(self, context, instance_id, *args, **kwargs)
        else:
            LOG.error(_("check_instance_lock: not executing |%s|"),
                      function, context=context)
            return False

    return decorated_function


class ComputeManager(manager.SchedulerDependentManager):
    """Manages the running instances from creation to destruction."""

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        # TODO(vish): sync driver creation logic with the rest of the system
        #             and redocument the module docstring
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
        self.network_manager = utils.import_object(FLAGS.network_manager)
        self.volume_manager = utils.import_object(FLAGS.volume_manager)
        self._last_host_check = 0
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
            inst_name = instance['name']
            db_state = instance['power_state']
            drv_state = self._get_power_state(context, instance)

            expect_running = db_state == power_state.RUNNING \
                             and drv_state != db_state

            LOG.debug(_('Current state of %(inst_name)s is %(drv_state)s, '
                        'state in DB is %(db_state)s.'), locals())

            if (expect_running and FLAGS.resume_guests_state_on_host_boot)\
               or FLAGS.start_guests_on_host_boot:
                LOG.info(_('Rebooting instance %(inst_name)s after '
                            'nova-compute restart.'), locals())
                self.reboot_instance(context, instance['id'])
            elif drv_state == power_state.RUNNING:
                # Hyper-V and VMWareAPI drivers will raise and exception
                try:
                    net_info = self._get_instance_nw_info(context, instance)
                    self.driver.ensure_filtering_rules_for_instance(instance,
                                                                    net_info)
                except NotImplementedError:
                    LOG.warning(_('Hypervisor driver does not '
                            'support firewall rules'))

    def _get_power_state(self, context, instance):
        """Retrieve the power state for the given instance."""
        LOG.debug(_('Checking state of %s'), instance['name'])
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

    def _setup_block_device_mapping(self, context, instance_id):
        """setup volumes for block device mapping"""
        volume_api = volume.API()
        block_device_mapping = []
        swap = None
        ephemerals = []
        for bdm in self.db.block_device_mapping_get_all_by_instance(
            context, instance_id):
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
                vol = volume_api.create(context, bdm['volume_size'],
                                        bdm['snapshot_id'], '', '')
                # TODO(yamahata): creating volume simultaneously
                #                 reduces creation time?
                volume_api.wait_creation(context, vol['id'])
                self.db.block_device_mapping_update(
                    context, bdm['id'], {'volume_id': vol['id']})
                bdm['volume_id'] = vol['id']

            if not ((bdm['snapshot_id'] is None) or
                    (bdm['volume_id'] is not None)):
                LOG.error(_('corrupted state of block device mapping '
                            'id: %(id)s '
                            'snapshot: %(snapshot_id) volume: %(vollume_id)') %
                          {'id': bdm['id'],
                           'snapshot_id': bdm['snapshot'],
                           'volume_id': bdm['volume_id']})
                raise exception.ApiError(_('broken block device mapping %d') %
                                         bdm['id'])

            if bdm['volume_id'] is not None:
                volume_api.check_attach(context,
                                        volume_id=bdm['volume_id'])
                dev_path = self._attach_volume_boot(context, instance_id,
                                                    bdm['volume_id'],
                                                    bdm['device_name'])
                block_device_mapping.append({'device_path': dev_path,
                                             'mount_device':
                                             bdm['device_name']})

        return (swap, ephemerals, block_device_mapping)

    def _run_instance(self, context, instance_id, **kwargs):
        """Launch a new instance with specified options."""
        def _check_image_size():
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
            # NOTE(jk0): image_ref is defined in the DB model, image_href is
            # used by the image service. This should be refactored to be
            # consistent.
            image_href = instance['image_ref']
            image_service, image_id = nova.image.get_image_service(context,
                                                                   image_href)
            image_meta = image_service.show(context, image_id)

            try:
                size_bytes = image_meta['size']
            except KeyError:
                # Size is not a required field in the image service (yet), so
                # we are unable to rely on it being there even though it's in
                # glance.

                # TODO(jk0): Should size be required in the image service?
                return

            instance_type_id = instance['instance_type_id']
            instance_type = self.db.instance_type_get(context,
                    instance_type_id)
            allowed_size_gb = instance_type['local_gb']

            # NOTE(jk0): Since libvirt uses local_gb as a secondary drive, we
            # need to handle potential situations where local_gb is 0. This is
            # the default for m1.tiny.
            if allowed_size_gb == 0:
                return

            allowed_size_bytes = allowed_size_gb * 1024 * 1024 * 1024

            LOG.debug(_("image_id=%(image_id)d, image_size_bytes="
                        "%(size_bytes)d, allowed_size_bytes="
                        "%(allowed_size_bytes)d") % locals())

            if size_bytes > allowed_size_bytes:
                LOG.info(_("Image '%(image_id)d' size %(size_bytes)d exceeded"
                           " instance_type allowed size "
                           "%(allowed_size_bytes)d")
                           % locals())
                raise exception.ImageTooLarge()

        def _make_network_info():
            if FLAGS.stub_network:
                # TODO(tr3buchet) not really sure how this should be handled.
                # virt requires network_info to be passed in but stub_network
                # is enabled. Setting to [] for now will cause virt to skip
                # all vif creation and network injection, maybe this is correct
                network_info = []
            else:
                # NOTE(vish): This could be a cast because we don't do
                # anything with the address currently, but I'm leaving it as a
                # call to ensure that network setup completes.  We will
                # eventually also need to save the address here.
                network_info = self.network_api.allocate_for_instance(context,
                                    instance, vpn=is_vpn,
                                    requested_networks=requested_networks)
                LOG.debug(_("instance network_info: |%s|"), network_info)
            return network_info

        def _make_block_device_info():
            (swap, ephemerals,
             block_device_mapping) = self._setup_block_device_mapping(
                context, instance_id)
            block_device_info = {
                'root_device_name': instance['root_device_name'],
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}
            return block_device_info

        def _deallocate_network():
            if not FLAGS.stub_network:
                LOG.debug(_("deallocating network for instance: %s"),
                          instance['id'])
                self.network_api.deallocate_for_instance(context,
                                    instance)

        context = context.elevated()
        instance = self.db.instance_get(context, instance_id)

        requested_networks = kwargs.get('requested_networks', None)

        if instance['name'] in self.driver.list_instances():
            raise exception.Error(_("Instance has already been created"))

        _check_image_size()

        LOG.audit(_("instance %s: starting..."), instance_id,
                  context=context)
        updates = {}
        updates['host'] = self.host
        updates['launched_on'] = self.host
        updates['vm_state'] = vm_states.BUILDING
        updates['task_state'] = task_states.NETWORKING
        instance = self.db.instance_update(context, instance_id, updates)
        instance['injected_files'] = kwargs.get('injected_files', [])
        instance['admin_pass'] = kwargs.get('admin_password', None)

        is_vpn = instance['image_ref'] == str(FLAGS.vpn_image_id)
        network_info = _make_network_info()
        try:
            self._instance_update(context,
                                  instance_id,
                                  vm_state=vm_states.BUILDING,
                                  task_state=task_states.BLOCK_DEVICE_MAPPING)

            block_device_info = _make_block_device_info()

            self._instance_update(context,
                                  instance_id,
                                  vm_state=vm_states.BUILDING,
                                  task_state=task_states.SPAWNING)

            # TODO(vish) check to make sure the availability zone matches
            try:
                self.driver.spawn(context, instance,
                                  network_info, block_device_info)
            except Exception as ex:  # pylint: disable=W0702
                msg = _("Instance '%(instance_id)s' failed to spawn. Is "
                        "virtualization enabled in the BIOS? Details: "
                        "%(ex)s") % locals()
                LOG.exception(msg)
                _deallocate_network()
                return

            current_power_state = self._get_power_state(context, instance)
            self._instance_update(context,
                                  instance_id,
                                  power_state=current_power_state,
                                  vm_state=vm_states.ACTIVE,
                                  task_state=None,
                                  launched_at=utils.utcnow())

            usage_info = utils.usage_from_instance(instance)
            notifier.notify('compute.%s' % self.host,
                            'compute.instance.create',
                            notifier.INFO, usage_info)

        except exception.InstanceNotFound:
            # FIXME(wwolf): We are just ignoring InstanceNotFound
            # exceptions here in case the instance was immediately
            # deleted before it actually got created.  This should
            # be fixed once we have no-db-messaging
            pass
        except:
            with utils.save_and_reraise_exception():
                _deallocate_network()

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def run_instance(self, context, instance_id, **kwargs):
        self._run_instance(context, instance_id, **kwargs)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def start_instance(self, context, instance_id):
        """Starting an instance on this host."""
        # TODO(yamahata): injected_files isn't supported.
        #                 Anyway OSAPI doesn't support stop/start yet
        self._run_instance(context, instance_id)

    def _shutdown_instance(self, context, instance_id, action_str):
        """Shutdown an instance on this host."""
        context = context.elevated()
        instance = self.db.instance_get(context, instance_id)
        LOG.audit(_("%(action_str)s instance %(instance_id)s") %
                  {'action_str': action_str, 'instance_id': instance_id},
                  context=context)

        network_info = self._get_instance_nw_info(context, instance)
        if not FLAGS.stub_network:
            self.network_api.deallocate_for_instance(context, instance)

        volumes = instance.get('volumes') or []
        for volume in volumes:
            self._detach_volume(context, instance_id, volume['id'], False)

        if instance['power_state'] == power_state.SHUTOFF:
            self.db.instance_destroy(context, instance_id)
            raise exception.Error(_('trying to destroy already destroyed'
                                    ' instance: %s') % instance_id)
        self.driver.destroy(instance, network_info)

        if action_str == 'Terminating':
            terminate_volumes(self.db, context, instance_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def terminate_instance(self, context, instance_id):
        """Terminate an instance on this host."""
        self._shutdown_instance(context, instance_id, 'Terminating')
        instance = self.db.instance_get(context.elevated(), instance_id)
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
    def stop_instance(self, context, instance_id):
        """Stopping an instance on this host."""
        self._shutdown_instance(context, instance_id, 'Stopping')
        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.STOPPED,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def rebuild_instance(self, context, instance_id, **kwargs):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        :param context: `nova.RequestContext` object
        :param instance_id: Instance identifier (integer)
        :param injected_files: Files to inject
        :param new_pass: password to set on rebuilt instance
        """
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_("Rebuilding instance %s"), instance_id, context=context)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.REBUILDING,
                              task_state=None)

        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.destroy(instance_ref, network_info)

        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.REBUILDING,
                              task_state=task_states.BLOCK_DEVICE_MAPPING)

        instance_ref.injected_files = kwargs.get('injected_files', [])
        network_info = self.network_api.get_instance_nw_info(context,
                                                              instance_ref)
        bd_mapping = self._setup_block_device_mapping(context, instance_id)

        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.REBUILDING,
                              task_state=task_states.SPAWNING)

        # pull in new password here since the original password isn't in the db
        instance_ref.admin_pass = kwargs.get('new_pass',
                utils.generate_password(FLAGS.password_length))

        self.driver.spawn(context, instance_ref, network_info, bd_mapping)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None,
                              launched_at=utils.utcnow())

        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.rebuild',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def reboot_instance(self, context, instance_id):
        """Reboot an instance on this host."""
        LOG.audit(_("Rebooting instance %s"), instance_id, context=context)
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=task_states.REBOOTING)

        if instance_ref['power_state'] != power_state.RUNNING:
            state = instance_ref['power_state']
            running = power_state.RUNNING
            LOG.warn(_('trying to reboot a non-running '
                     'instance: %(instance_id)s (state: %(state)s '
                     'expected: %(running)s)') % locals(),
                     context=context)

        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.reboot(instance_ref, network_info)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def snapshot_instance(self, context, instance_id, image_id,
                          image_type='snapshot', backup_type=None,
                          rotation=None):
        """Snapshot an instance on this host.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
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
        instance_ref = self.db.instance_get(context, instance_id)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=task_state)

        LOG.audit(_('instance %s: snapshotting'), instance_id,
                  context=context)

        if instance_ref['power_state'] != power_state.RUNNING:
            state = instance_ref['power_state']
            running = power_state.RUNNING
            LOG.warn(_('trying to snapshot a non-running '
                       'instance: %(instance_id)s (state: %(state)s '
                       'expected: %(running)s)') % locals())

        self.driver.snapshot(context, instance_ref, image_id)
        self._instance_update(context, instance_id, task_state=None)

        if image_type == 'snapshot' and rotation:
            raise exception.ImageRotationNotAllowed()

        elif image_type == 'backup' and rotation:
            instance_uuid = instance_ref['uuid']
            self.rotate_backups(context, instance_uuid, backup_type, rotation)

        elif image_type == 'backup':
            raise exception.RotationRequiredForBackup()

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
                LOG.debug(_("Deleting image %d" % image_id))
                image_service.delete(context, image_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def set_admin_password(self, context, instance_id, new_pass=None):
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
            instance_ref = self.db.instance_get(context, instance_id)
            instance_id = instance_ref["id"]
            instance_state = instance_ref["power_state"]
            expected_state = power_state.RUNNING

            if instance_state != expected_state:
                raise exception.Error(_('Instance is not running'))
            else:
                try:
                    self.driver.set_admin_password(instance_ref, new_pass)
                    LOG.audit(_("Instance %s: Root password set"),
                                instance_ref["name"])
                    break
                except NotImplementedError:
                    # NOTE(dprince): if the driver doesn't implement
                    # set_admin_password we break to avoid a loop
                    LOG.warn(_('set_admin_password is not implemented '
                            'by this driver.'))
                    break
                except Exception, e:
                    # Catch all here because this could be anything.
                    LOG.exception(e)
                    if i == max_tries - 1:
                        # At some point this exception may make it back
                        # to the API caller, and we don't want to reveal
                        # too much.  The real exception is logged above
                        raise exception.Error(_('Internal error'))
                    time.sleep(1)
                    continue

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def inject_file(self, context, instance_id, path, file_contents):
        """Write a file to the specified path in an instance on this host."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        instance_id = instance_ref['id']
        instance_state = instance_ref['power_state']
        expected_state = power_state.RUNNING
        if instance_state != expected_state:
            LOG.warn(_('trying to inject a file into a non-running '
                    'instance: %(instance_id)s (state: %(instance_state)s '
                    'expected: %(expected_state)s)') % locals())
        nm = instance_ref['name']
        msg = _('instance %(nm)s: injecting file to %(path)s') % locals()
        LOG.audit(msg)
        self.driver.inject_file(instance_ref, path, file_contents)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def agent_update(self, context, instance_id, url, md5hash):
        """Update agent running on an instance on this host."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        instance_id = instance_ref['id']
        instance_state = instance_ref['power_state']
        expected_state = power_state.RUNNING
        if instance_state != expected_state:
            LOG.warn(_('trying to update agent on a non-running '
                    'instance: %(instance_id)s (state: %(instance_state)s '
                    'expected: %(expected_state)s)') % locals())
        nm = instance_ref['name']
        msg = _('instance %(nm)s: updating agent to %(url)s') % locals()
        LOG.audit(msg)
        self.driver.agent_update(instance_ref, url, md5hash)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def rescue_instance(self, context, instance_id):
        """Rescue an instance on this host."""
        LOG.audit(_('instance %s: rescuing'), instance_id, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        network_info = self._get_instance_nw_info(context, instance_ref)

        # NOTE(blamar): None of the virt drivers use the 'callback' param
        self.driver.rescue(context, instance_ref, None, network_info)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.RESCUED,
                              task_state=None,
                              power_state=current_power_state)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def unrescue_instance(self, context, instance_id):
        """Rescue an instance on this host."""
        LOG.audit(_('instance %s: unrescuing'), instance_id, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        network_info = self._get_instance_nw_info(context, instance_ref)

        # NOTE(blamar): None of the virt drivers use the 'callback' param
        self.driver.unrescue(instance_ref, None, network_info)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.ACTIVE,
                              task_state=None,
                              power_state=current_power_state)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def confirm_resize(self, context, instance_id, migration_id):
        """Destroys the source instance."""
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)

        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.destroy(instance_ref, network_info)
        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.resize.confirm',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def revert_resize(self, context, instance_id, migration_id):
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
                instance_ref['host'])
        rpc.cast(context, topic,
                {'method': 'finish_revert_resize',
                 'args': {'instance_id': instance_ref['uuid'],
                          'migration_id': migration_ref['id']},
                })

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def finish_revert_resize(self, context, instance_id, migration_id):
        """Finishes the second half of reverting a resize.

        Power back on the source instance and revert the resized attributes
        in the database.

        """
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)

        instance_type = self.db.instance_type_get(context,
                migration_ref['old_instance_type_id'])

        # Just roll back the record. There's no need to resize down since
        # the 'old' VM already has the preferred attributes
        self._instance_update(context,
                              instance_ref["uuid"],
                              memory_mb=instance_type['memory_mb'],
                              vcpus=instance_type['vcpus'],
                              local_gb=instance_type['local_gb'],
                              instance_type_id=instance_type['id'])

        self.driver.revert_migration(instance_ref)
        self.db.migration_update(context, migration_id,
                {'status': 'reverted'})
        usage_info = utils.usage_from_instance(instance_ref)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.resize.revert',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def prep_resize(self, context, instance_id, instance_type_id):
        """Initiates the process of moving a running instance to another host.

        Possibly changes the RAM and disk size in the process.

        """
        context = context.elevated()

        # Because of checks_instance_lock, this must currently be called
        # instance_id. However, the compute API is always passing the UUID
        # of the instance down
        instance_ref = self.db.instance_get_by_uuid(context, instance_id)

        if instance_ref['host'] == FLAGS.host:
            self._instance_update(context,
                                  instance_id,
                                  vm_state=vm_states.ERROR)
            msg = _('Migration error: destination same as source!')
            raise exception.Error(msg)

        old_instance_type = self.db.instance_type_get(context,
                instance_ref['instance_type_id'])
        new_instance_type = self.db.instance_type_get(context,
                instance_type_id)

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
                 'args': {'instance_id': instance_ref['uuid'],
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
    def resize_instance(self, context, instance_id, migration_id):
        """Starts the migration of a running instance to another host."""
        migration_ref = self.db.migration_get(context, migration_id)
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)

        self.db.migration_update(context,
                                 migration_id,
                                 {'status': 'migrating'})

        disk_info = self.driver.migrate_disk_and_power_off(
                instance_ref, migration_ref['dest_host'])
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
                  'instance_id': instance_ref['uuid']}
        rpc.cast(context, topic, {'method': 'finish_resize',
                                  'args': params})

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def finish_resize(self, context, instance_id, migration_id, disk_info):
        """Completes the migration process.

        Sets up the newly transferred disk and turns on the instance at its
        new host machine.

        """
        migration_ref = self.db.migration_get(context, migration_id)

        resize_instance = False
        instance_ref = self.db.instance_get_by_uuid(context,
                migration_ref.instance_uuid)
        if migration_ref['old_instance_type_id'] != \
           migration_ref['new_instance_type_id']:
            instance_type = self.db.instance_type_get(context,
                    migration_ref['new_instance_type_id'])
            self.db.instance_update(context, instance_ref.uuid,
                   dict(instance_type_id=instance_type['id'],
                        memory_mb=instance_type['memory_mb'],
                        vcpus=instance_type['vcpus'],
                        local_gb=instance_type['local_gb']))
            resize_instance = True

        instance_ref = self.db.instance_get_by_uuid(context,
                                            instance_ref.uuid)

        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.finish_migration(context, instance_ref, disk_info,
                                     network_info, resize_instance)

        self._instance_update(context,
                              instance_id,
                              vm_state=vm_states.ACTIVE,
                              task_state=task_states.RESIZE_VERIFY)

        self.db.migration_update(context, migration_id,
                {'status': 'finished', })

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def add_fixed_ip_to_instance(self, context, instance_id, network_id):
        """Calls network_api to add new fixed_ip to instance
        then injects the new network info and resets instance networking.

        """
        self.network_api.add_fixed_ip_to_instance(context, instance_id,
                                                  self.host, network_id)
        self.inject_network_info(context, instance_id)
        self.reset_network(context, instance_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def remove_fixed_ip_from_instance(self, context, instance_id, address):
        """Calls network_api to remove existing fixed_ip from instance
        by injecting the altered network info and resetting
        instance networking.
        """
        self.network_api.remove_fixed_ip_from_instance(context, instance_id,
                                                       address)
        self.inject_network_info(context, instance_id)
        self.reset_network(context, instance_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def pause_instance(self, context, instance_id):
        """Pause an instance on this host."""
        LOG.audit(_('instance %s: pausing'), instance_id, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        self.driver.pause(instance_ref, lambda result: None)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.PAUSED,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def unpause_instance(self, context, instance_id):
        """Unpause a paused instance on this host."""
        LOG.audit(_('instance %s: unpausing'), instance_id, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        self.driver.unpause(instance_ref, lambda result: None)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
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
    def get_diagnostics(self, context, instance_id):
        """Retrieve diagnostics for an instance on this host."""
        instance_ref = self.db.instance_get(context, instance_id)
        if instance_ref["power_state"] == power_state.RUNNING:
            LOG.audit(_("instance %s: retrieving diagnostics"), instance_id,
                      context=context)
            return self.driver.get_diagnostics(instance_ref)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def suspend_instance(self, context, instance_id):
        """Suspend the given instance."""
        LOG.audit(_('instance %s: suspending'), instance_id, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        self.driver.suspend(instance_ref, lambda result: None)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.SUSPENDED,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def resume_instance(self, context, instance_id):
        """Resume the given suspended instance."""
        LOG.audit(_('instance %s: resuming'), instance_id, context=context)
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        self.driver.resume(instance_ref, lambda result: None)

        current_power_state = self._get_power_state(context, instance_ref)
        self._instance_update(context,
                              instance_id,
                              power_state=current_power_state,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def lock_instance(self, context, instance_id):
        """Lock the given instance."""
        context = context.elevated()

        LOG.debug(_('instance %s: locking'), instance_id, context=context)
        self.db.instance_update(context, instance_id, {'locked': True})

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def unlock_instance(self, context, instance_id):
        """Unlock the given instance."""
        context = context.elevated()

        LOG.debug(_('instance %s: unlocking'), instance_id, context=context)
        self.db.instance_update(context, instance_id, {'locked': False})

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def get_lock(self, context, instance_id):
        """Return the boolean state of the given instance's lock."""
        context = context.elevated()
        LOG.debug(_('instance %s: getting locked state'), instance_id,
                  context=context)
        if utils.is_uuid_like(instance_id):
            uuid = instance_id
            instance_ref = self.db.instance_get_by_uuid(context, uuid)
        else:
            instance_ref = self.db.instance_get(context, instance_id)
        return instance_ref['locked']

    @checks_instance_lock
    def reset_network(self, context, instance_id):
        """Reset networking on the given instance."""
        instance = self.db.instance_get(context, instance_id)
        LOG.debug(_('instance %s: reset network'), instance_id,
                                                   context=context)
        self.driver.reset_network(instance)

    @checks_instance_lock
    def inject_network_info(self, context, instance_id):
        """Inject network info for the given instance."""
        LOG.debug(_('instance %s: inject network info'), instance_id,
                                                         context=context)
        instance = self.db.instance_get(context, instance_id)
        network_info = self._get_instance_nw_info(context, instance)
        LOG.debug(_("network_info to inject: |%s|"), network_info)

        self.driver.inject_network_info(instance, network_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def get_console_output(self, context, instance_id):
        """Send the console output for the given instance."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_("Get console output for instance %s"), instance_id,
                  context=context)
        output = self.driver.get_console_output(instance_ref)
        return output.decode('utf-8', 'replace').encode('ascii', 'replace')

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def get_ajax_console(self, context, instance_id):
        """Return connection information for an ajax console."""
        context = context.elevated()
        LOG.debug(_("instance %s: getting ajax console"), instance_id)
        instance_ref = self.db.instance_get(context, instance_id)
        return self.driver.get_ajax_console(instance_ref)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def get_vnc_console(self, context, instance_id):
        """Return connection information for a vnc console."""
        context = context.elevated()
        LOG.debug(_("instance %s: getting vnc console"), instance_id)
        instance_ref = self.db.instance_get(context, instance_id)
        return self.driver.get_vnc_console(instance_ref)

    def _attach_volume_boot(self, context, instance_id, volume_id, mountpoint):
        """Attach a volume to an instance at boot time. So actual attach
        is done by instance creation"""

        # TODO(yamahata):
        # should move check_attach to volume manager?
        volume.API().check_attach(context, volume_id)

        context = context.elevated()
        LOG.audit(_("instance %(instance_id)s: booting with "
                    "volume %(volume_id)s at %(mountpoint)s") %
                  locals(), context=context)
        dev_path = self.volume_manager.setup_compute_volume(context, volume_id)
        self.db.volume_attached(context, volume_id, instance_id, mountpoint)
        return dev_path

    @checks_instance_lock
    def attach_volume(self, context, instance_id, volume_id, mountpoint):
        """Attach a volume to an instance."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_("instance %(instance_id)s: attaching volume %(volume_id)s"
                " to %(mountpoint)s") % locals(), context=context)
        dev_path = self.volume_manager.setup_compute_volume(context,
                                                            volume_id)
        try:
            self.driver.attach_volume(instance_ref['name'],
                                      dev_path,
                                      mountpoint)
            self.db.volume_attached(context,
                                    volume_id,
                                    instance_id,
                                    mountpoint)
            values = {
                'instance_id': instance_id,
                'device_name': mountpoint,
                'delete_on_termination': False,
                'virtual_name': None,
                'snapshot_id': None,
                'volume_id': volume_id,
                'volume_size': None,
                'no_device': None}
            self.db.block_device_mapping_create(context, values)
        except Exception as exc:  # pylint: disable=W0702
            # NOTE(vish): The inline callback eats the exception info so we
            #             log the traceback here and reraise the same
            #             ecxception below.
            LOG.exception(_("instance %(instance_id)s: attach failed"
                    " %(mountpoint)s, removing") % locals(), context=context)
            self.volume_manager.remove_compute_volume(context,
                                                      volume_id)
            raise exc

        return True

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def _detach_volume(self, context, instance_id, volume_id, destroy_bdm):
        """Detach a volume from an instance."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        volume_ref = self.db.volume_get(context, volume_id)
        mp = volume_ref['mountpoint']
        LOG.audit(_("Detach volume %(volume_id)s from mountpoint %(mp)s"
                " on instance %(instance_id)s") % locals(), context=context)
        if instance_ref['name'] not in self.driver.list_instances():
            LOG.warn(_("Detaching volume from unknown instance %s"),
                     instance_id, context=context)
        else:
            self.driver.detach_volume(instance_ref['name'],
                                      volume_ref['mountpoint'])
        self.volume_manager.remove_compute_volume(context, volume_id)
        self.db.volume_detached(context, volume_id)
        if destroy_bdm:
            self.db.block_device_mapping_destroy_by_instance_and_volume(
                context, instance_id, volume_id)
        return True

    def detach_volume(self, context, instance_id, volume_id):
        """Detach a volume from an instance."""
        return self._detach_volume(context, instance_id, volume_id, True)

    def remove_volume(self, context, volume_id):
        """Remove volume on compute host.

        :param context: security context
        :param volume_id: volume ID
        """
        self.volume_manager.remove_compute_volume(context, volume_id)

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
        hostname = instance_ref['hostname']

        # Getting fixed ips
        fixed_ips = self.db.instance_get_fixed_addresses(context, instance_id)
        if not fixed_ips:
            raise exception.FixedIpNotFoundForInstance(instance_id=instance_id)

        # If any volume is mounted, prepare here.
        if not instance_ref['volumes']:
            LOG.info(_("%s has no volume."), hostname)
        else:
            for v in instance_ref['volumes']:
                self.volume_manager.setup_compute_volume(context, v['id'])

        # Bridge settings.
        # Call this method prior to ensure_filtering_rules_for_instance,
        # since bridge is not set up, ensure_filtering_rules_for instance
        # fails.
        #
        # Retry operation is necessary because continuously request comes,
        # concorrent request occurs to iptables, then it complains.
        network_info = self._get_instance_nw_info(context, instance_ref)
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
        :param block_migration: if true, do block migration

        """
        # Get instance for error handling.
        instance_ref = self.db.instance_get(context, instance_id)

        try:
            # Checking volume node is working correctly when any volumes
            # are attached to instances.
            if instance_ref['volumes']:
                rpc.call(context,
                          FLAGS.volume_topic,
                          {"method": "check_for_export",
                           "args": {'instance_id': instance_id}})

            if block_migration:
                disk = self.driver.get_instance_disk_info(context,
                                                          instance_ref)
            else:
                disk = None

            rpc.call(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": "pre_live_migration",
                      "args": {'instance_id': instance_id,
                               'block_migration': block_migration,
                               'disk': disk}})

        except Exception:
            i_name = instance_ref.name
            msg = _("Pre live migration for %(i_name)s failed at %(dest)s")
            LOG.error(msg % locals())
            self.rollback_live_migration(context, instance_ref,
                                         dest, block_migration)
            raise

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
        :param block_migration: if true, do block migration

        """

        LOG.info(_('post_live_migration() is started..'))
        instance_id = instance_ref['id']

        # Detaching volumes.
        try:
            for vol in self.db.volume_get_all_by_instance(ctxt, instance_id):
                self.volume_manager.remove_compute_volume(ctxt, vol['id'])
        except exception.NotFound:
            pass

        # Releasing vlan.
        # (not necessary in current implementation?)

        network_info = self._get_instance_nw_info(ctxt, instance_ref)
        # Releasing security group ingress rule.
        self.driver.unfilter_instance(instance_ref, network_info)

        # Database updating.
        i_name = instance_ref.name
        try:
            # Not return if floating_ip is not found, otherwise,
            # instance never be accessible..
            floating_ip = self.db.instance_get_floating_address(ctxt,
                                                         instance_id)
            if not floating_ip:
                LOG.info(_('No floating_ip is found for %s.'), i_name)
            else:
                floating_ip_ref = self.db.floating_ip_get_by_address(ctxt,
                                                              floating_ip)
                self.db.floating_ip_update(ctxt,
                                           floating_ip_ref['address'],
                                           {'host': dest})
        except exception.NotFound:
            LOG.info(_('No floating_ip is found for %s.'), i_name)
        except Exception, e:
            LOG.error(_("Live migration: Unexpected error: "
                        "%(i_name)s cannot inherit floating "
                        "ip.\n%(e)s") % (locals()))

        # Define domain at destination host, without doing it,
        # pause/suspend/terminate do not work.
        rpc.call(ctxt,
                 self.db.queue_get_for(ctxt, FLAGS.compute_topic, dest),
                     {"method": "post_live_migration_at_destination",
                      "args": {'instance_id': instance_ref.id,
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
            volume_id = volume_ref['id']
            self.db.volume_update(ctxt, volume_id, {'status': 'in-use'})

        # No instance booting at source host, but instance dir
        # must be deleted for preparing next block migration
        if block_migration:
            self.driver.destroy(instance_ref, network_info)

        LOG.info(_('Migrating %(i_name)s to %(dest)s finished successfully.')
                 % locals())
        LOG.info(_("You may see the error \"libvirt: QEMU error: "
                   "Domain not found: no domain with matching name.\" "
                   "This error can be safely ignored."))

    def post_live_migration_at_destination(self, context,
                                instance_id, block_migration=False):
        """Post operations for live migration .

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param block_migration: block_migration

        """
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.info(_('Post operation of migraton started for %s .')
                 % instance_ref.name)
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
        """
        host = instance_ref['host']
        self._instance_update(context,
                              instance_ref['id'],
                              host=host,
                              vm_state=vm_states.ACTIVE,
                              task_state=None)

        for volume_ref in instance_ref['volumes']:
            volume_id = volume_ref['id']
            self.db.volume_update(context, volume_id, {'status': 'in-use'})
            volume.API().remove_from_compute(context, volume_id, dest)

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
        instances_ref = self.db.instance_get(context, instance_id)
        network_info = self._get_instance_nw_info(context, instances_ref)
        self.driver.destroy(instances_ref, network_info)

    def periodic_tasks(self, context=None):
        """Tasks to be run at a periodic interval."""
        error_list = super(ComputeManager, self).periodic_tasks(context)
        if error_list is None:
            error_list = []

        try:
            if FLAGS.rescue_timeout > 0:
                self.driver.poll_rescued_instances(FLAGS.rescue_timeout)
        except Exception as ex:
            LOG.warning(_("Error during poll_rescued_instances: %s"),
                        unicode(ex))
            error_list.append(ex)

        try:
            self._report_driver_status()
        except Exception as ex:
            LOG.warning(_("Error during report_driver_status(): %s"),
                        unicode(ex))
            error_list.append(ex)

        try:
            self._sync_power_states(context)
        except Exception as ex:
            LOG.warning(_("Error during power_state sync: %s"), unicode(ex))
            error_list.append(ex)

        return error_list

    def _report_driver_status(self):
        curr_time = time.time()
        if curr_time - self._last_host_check > FLAGS.host_state_interval:
            self._last_host_check = curr_time
            LOG.info(_("Updating host status"))
            # This will grab info about the host and queue it
            # to be sent to the Schedulers.
            self.update_service_capabilities(
                self.driver.get_host_stats(refresh=True))

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

            self._instance_update(context,
                                  db_instance["id"],
                                  power_state=vm_power_state)
