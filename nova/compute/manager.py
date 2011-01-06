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
Handles all processes relating to instances (guest vms).

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

import datetime
import logging
import random
import string

from nova import exception
from nova import flags
from nova import manager
from nova import rpc
from nova import utils
from nova.compute import power_state

FLAGS = flags.FLAGS
flags.DEFINE_string('instances_path', '$state_path/instances',
                    'where instances are stored on disk')
flags.DEFINE_string('compute_driver', 'nova.virt.connection.get_connection',
                    'Driver to use for controlling virtualization')
flags.DEFINE_string('stub_network', False,
                    'Stub network related code')
flags.DEFINE_integer('password_length', 12,
                    'Length of generated admin passwords')


class ComputeManager(manager.Manager):

    """Manages the running instances from creation to destruction."""

    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        # TODO(vish): sync driver creation logic with the rest of the system
        #             and redocument the module docstring
        if not compute_driver:
            compute_driver = FLAGS.compute_driver
        self.driver = utils.import_object(compute_driver)
        self.network_manager = utils.import_object(FLAGS.network_manager)
        self.volume_manager = utils.import_object(FLAGS.volume_manager)
        super(ComputeManager, self).__init__(*args, **kwargs)

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service.
        """
        self.driver.init_host()

    def _update_state(self, context, instance_id):
        """Update the state of an instance from the driver info."""
        # FIXME(ja): include other fields from state?
        instance_ref = self.db.instance_get(context, instance_id)
        try:
            #info = self.driver.get_info(instance_ref['name'])
            info = self.driver.get_info(instance_ref)
            state = info['state']
        except exception.NotFound:
            state = power_state.NOSTATE
        self.db.instance_set_state(context, instance_id, state)

    def get_network_topic(self, context, **_kwargs):
        """Retrieves the network host for a project on this host"""
        # TODO(vish): This method should be memoized. This will make
        #             the call to get_network_host cheaper, so that
        #             it can pas messages instead of checking the db
        #             locally.
        if FLAGS.stub_network:
            host = FLAGS.network_host
        else:
            host = self.network_manager.get_network_host(context)
        return self.db.queue_get_for(context,
                                     FLAGS.network_topic,
                                     host)

    @exception.wrap_exception
    def refresh_security_group(self, context, security_group_id, **_kwargs):
        """This call passes stright through to the virtualization driver."""
        self.driver.refresh_security_group(security_group_id)

    @exception.wrap_exception
    def run_instance(self, context, instance_id, **_kwargs):
        """Launch a new instance with specified options."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        if instance_ref['name'] in self.driver.list_instances():
            raise exception.Error(_("Instance has already been created"))
        logging.debug(_("instance %s: starting..."), instance_id)
        self.db.instance_update(context,
                                instance_id,
                                {'host': self.host})

        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'networking')

        is_vpn = instance_ref['image_id'] == FLAGS.vpn_image_id
        # NOTE(vish): This could be a cast because we don't do anything
        #             with the address currently, but I'm leaving it as
        #             a call to ensure that network setup completes.  We
        #             will eventually also need to save the address here.
        if not FLAGS.stub_network:
            address = rpc.call(context,
                               self.get_network_topic(context),
                               {"method": "allocate_fixed_ip",
                                "args": {"instance_id": instance_id,
                                         "vpn": is_vpn}})

            self.network_manager.setup_compute_network(context,
                                                       instance_id)

        # TODO(vish) check to make sure the availability zone matches
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'spawning')

        try:
            self.driver.spawn(instance_ref)
            now = datetime.datetime.utcnow()
            self.db.instance_update(context,
                                    instance_id,
                                    {'launched_at': now})
        except Exception:  # pylint: disable-msg=W0702
            logging.exception(_("instance %s: Failed to spawn"),
                              instance_ref['name'])
            self.db.instance_set_state(context,
                                       instance_id,
                                       power_state.SHUTDOWN)

        self._update_state(context, instance_id)

    @exception.wrap_exception
    def terminate_instance(self, context, instance_id):
        """Terminate an instance on this machine."""
        context = context.elevated()

        instance_ref = self.db.instance_get(context, instance_id)

        if not FLAGS.stub_network:
            address = self.db.instance_get_floating_address(context,
                                                            instance_ref['id'])
            if address:
                logging.debug(_("Disassociating address %s") % address)
                # NOTE(vish): Right now we don't really care if the ip is
                #             disassociated.  We may need to worry about
                #             checking this later.
                rpc.cast(context,
                         self.get_network_topic(context),
                         {"method": "disassociate_floating_ip",
                          "args": {"floating_address": address}})

            address = self.db.instance_get_fixed_address(context,
                                                         instance_ref['id'])
            if address:
                logging.debug(_("Deallocating address %s") % address)
                # NOTE(vish): Currently, nothing needs to be done on the
                #             network node until release. If this changes,
                #             we will need to cast here.
                self.network_manager.deallocate_fixed_ip(context.elevated(),
                                                         address)

        logging.debug(_("instance %s: terminating"), instance_id)

        volumes = instance_ref.get('volumes', []) or []
        for volume in volumes:
            self.detach_volume(context, instance_id, volume['id'])
        if instance_ref['state'] == power_state.SHUTOFF:
            self.db.instance_destroy(context, instance_id)
            raise exception.Error(_('trying to destroy already destroyed'
                                    ' instance: %s') % instance_id)
        self.driver.destroy(instance_ref)

        # TODO(ja): should we keep it in a terminated state for a bit?
        self.db.instance_destroy(context, instance_id)

    @exception.wrap_exception
    def reboot_instance(self, context, instance_id):
        """Reboot an instance on this server."""
        context = context.elevated()
        self._update_state(context, instance_id)
        instance_ref = self.db.instance_get(context, instance_id)

        if instance_ref['state'] != power_state.RUNNING:
            logging.warn(_('trying to reboot a non-running '
                           'instance: %s (state: %s excepted: %s)'),
                         instance_id,
                         instance_ref['state'],
                         power_state.RUNNING)

        logging.debug(_('instance %s: rebooting'), instance_ref['name'])
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'rebooting')
        self.network_manager.setup_compute_network(context, instance_id)
        self.driver.reboot(instance_ref)
        self._update_state(context, instance_id)

    @exception.wrap_exception
    def snapshot_instance(self, context, instance_id, name):
        """Snapshot an instance on this server."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        #NOTE(sirp): update_state currently only refreshes the state field
        # if we add is_snapshotting, we will need this refreshed too,
        # potentially?
        self._update_state(context, instance_id)

        logging.debug(_('instance %s: snapshotting'), instance_ref['name'])
        if instance_ref['state'] != power_state.RUNNING:
            logging.warn(_('trying to snapshot a non-running '
                           'instance: %s (state: %s excepted: %s)'),
                         instance_id,
                         instance_ref['state'],
                         power_state.RUNNING)

        self.driver.snapshot(instance_ref, name)

    @exception.wrap_exception
    def set_admin_password(self, context, instance_id, new_pass=None):
        """Set the root/admin password for an instance on this server."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)
        self._update_state(context, instance_id)

        if instance_ref['state'] != power_state.RUNNING:
            logging.warn('trying to reset the password on a non-running '
                    'instance: %s (state: %s expected: %s)',
                    instance_ref['id'],
                    instance_ref['state'],
                    power_state.RUNNING)

        logging.debug('instance %s: setting admin password',
                instance_ref['name'])
        self.db.instance_set_state(context, instance_id,
                power_state.NOSTATE, 'setting_password')
        if new_pass is None:
            # Generate a random password
            new_pass = self._generate_password(FLAGS.password_length)
        self.driver.set_admin_password(instance_ref, new_pass)
        self._update_state(context, instance_id)

    def _generate_password(self, length=20):
        """Generate a random sequence of letters and digits
        to be used as a password.
        """
        chrs = string.letters + string.digits
        return "".join([random.choice(chrs) for i in xrange(length)])

    @exception.wrap_exception
    def rescue_instance(self, context, instance_id):
        """Rescue an instance on this server."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        logging.debug(_('instance %s: rescuing'), instance_id)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'rescuing')
        self.network_manager.setup_compute_network(context, instance_id)
        self.driver.rescue(instance_ref)
        self._update_state(context, instance_id)

    @exception.wrap_exception
    def unrescue_instance(self, context, instance_id):
        """Rescue an instance on this server."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        logging.debug(_('instance %s: unrescuing'), instance_id)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'unrescuing')
        self.driver.unrescue(instance_ref)
        self._update_state(context, instance_id)

    @staticmethod
    def _update_state_callback(self, context, instance_id, result):
        """Update instance state when async task completes."""
        self._update_state(context, instance_id)

    @exception.wrap_exception
    def pause_instance(self, context, instance_id):
        """Pause an instance on this server."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        logging.debug('instance %s: pausing', instance_id)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'pausing')
        self.driver.pause(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception
    def unpause_instance(self, context, instance_id):
        """Unpause a paused instance on this server."""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        logging.debug('instance %s: unpausing', instance_id)
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'unpausing')
        self.driver.unpause(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception
    def get_diagnostics(self, context, instance_id):
        """Retrieve diagnostics for an instance on this server."""
        instance_ref = self.db.instance_get(context, instance_id)

        if instance_ref["state"] == power_state.RUNNING:
            logging.debug(_("instance %s: retrieving diagnostics"),
                          instance_id)
            return self.driver.get_diagnostics(instance_ref)

    @exception.wrap_exception
    def suspend_instance(self, context, instance_id):
        """suspend the instance with instance_id"""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        logging.debug(_('instance %s: suspending'), instance_id)
        self.db.instance_set_state(context, instance_id,
                                            power_state.NOSTATE,
                                            'suspending')
        self.driver.suspend(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception
    def resume_instance(self, context, instance_id):
        """resume the suspended instance with instance_id"""
        context = context.elevated()
        instance_ref = self.db.instance_get(context, instance_id)

        logging.debug(_('instance %s: resuming'), instance_id)
        self.db.instance_set_state(context, instance_id,
                                            power_state.NOSTATE,
                                            'resuming')
        self.driver.resume(instance_ref,
            lambda result: self._update_state_callback(self,
                                                       context,
                                                       instance_id,
                                                       result))

    @exception.wrap_exception
    def get_console_output(self, context, instance_id):
        """Send the console output for an instance."""
        context = context.elevated()
        logging.debug(_("instance %s: getting console output"), instance_id)
        instance_ref = self.db.instance_get(context, instance_id)

        return self.driver.get_console_output(instance_ref)

    @exception.wrap_exception
    def attach_volume(self, context, instance_id, volume_id, mountpoint):
        """Attach a volume to an instance."""
        context = context.elevated()
        logging.debug(_("instance %s: attaching volume %s to %s"), instance_id,
            volume_id, mountpoint)
        instance_ref = self.db.instance_get(context, instance_id)
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
        except Exception as exc:  # pylint: disable-msg=W0702
            # NOTE(vish): The inline callback eats the exception info so we
            #             log the traceback here and reraise the same
            #             ecxception below.
            logging.exception(_("instance %s: attach failed %s, removing"),
                              instance_id, mountpoint)
            self.volume_manager.remove_compute_volume(context,
                                                      volume_id)
            raise exc

        return True

    @exception.wrap_exception
    def detach_volume(self, context, instance_id, volume_id):
        """Detach a volume from an instance."""
        context = context.elevated()
        logging.debug(_("instance %s: detaching volume %s"),
                      instance_id,
                      volume_id)
        instance_ref = self.db.instance_get(context, instance_id)
        volume_ref = self.db.volume_get(context, volume_id)
        if instance_ref['name'] not in self.driver.list_instances():
            logging.warn(_("Detaching volume from unknown instance %s"),
                         instance_ref['name'])
        else:
            self.driver.detach_volume(instance_ref['name'],
                                      volume_ref['mountpoint'])
        self.volume_manager.remove_compute_volume(context, volume_id)
        self.db.volume_detached(context, volume_id)
        return True
