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

    def init_host(self):
        """Initialization for a standalone compute service."""
        self.driver.init_host(host=self.host)
        context = nova.context.get_admin_context()
        instances = self.db.instance_get_all_by_host(context, self.host)
        for instance in instances:
            inst_name = instance['name']
            db_state = instance['state']
            drv_state = self._update_state(context, instance['id'])

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
                    self.driver.ensure_filtering_rules_for_instance(instance)
                except NotImplementedError:
                    LOG.warning(_('Hypervisor driver does not '
                            'support firewall rules'))

    def _update_state(self, context, instance_id, state=None):
        """Update the state of an instance from the driver info."""
        instance_ref = self.db.instance_get(context, instance_id)

        if state is None:
            try:
                LOG.debug(_('Checking state of %s'), instance_ref['name'])
                info = self.driver.get_info(instance_ref['name'])
            except exception.NotFound:
                info = None

            if info is not None:
                state = info['state']
            else:
                state = power_state.FAILED

        self.db.instance_set_state(context, instance_id, state)
        return state

    def _update_launched_at(self, context, instance_id, launched_at=None):
        """Update the launched_at parameter of the given instance."""
        data = {'launched_at': launched_at or utils.utcnow()}
        self.db.instance_update(context, instance_id, data)

    def _update_image_ref(self, context, instance_id, image_ref):
        """Update the image_id for the given instance."""
        data = {'image_ref': image_ref}
        self.db.instance_update(context, instance_id, data)

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
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'block_device_mapping')

        volume_api = volume.API()
        block_device_mapping = []
        for bdm in self.db.block_device_mapping_get_all_by_instance(
            context, instance_id):
            LOG.debug(_("setting up bdm %s"), bdm)

            if bdm['no_device']:
                continue
            if bdm['virtual_name']:
                # TODO(yamahata):
                # block devices for swap and ephemeralN will be
                # created by virt driver locally in compute node.
                assert (bdm['virtual_name'] == 'swap' or
                        bdm['virtual_name'].startswith('ephemeral'))
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

        return block_device_mapping

    def _run_instance(self, context, instance_id, **kwargs):
        """Launch a new instance with specified options."""
        context = context.elevated()
        instance = self.db.instance_get(context, instance_id)
        if instance['name'] in self.driver.list_instances():
            raise exception.Error(_("Instance has already been created"))
        LOG.audit(_("instance %s: starting..."), instance_id,
                  context=context)
        updates = {}
        updates['host'] = self.host
        updates['launched_on'] = self.host
        # NOTE(vish): used by virt but not in database
        updates['injected_files'] = kwargs.get('injected_files', [])
        updates['admin_pass'] = kwargs.get('admin_password', None)
        instance = self.db.instance_update(context,
                                           instance_id,
                                           updates)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'networking')

        is_vpn = instance['image_ref'] == str(FLAGS.vpn_image_id)
        try:
            # NOTE(vish): This could be a cast because we don't do anything
            #             with the address currently, but I'm leaving it as
            #             a call to ensure that network setup completes.  We
            #             will eventually also need to save the address here.
            if not FLAGS.stub_network:
                network_info = self.network_api.allocate_for_instance(context,
                                                         instance, vpn=is_vpn)
                LOG.debug(_("instance network_info: |%s|"), network_info)
            else:
                # TODO(tr3buchet) not really sure how this should be handled.
                # virt requires network_info to be passed in but stub_network
                # is enabled. Setting to [] for now will cause virt to skip
                # all vif creation and network injection, maybe this is correct
                network_info = []

            bd_mapping = self._setup_block_device_mapping(context, instance_id)

            # TODO(vish) check to make sure the availability zone matches
            self._update_state(context, instance_id, power_state.BUILDING)

            try:
                self.driver.spawn(context, instance, network_info, bd_mapping)
            except Exception as ex:  # pylint: disable=W0702
                msg = _("Instance '%(instance_id)s' failed to spawn. Is "
                        "virtualization enabled in the BIOS? Details: "
                        "%(ex)s") % locals()
                LOG.exception(msg)

            self._update_launched_at(context, instance_id)
            self._update_state(context, instance_id)
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

        if (instance['state'] == power_state.SHUTOFF and
            instance['state_description'] != 'stopped'):
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

        # TODO(ja): should we keep it in a terminated state for a bit?
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
        # instance state will be updated to stopped by _poll_instance_states()

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def rebuild_instance(self, context, instance_id, **kwargs):
        """Destroy and re-make this instance.

        A 'rebuild' effectively purges all existing data from the system and
        remakes the VM with given 'metadata' and 'personalities'.

        :param context: `nova.RequestContext` object
        :param instance_id: Instance identifier (integer)
        :param image_ref: Image identifier (href or integer)
        """
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_("Rebuilding instance %s"), instance_id, context=context)

        self._update_state(context, instance_id, power_state.BUILDING)

        network_info = self._get_instance_nw_info(context, instance_ref)

        self.driver.destroy(instance_ref, network_info)
        image_ref = kwargs.get('image_ref')
        instance_ref.image_ref = image_ref
        instance_ref.injected_files = kwargs.get('injected_files', [])
        network_info = self.network_api.get_instance_nw_info(context,
                                                              instance_ref)
        bd_mapping = self._setup_block_device_mapping(context, instance_id)
        self.driver.spawn(context, instance_ref, network_info, bd_mapping)

        self._update_image_ref(context, instance_id, image_ref)
        self._update_launched_at(context, instance_id)
        self._update_state(context, instance_id)
        usage_info = utils.usage_from_instance(instance_ref,
                                               image_ref=image_ref)
        notifier.notify('compute.%s' % self.host,
                            'compute.instance.rebuild',
                            notifier.INFO,
                            usage_info)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def reboot_instance(self, context, instance_id):
        """Reboot an instance on this host."""
        context = context.elevated()
        self._update_state(context, instance_id)
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_("Rebooting instance %s"), instance_id, context=context)

        if instance_ref['state'] != power_state.RUNNING:
            state = instance_ref['state']
            running = power_state.RUNNING
            LOG.warn(_('trying to reboot a non-running '
                     'instance: %(instance_id)s (state: %(state)s '
                     'expected: %(running)s)') % locals(),
                     context=context)

        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'rebooting')
        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.reboot(instance_ref, network_info)
        self._update_state(context, instance_id)

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
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        #NOTE(sirp): update_state currently only refreshes the state field
        # if we add is_snapshotting, we will need this refreshed too,
        # potentially?
        self._update_state(context, instance_id)

        LOG.audit(_('instance %s: snapshotting'), instance_id,
                  context=context)
        if instance_ref['state'] != power_state.RUNNING:
            state = instance_ref['state']
            running = power_state.RUNNING
            LOG.warn(_('trying to snapshot a non-running '
                       'instance: %(instance_id)s (state: %(state)s '
                       'expected: %(running)s)') % locals())

        self.driver.snapshot(context, instance_ref, image_id)

        if image_type == 'snapshot':
            if rotation:
                raise exception.ImageRotationNotAllowed()
        elif image_type == 'backup':
            if rotation:
                instance_uuid = instance_ref['uuid']
                self.rotate_backups(context, instance_uuid, backup_type,
                                    rotation)
            else:
                raise exception.RotationRequiredForBackup()
        else:
            raise Exception(_('Image type not recognized %s') % image_type)

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
            instance_state = instance_ref["state"]
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
        instance_state = instance_ref['state']
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
        instance_state = instance_ref['state']
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
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_('instance %s: rescuing'), instance_id, context=context)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'rescuing')
        _update_state = lambda result: self._update_state_callback(
                self, context, instance_id, result)
        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.rescue(context, instance_ref, _update_state, network_info)
        self._update_state(context, instance_id)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def unrescue_instance(self, context, instance_id):
        """Rescue an instance on this host."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_('instance %s: unrescuing'), instance_id, context=context)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'unrescuing')
        _update_state = lambda result: self._update_state_callback(
                self, context, instance_id, result)
        network_info = self._get_instance_nw_info(context, instance_ref)
        self.driver.unrescue(instance_ref, _update_state, network_info)
        self._update_state(context, instance_id)

    @staticmethod
    def _update_state_callback(self, context, instance_id, result):
        """Update instance state when async task completes."""
        self._update_state(context, instance_id)

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
                 'args': {'migration_id': migration_ref['id']},
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
        self.db.instance_update(context, instance_ref['uuid'],
           dict(memory_mb=instance_type['memory_mb'],
                vcpus=instance_type['vcpus'],
                local_gb=instance_type['local_gb'],
                instance_type_id=instance_type['id']))

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
            raise exception.Error(_(
                    'Migration error: destination same as source!'))

        old_instance_type = self.db.instance_type_get(context,
                instance_ref['instance_type_id'])
        new_instance_type = self.db.instance_type_get(context,
                instance_type_id)

        migration_ref = self.db.migration_create(context,
                {'instance_uuid': instance_ref['uuid'],
                 'source_compute': instance_ref['host'],
                 'dest_compute': FLAGS.host,
                 'dest_host':   self.driver.get_host_ip_addr(),
                 'old_instance_type_id': old_instance_type['id'],
                 'new_instance_type_id': instance_type_id,
                 'status':      'pre-migrating'})

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
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_('instance %s: pausing'), instance_id, context=context)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'pausing')
        self.driver.pause(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def unpause_instance(self, context, instance_id):
        """Unpause a paused instance on this host."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_('instance %s: unpausing'), instance_id, context=context)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'unpausing')
        self.driver.unpause(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def set_host_enabled(self, context, instance_id=None, host=None,
            enabled=None):
        """Sets the specified host's ability to accept new instances."""
        return self.driver.set_host_enabled(host, enabled)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def get_diagnostics(self, context, instance_id):
        """Retrieve diagnostics for an instance on this host."""
        instance_ref = self.db.instance_get(context, instance_id)
        if instance_ref["state"] == power_state.RUNNING:
            LOG.audit(_("instance %s: retrieving diagnostics"), instance_id,
                      context=context)
            return self.driver.get_diagnostics(instance_ref)

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def suspend_instance(self, context, instance_id):
        """Suspend the given instance."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_('instance %s: suspending'), instance_id, context=context)
        self.db.instance_set_state(context, instance_id,
                                            power_state.NOSTATE,
                                            'suspending')
        self.driver.suspend(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    @checks_instance_lock
    def resume_instance(self, context, instance_id):
        """Resume the given suspended instance."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        LOG.audit(_('instance %s: resuming'), instance_id, context=context)
        self.db.instance_set_state(context, instance_id,
                                            power_state.NOSTATE,
                                            'resuming')
        self.driver.resume(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

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

        :param context: security context
        :param filename: confirm existence of FLAGS.instances_path/thisfile

        """
        tmp_file = os.path.join(FLAGS.instances_path, filename)
        if not os.path.exists(tmp_file):
            raise exception.FileNotFound(file_path=tmp_file)

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

    def pre_live_migration(self, context, instance_id, time=None):
        """Preparations for live migration at dest host.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id

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
        self.driver.ensure_filtering_rules_for_instance(instance_ref)

    def live_migration(self, context, instance_id, dest):
        """Executing live migration.

        :param context: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param dest: destination host

        """
        # Get instance for error handling.
        instance_ref = self.db.instance_get(context, instance_id)
        i_name = instance_ref.name

        try:
            # Checking volume node is working correctly when any volumes
            # are attached to instances.
            if instance_ref['volumes']:
                rpc.call(context,
                          FLAGS.volume_topic,
                          {"method": "check_for_export",
                           "args": {'instance_id': instance_id}})

            # Asking dest host to preparing live migration.
            rpc.call(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": "pre_live_migration",
                      "args": {'instance_id': instance_id}})

        except Exception:
            msg = _("Pre live migration for %(i_name)s failed at %(dest)s")
            LOG.error(msg % locals())
            self.recover_live_migration(context, instance_ref)
            raise

        # Executing live migration
        # live_migration might raises exceptions, but
        # nothing must be recovered in this version.
        self.driver.live_migration(context, instance_ref, dest,
                                   self.post_live_migration,
                                   self.recover_live_migration)

    def post_live_migration(self, ctxt, instance_ref, dest):
        """Post operations for live migration.

        This method is called from live_migration
        and mainly updating database record.

        :param ctxt: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param dest: destination host

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

        # Restore instance/volume state
        self.recover_live_migration(ctxt, instance_ref, dest)

        LOG.info(_('Migrating %(i_name)s to %(dest)s finished successfully.')
                 % locals())
        LOG.info(_("You may see the error \"libvirt: QEMU error: "
                   "Domain not found: no domain with matching name.\" "
                   "This error can be safely ignored."))

    def recover_live_migration(self, ctxt, instance_ref, host=None, dest=None):
        """Recovers Instance/volume state from migrating -> running.

        :param ctxt: security context
        :param instance_id: nova.db.sqlalchemy.models.Instance.Id
        :param host: DB column value is updated by this hostname.
                     If none, the host instance currently running is selected.

        """
        if not host:
            host = instance_ref['host']

        self.db.instance_update(ctxt,
                                instance_ref['id'],
                                {'state_description': 'running',
                                 'state': power_state.RUNNING,
                                 'host': host})

        if dest:
            volume_api = volume.API()
        for volume_ref in instance_ref['volumes']:
            volume_id = volume_ref['id']
            self.db.volume_update(ctxt, volume_id, {'status': 'in-use'})
            if dest:
                volume_api.remove_from_compute(ctxt, volume_id, dest)

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
            self._poll_instance_states(context)
        except Exception as ex:
            LOG.warning(_("Error during instance poll: %s"),
                        unicode(ex))
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

    def _poll_instance_states(self, context):
        vm_instances = self.driver.list_instances_detail()
        vm_instances = dict((vm.name, vm) for vm in vm_instances)

        # Keep a list of VMs not in the DB, cross them off as we find them
        vms_not_found_in_db = list(vm_instances.keys())

        db_instances = self.db.instance_get_all_by_host(context, self.host)

        for db_instance in db_instances:
            name = db_instance['name']
            db_state = db_instance['state']
            vm_instance = vm_instances.get(name)

            if vm_instance is None:
                # NOTE(justinsb): We have to be very careful here, because a
                # concurrent operation could be in progress (e.g. a spawn)
                if db_state == power_state.BUILDING:
                    # TODO(justinsb): This does mean that if we crash during a
                    # spawn, the machine will never leave the spawning state,
                    # but this is just the way nova is; this function isn't
                    # trying to correct that problem.
                    # We could have a separate task to correct this error.
                    # TODO(justinsb): What happens during a live migration?
                    LOG.info(_("Found instance '%(name)s' in DB but no VM. "
                               "State=%(db_state)s, so assuming spawn is in "
                               "progress.") % locals())
                    vm_state = db_state
                else:
                    LOG.info(_("Found instance '%(name)s' in DB but no VM. "
                               "State=%(db_state)s, so setting state to "
                               "shutoff.") % locals())
                    vm_state = power_state.SHUTOFF
                    if db_instance['state_description'] == 'stopping':
                        self.db.instance_stop(context, db_instance['id'])
                        continue
            else:
                vm_state = vm_instance.state
                vms_not_found_in_db.remove(name)

            if (db_instance['state_description'] in ['migrating', 'stopping']):
                # A situation which db record exists, but no instance"
                # sometimes occurs while live-migration at src compute,
                # this case should be ignored.
                LOG.debug(_("Ignoring %(name)s, as it's currently being "
                           "migrated.") % locals())
                continue

            if vm_state != db_state:
                LOG.info(_("DB/VM state mismatch. Changing state from "
                           "'%(db_state)s' to '%(vm_state)s'") % locals())
                self._update_state(context, db_instance['id'], vm_state)

            # NOTE(justinsb): We no longer auto-remove SHUTOFF instances
            # It's quite hard to get them back when we do.

        # Are there VMs not in the DB?
        for vm_not_found_in_db in vms_not_found_in_db:
            name = vm_not_found_in_db

            # We only care about instances that compute *should* know about
            if name.startswith("instance-"):
                # TODO(justinsb): What to do here?  Adopt it?  Shut it down?
                LOG.warning(_("Found VM not in DB: '%(name)s'.  Ignoring")
                            % locals())
