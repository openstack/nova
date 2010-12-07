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
Handles all API requests relating to instances (guest vms).
"""

import logging
import time

from nova import db
from nova import exception
from nova import flags
from nova import quota
from nova import rpc
from nova import utils
from nova.compute import instance_types
from nova.db import base

FLAGS = flags.FLAGS


def generate_default_hostname(internal_id):
    """Default function to generate a hostname given an instance reference."""
    return str(internal_id)


class ComputeAPI(base.Base):
    """API for interacting with the compute manager."""

    def __init__(self, **kwargs):
        self.network_manager = utils.import_object(FLAGS.network_manager)
        super(ComputeAPI, self).__init__(**kwargs)

    # TODO(eday): network_topic arg should go away once we push network
    # allocation into the scheduler or compute worker.
    def create_instances(self, context, instance_type, image_service, image_id,
                         network_topic, min_count=1, max_count=1,
                         kernel_id=None, ramdisk_id=None, name='',
                         description='', user_data='', key_name=None,
                         key_data=None, security_group='default',
                         generate_hostname=generate_default_hostname):
        """Create the number of instances requested if quote and
        other arguments check out ok."""

        num_instances = quota.allowed_instances(context, max_count,
                                                instance_type)
        if num_instances < min_count:
            logging.warn("Quota exceeeded for %s, tried to run %s instances",
                         context.project_id, min_count)
            raise quota.QuotaError("Instance quota exceeded. You can only "
                                   "run %s more instances of this type." %
                                   num_instances, "InstanceLimitExceeded")

        is_vpn = image_id == FLAGS.vpn_image_id
        if not is_vpn:
            image = image_service.show(context, image_id)
            if kernel_id is None:
                kernel_id = image.get('kernelId', FLAGS.default_kernel)
            if ramdisk_id is None:
                ramdisk_id = image.get('ramdiskId', FLAGS.default_ramdisk)

            # Make sure we have access to kernel and ramdisk
            image_service.show(context, kernel_id)
            image_service.show(context, ramdisk_id)

        if security_group is None:
            security_group = ['default']
        if not type(security_group) is list:
            security_group = [security_group]

        print '<<<<<<<<<<<<<<<<<<<<<<<<<<1'
        security_groups = []
        self.ensure_default_security_group(context)
        for security_group_name in security_group:
            group = db.security_group_get_by_name(context,
                                                  context.project_id,
                                                  security_group_name)
            security_groups.append(group['id'])

        print '<<<<<<<<<<<<<<<<<<<<<<<<<<2'
        if key_data is None and key_name:
            key_pair = db.key_pair_get(context, context.user_id, key_name)
            key_data = key_pair['public_key']

        type_data = instance_types.INSTANCE_TYPES[instance_type]
        base_options = {
            'reservation_id': utils.generate_uid('r'),
            'image_id': image_id,
            'kernel_id': kernel_id,
            'ramdisk_id': ramdisk_id,
            'state_description': 'scheduling',
            'user_id': context.user_id,
            'project_id': context.project_id,
            'launch_time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'instance_type': instance_type,
            'memory_mb': type_data['memory_mb'],
            'vcpus': type_data['vcpus'],
            'local_gb': type_data['local_gb'],
            'display_name': name,
            'display_description': description,
            'key_name': key_name,
            'key_data': key_data}

        print '<<<<<<<<<<<<<<<<<<<<<<<<<<3'
        elevated = context.elevated()
        instances = []
        logging.debug("Going to run %s instances...", num_instances)
        for num in range(num_instances):
            instance = dict(mac_address=utils.generate_mac(),
                            launch_index=num,
                            **base_options)
            instance_ref = self.create_instance(context, security_groups,
                                                **instance)
            instance_id = instance_ref['id']
            internal_id = instance_ref['internal_id']
            hostname = generate_hostname(internal_id)
            self.update_instance(context, instance_id, hostname=hostname)
            instances.append(dict(id=instance_id, internal_id=internal_id,
                             hostname=hostname, **instance))

            # TODO(vish): This probably should be done in the scheduler
            #             or in compute as a call.  The network should be
            #             allocated after the host is assigned and setup
            #             can happen at the same time.
            address = self.network_manager.allocate_fixed_ip(context,
                                                             instance_id,
                                                             is_vpn)
            rpc.cast(elevated,
                     network_topic,
                     {"method": "setup_fixed_ip",
                      "args": {"address": address}})

            logging.debug("Casting to scheduler for %s/%s's instance %s" %
                          (context.project_id, context.user_id, instance_id))
            rpc.cast(context,
                     FLAGS.scheduler_topic,
                     {"method": "run_instance",
                      "args": {"topic": FLAGS.compute_topic,
                               "instance_id": instance_id}})

        return instances

    def ensure_default_security_group(self, context):
        try:
            db.security_group_get_by_name(context, context.project_id,
                                          'default')
        except exception.NotFound:
            values = {'name': 'default',
                      'description': 'default',
                      'user_id': context.user_id,
                      'project_id': context.project_id}
            group = db.security_group_create(context, values)

    def create_instance(self, context, security_groups=None, **kwargs):
        """Creates the instance in the datastore and returns the
        new instance as a mapping

        :param context: The security context
        :param security_groups: list of security group ids to
                                attach to the instance
        :param kwargs: All additional keyword args are treated
                       as data fields of the instance to be
                       created

        :retval Returns a mapping of the instance information
                that has just been created

        """
        instance_ref = self.db.instance_create(context, kwargs)
        inst_id = instance_ref['id']
        # Set sane defaults if not specified
        if kwargs.get('display_name') is None:
            display_name = "Server %s" % instance_ref['internal_id']
            instance_ref['display_name'] = display_name
            self.db.instance_update(context, inst_id,
                                    {'display_name': display_name})

        elevated = context.elevated()
        if not security_groups:
            security_groups = []
        for security_group_id in security_groups:
            self.db.instance_add_security_group(elevated,
                                                inst_id,
                                                security_group_id)
        return instance_ref

    def update_instance(self, context, instance_id, **kwargs):
        """Updates the instance in the datastore.

        :param context: The security context
        :param instance_id: ID of the instance to update
        :param kwargs: All additional keyword args are treated
                       as data fields of the instance to be
                       updated

        :retval None

        """
        self.db.instance_update(context, instance_id, kwargs)
