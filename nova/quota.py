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

"""Quotas for instances, volumes, and floating ips."""

from nova import db
from nova.openstack.common import cfg
from nova import flags


quota_opts = [
    cfg.IntOpt('quota_instances',
               default=10,
               help='number of instances allowed per project'),
    cfg.IntOpt('quota_cores',
               default=20,
               help='number of instance cores allowed per project'),
    cfg.IntOpt('quota_ram',
               default=50 * 1024,
               help='megabytes of instance ram allowed per project'),
    cfg.IntOpt('quota_volumes',
               default=10,
               help='number of volumes allowed per project'),
    cfg.IntOpt('quota_gigabytes',
               default=1000,
               help='number of volume gigabytes allowed per project'),
    cfg.IntOpt('quota_floating_ips',
               default=10,
               help='number of floating ips allowed per project'),
    cfg.IntOpt('quota_metadata_items',
               default=128,
               help='number of metadata items allowed per instance'),
    cfg.IntOpt('quota_max_injected_files',
               default=5,
               help='number of injected files allowed'),
    cfg.IntOpt('quota_max_injected_file_content_bytes',
               default=10 * 1024,
               help='number of bytes allowed per injected file'),
    cfg.IntOpt('quota_max_injected_file_path_bytes',
               default=255,
               help='number of bytes allowed per injected file path'),
    cfg.IntOpt('quota_security_groups',
               default=10,
               help='number of security groups per project'),
    cfg.IntOpt('quota_security_group_rules',
               default=20,
               help='number of security rules per security group'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(quota_opts)


def _get_default_quotas():
    defaults = {
        'instances': FLAGS.quota_instances,
        'cores': FLAGS.quota_cores,
        'ram': FLAGS.quota_ram,
        'volumes': FLAGS.quota_volumes,
        'gigabytes': FLAGS.quota_gigabytes,
        'floating_ips': FLAGS.quota_floating_ips,
        'metadata_items': FLAGS.quota_metadata_items,
        'injected_files': FLAGS.quota_max_injected_files,
        'injected_file_content_bytes':
            FLAGS.quota_max_injected_file_content_bytes,
        'security_groups': FLAGS.quota_security_groups,
        'security_group_rules': FLAGS.quota_security_group_rules,
    }
    # -1 in the quota flags means unlimited
    for key in defaults.keys():
        if defaults[key] == -1:
            defaults[key] = None
    return defaults


def get_project_quotas(context, project_id):
    rval = _get_default_quotas()
    quota = db.quota_get_all_by_project(context, project_id)
    for key in rval.keys():
        if key in quota:
            rval[key] = quota[key]
    return rval


def _get_request_allotment(requested, used, quota):
    if quota is None:
        return requested
    return quota - used


def allowed_instances(context, requested_instances, instance_type):
    """Check quota and return min(requested_instances, allowed_instances)."""
    project_id = context.project_id
    context = context.elevated()
    requested_cores = requested_instances * instance_type['vcpus']
    requested_ram = requested_instances * instance_type['memory_mb']
    usage = db.instance_data_get_for_project(context, project_id)
    used_instances, used_cores, used_ram = usage
    quota = get_project_quotas(context, project_id)
    allowed_instances = _get_request_allotment(requested_instances,
                                               used_instances,
                                               quota['instances'])
    allowed_cores = _get_request_allotment(requested_cores, used_cores,
                                           quota['cores'])
    allowed_ram = _get_request_allotment(requested_ram, used_ram, quota['ram'])
    if instance_type['vcpus']:
        allowed_instances = min(allowed_instances,
                                allowed_cores // instance_type['vcpus'])
    if instance_type['memory_mb']:
        allowed_instances = min(allowed_instances,
                                allowed_ram // instance_type['memory_mb'])

    return min(requested_instances, allowed_instances)


def allowed_volumes(context, requested_volumes, size):
    """Check volume quotas and return breached if any."""
    project_id = context.project_id
    context = context.elevated()
    size = int(size)

    allowed = {}
    overs = []

    used_volumes, used_gigabytes = db.volume_data_get_for_project(context,
                                                                  project_id)
    usages = dict(volumes=used_volumes, gigabytes=used_gigabytes)

    quotas = get_project_quotas(context, project_id)

    def _check_allowed(resource, requested):
        allow = _get_request_allotment(requested,
                                       usages[resource],
                                       quotas[resource])
        if requested and allow < requested:
            overs.append(resource)
        allowed[resource] = allow

    _check_allowed('volumes', requested_volumes)
    _check_allowed('gigabytes', requested_volumes * size)

    if size != 0:
        allowed['volumes'] = min(allowed['volumes'],
                                 int(allowed['gigabytes'] // size))

    return dict(overs=overs, usages=usages, quotas=quotas, allowed=allowed)


def allowed_floating_ips(context, requested_floating_ips):
    """Check quota and return min(requested, allowed) floating ips."""
    project_id = context.project_id
    context = context.elevated()
    used_floating_ips = db.floating_ip_count_by_project(context, project_id)
    quota = get_project_quotas(context, project_id)
    allowed_floating_ips = _get_request_allotment(requested_floating_ips,
                                                  used_floating_ips,
                                                  quota['floating_ips'])
    return min(requested_floating_ips, allowed_floating_ips)


def allowed_security_groups(context, requested_security_groups):
    """Check quota and return min(requested, allowed) security groups."""
    project_id = context.project_id
    context = context.elevated()
    used_sec_groups = db.security_group_count_by_project(context, project_id)
    quota = get_project_quotas(context, project_id)
    allowed_sec_groups = _get_request_allotment(requested_security_groups,
                                                  used_sec_groups,
                                                  quota['security_groups'])
    return min(requested_security_groups, allowed_sec_groups)


def allowed_security_group_rules(context, security_group_id,
        requested_rules):
    """Check quota and return min(requested, allowed) sec group rules."""
    project_id = context.project_id
    context = context.elevated()
    used_rules = db.security_group_rule_count_by_group(context,
                                                            security_group_id)
    quota = get_project_quotas(context, project_id)
    allowed_rules = _get_request_allotment(requested_rules,
                                              used_rules,
                                              quota['security_group_rules'])
    return min(requested_rules, allowed_rules)


def _calculate_simple_quota(context, resource, requested):
    """Check quota for resource; return min(requested, allowed)."""
    quota = get_project_quotas(context, context.project_id)
    allowed = _get_request_allotment(requested, 0, quota[resource])
    return min(requested, allowed)


def allowed_metadata_items(context, requested_metadata_items):
    """Return the number of metadata items allowed."""
    return _calculate_simple_quota(context, 'metadata_items',
                                   requested_metadata_items)


def allowed_injected_files(context, requested_injected_files):
    """Return the number of injected files allowed."""
    return _calculate_simple_quota(context, 'injected_files',
                                   requested_injected_files)


def allowed_injected_file_content_bytes(context, requested_bytes):
    """Return the number of bytes allowed per injected file content."""
    resource = 'injected_file_content_bytes'
    return _calculate_simple_quota(context, resource, requested_bytes)


def allowed_injected_file_path_bytes(context):
    """Return the number of bytes allowed in an injected file path."""
    return FLAGS.quota_max_injected_file_path_bytes
