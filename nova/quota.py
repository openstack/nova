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
Quotas for instances, volumes, and floating ips
"""

from nova import db
from nova import exception
from nova import flags
from nova.compute import instance_types

FLAGS = flags.FLAGS

flags.DEFINE_integer('quota_instances', 10,
                     'number of instances allowed per project')
flags.DEFINE_integer('quota_cores', 20,
                     'number of instance cores allowed per project')
flags.DEFINE_integer('quota_volumes', 10,
                     'number of volumes allowed per project')
flags.DEFINE_integer('quota_gigabytes', 1000,
                     'number of volume gigabytes allowed per project')
flags.DEFINE_integer('quota_floating_ips', 10,
                     'number of floating ips allowed per project')


def get_quota(context, project_id):
    rval = {'instances': FLAGS.quota_instances,
            'cores': FLAGS.quota_cores,
            'volumes': FLAGS.quota_volumes,
            'gigabytes': FLAGS.quota_gigabytes,
            'floating_ips': FLAGS.quota_floating_ips}
    try:
        quota = db.quota_get(context, project_id)
        for key in rval.keys():
            if quota[key] is not None:
                rval[key] = quota[key]
    except exception.NotFound:
        pass
    return rval


def allowed_instances(context, num_instances, instance_type):
    """Check quota and return min(num_instances, allowed_instances)"""
    project_id = context.project_id
    context = context.elevated()
    used_instances, used_cores = db.instance_data_get_for_project(context,
                                                                  project_id)
    quota = get_quota(context, project_id)
    allowed_instances = quota['instances'] - used_instances
    allowed_cores = quota['cores'] - used_cores
    type_cores = instance_types.INSTANCE_TYPES[instance_type]['vcpus']
    num_cores = num_instances * type_cores
    allowed_instances = min(allowed_instances,
                            int(allowed_cores // type_cores))
    return min(num_instances, allowed_instances)


def allowed_volumes(context, num_volumes, size):
    """Check quota and return min(num_volumes, allowed_volumes)"""
    project_id = context.project_id
    context = context.elevated()
    used_volumes, used_gigabytes = db.volume_data_get_for_project(context,
                                                                  project_id)
    quota = get_quota(context, project_id)
    allowed_volumes = quota['volumes'] - used_volumes
    allowed_gigabytes = quota['gigabytes'] - used_gigabytes
    size = int(size)
    num_gigabytes = num_volumes * size
    allowed_volumes = min(allowed_volumes,
                          int(allowed_gigabytes // size))
    return min(num_volumes, allowed_volumes)


def allowed_floating_ips(context, num_floating_ips):
    """Check quota and return min(num_floating_ips, allowed_floating_ips)"""
    project_id = context.project_id
    context = context.elevated()
    used_floating_ips = db.floating_ip_count_by_project(context, project_id)
    quota = get_quota(context, project_id)
    allowed_floating_ips = quota['floating_ips'] - used_floating_ips
    return min(num_floating_ips, allowed_floating_ips)
