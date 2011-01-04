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
Handles all requests relating to instances (guest vms).
"""

import datetime
import logging
import time

from nova import db
from nova import exception
from nova import flags
from nova import network
from nova import quota
from nova import rpc
from nova import utils
from nova import volume
from nova.compute import instance_types
from nova.db import base

FLAGS = flags.FLAGS


def generate_default_hostname(instance_id):
    """Default function to generate a hostname given an instance reference."""
    return str(instance_id)


class API(base.Base):
    """API for interacting with the compute manager."""

    def __init__(self, image_service=None, network_api=None, volume_api=None,
                 **kwargs):
        if not image_service:
            image_service = utils.import_object(FLAGS.image_service)
        self.image_service = image_service
        if not network_api:
            network_api = network.API()
        self.network_api = network_api
        if not volume_api:
            volume_api = volume.API()
        self.volume_api = volume_api
        super(API, self).__init__(**kwargs)

    def get_network_topic(self, context, instance_id):
        try:
            instance = self.get(context, instance_id)
        except exception.NotFound as e:
            logging.warning("Instance %d was not found in get_network_topic",
                            instance_id)
            raise e

        host = instance['host']
        if not host:
            raise exception.Error("Instance %d has no host" % instance_id)
        topic = self.db.queue_get_for(context, FLAGS.compute_topic, host)
        return rpc.call(context,
                        topic,
                        {"method": "get_network_topic", "args": {'fake': 1}})

    def create(self, context, instance_type,
               image_id, kernel_id=None, ramdisk_id=None,
               min_count=1, max_count=1,
               display_name='', display_description='',
               key_name=None, key_data=None, security_group='default',
               availability_zone=None, user_data=None,
               generate_hostname=generate_default_hostname):
        """Create the number of instances requested if quota and
        other arguments check out ok."""

        type_data = instance_types.INSTANCE_TYPES[instance_type]
        num_instances = quota.allowed_instances(context, max_count, type_data)
        if num_instances < min_count:
            logging.warn("Quota exceeeded for %s, tried to run %s instances",
                         context.project_id, min_count)
            raise quota.QuotaError("Instance quota exceeded. You can only "
                                   "run %s more instances of this type." %
                                   num_instances, "InstanceLimitExceeded")

        is_vpn = image_id == FLAGS.vpn_image_id
        if not is_vpn:
            image = self.image_service.show(context, image_id)
            if kernel_id is None:
                kernel_id = image.get('kernelId', None)
            if ramdisk_id is None:
                ramdisk_id = image.get('ramdiskId', None)
            # No kernel and ramdisk for raw images
            if kernel_id == str(FLAGS.null_kernel):
                kernel_id = None
                ramdisk_id = None
                logging.debug("Creating a raw instance")
            # Make sure we have access to kernel and ramdisk (if not raw)
            if kernel_id:
                self.image_service.show(context, kernel_id)
            if ramdisk_id:
                self.image_service.show(context, ramdisk_id)

        if security_group is None:
            security_group = ['default']
        if not type(security_group) is list:
            security_group = [security_group]

        security_groups = []
        self.ensure_default_security_group(context)
        for security_group_name in security_group:
            group = db.security_group_get_by_name(context,
                                                  context.project_id,
                                                  security_group_name)
            security_groups.append(group['id'])

        if key_data is None and key_name:
            key_pair = db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        base_options = {
            'reservation_id': utils.generate_uid('r'),
            'image_id': image_id,
            'kernel_id': kernel_id or '',
            'ramdisk_id': ramdisk_id or '',
            'state_description': 'scheduling',
            'user_id': context.user_id,
            'project_id': context.project_id,
            'launch_time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'instance_type': instance_type,
            'memory_mb': type_data['memory_mb'],
            'vcpus': type_data['vcpus'],
            'local_gb': type_data['local_gb'],
            'display_name': display_name,
            'display_description': display_description,
            'user_data': user_data or '',
            'key_name': key_name,
            'key_data': key_data,
            'availability_zone': availability_zone}

        elevated = context.elevated()
        instances = []
        logging.debug(_("Going to run %s instances..."), num_instances)
        for num in range(num_instances):
            instance = dict(mac_address=utils.generate_mac(),
                            launch_index=num,
                            **base_options)
            instance = self.db.instance_create(context, instance)
            instance_id = instance['id']

            elevated = context.elevated()
            if not security_groups:
                security_groups = []
            for security_group_id in security_groups:
                self.db.instance_add_security_group(elevated,
                                                    instance_id,
                                                    security_group_id)

            # Set sane defaults if not specified
            updates = dict(hostname=generate_hostname(instance_id))
            if 'display_name' not in instance:
                updates['display_name'] = "Server %s" % instance_id

            instance = self.update(context, instance_id, **updates)
            instances.append(instance)

            logging.debug(_("Casting to scheduler for %s/%s's instance %s"),
                          context.project_id, context.user_id, instance_id)
            rpc.cast(context,
                     FLAGS.scheduler_topic,
                     {"method": "run_instance",
                      "args": {"topic": FLAGS.compute_topic,
                               "instance_id": instance_id}})

        return instances

    def ensure_default_security_group(self, context):
        """ Create security group for the security context if it
        does not already exist

        :param context: the security context

        """
        try:
            db.security_group_get_by_name(context, context.project_id,
                                          'default')
        except exception.NotFound:
            values = {'name': 'default',
                      'description': 'default',
                      'user_id': context.user_id,
                      'project_id': context.project_id}
            db.security_group_create(context, values)

    def update(self, context, instance_id, **kwargs):
        """Updates the instance in the datastore.

        :param context: The security context
        :param instance_id: ID of the instance to update
        :param kwargs: All additional keyword args are treated
                       as data fields of the instance to be
                       updated

        :retval None

        """
        return self.db.instance_update(context, instance_id, kwargs)

    def delete(self, context, instance_id):
        logging.debug("Going to try and terminate %s" % instance_id)
        try:
            instance = self.get(context, instance_id)
        except exception.NotFound as e:
            logging.warning(_("Instance %s was not found during terminate"),
                            instance_id)
            raise e

        if (instance['state_description'] == 'terminating'):
            logging.warning(_("Instance %s is already being terminated"),
                            instance_id)
            return

        self.update(context,
                    instance['id'],
                    state_description='terminating',
                    state=0,
                    terminated_at=datetime.datetime.utcnow())

        host = instance['host']
        if host:
            rpc.cast(context,
                     self.db.queue_get_for(context, FLAGS.compute_topic, host),
                     {"method": "terminate_instance",
                      "args": {"instance_id": instance_id}})
        else:
            self.db.instance_destroy(context, instance_id)

    def get(self, context, instance_id=None, project_id=None,
            reservation_id=None, fixed_ip=None):
        """Get one or more instances, possibly filtered by one of the
        given parameters. If there is no filter and the context is
        an admin, it will retreive all instances in the system."""
        if instance_id is not None:
            return self.db.instance_get_by_id(context, instance_id)
        if reservation_id is not None:
            return self.db.instance_get_all_by_reservation(context,
                                                           reservation_id)
        if fixed_ip is not None:
            return self.db.fixed_ip_get_instance(context, fixed_ip)
        if project_id or not context.is_admin:
            if not context.project:
                return self.db.instance_get_all_by_user(context,
                                                        context.user_id)
            if project_id is None:
                project_id = context.project_id
            return self.db.instance_get_all_by_project(context,
            project_id)
        return self.db.instance_get_all(context)

    def snapshot(self, context, instance_id, name):
        """Snapshot the given instance."""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "snapshot_instance",
                  "args": {"instance_id": instance_id, "name": name}})

    def reboot(self, context, instance_id):
        """Reboot the given instance."""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "reboot_instance",
                  "args": {"instance_id": instance_id}})

    def pause(self, context, instance_id):
        """Pause the given instance."""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "pause_instance",
                  "args": {"instance_id": instance_id}})

    def unpause(self, context, instance_id):
        """Unpause the given instance."""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "unpause_instance",
                  "args": {"instance_id": instance_id}})

    def get_diagnostics(self, context, instance_id):
        """Retrieve diagnostics for the given instance."""
        instance = self.get(context, instance_id)
        host = instance["host"]
        return rpc.call(context,
            self.db.queue_get_for(context, FLAGS.compute_topic, host),
            {"method": "get_diagnostics",
             "args": {"instance_id": instance_id}})

    def get_actions(self, context, instance_id):
        """Retrieve actions for the given instance."""
        return self.db.instance_get_actions(context, instance_id)

    def suspend(self, context, instance_id):
        """suspend the instance with instance_id"""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "suspend_instance",
                  "args": {"instance_id": instance_id}})

    def resume(self, context, instance_id):
        """resume the instance with instance_id"""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "resume_instance",
                  "args": {"instance_id": instance_id}})

    def rescue(self, context, instance_id):
        """Rescue the given instance."""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "rescue_instance",
                  "args": {"instance_id": instance_id}})

    def unrescue(self, context, instance_id):
        """Unrescue the given instance."""
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "unrescue_instance",
                  "args": {"instance_id": instance_id}})

    def attach_volume(self, context, instance_id, volume_id, device):
        if not re.match("^/dev/[a-z]d[a-z]+$", device):
            raise exception.ApiError(_("Invalid device specified: %s. "
                                     "Example device: /dev/vdb") % device)
        self.volume_api.check_attach(context, volume_id)
        instance = self.get(context, instance_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "attach_volume",
                  "args": {"volume_id": volume_id,
                           "instance_id": instance_id,
                           "mountpoint": device}})

    def detach_volume(self, context, volume_id):
        instance = self.db.volume_get_instance(context.elevated(), volume_id)
        if not instance:
            raise exception.ApiError(_("Volume isn't attached to anything!"))
        self.volume_api.check_detach(context, volume_id)
        host = instance['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "detach_volume",
                  "args": {"instance_id": instance['id'],
                           "volume_id": volume_id}})
        return instance

    def associate_floating_ip(self, context, instance_id, address):
        instance = self.get(context, instance_id)
        self.network_api.associate_floating_ip(context, address,
                                               instance['fixed_ip'])
