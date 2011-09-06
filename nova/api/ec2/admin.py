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
Admin API controller, exposed through http via the api worker.
"""

import base64
import netaddr
import urllib

from nova import compute
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.api.ec2 import ec2utils
from nova.auth import manager
from nova.compute import vm_states


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.ec2.admin')


def user_dict(user, base64_file=None):
    """Convert the user object to a result dict"""
    if user:
        return {
            'username': user.id,
            'accesskey': user.access,
            'secretkey': user.secret,
            'file': base64_file}
    else:
        return {}


def project_dict(project):
    """Convert the project object to a result dict"""
    if project:
        return {
            'projectname': project.id,
            'project_manager_id': project.project_manager_id,
            'description': project.description}
    else:
        return {}


def host_dict(host, compute_service, instances, volume_service, volumes, now):
    """Convert a host model object to a result dict"""
    rv = {'hostname': host, 'instance_count': len(instances),
          'volume_count': len(volumes)}
    if compute_service:
        latest = compute_service['updated_at'] or compute_service['created_at']
        delta = now - latest
        if delta.seconds <= FLAGS.service_down_time:
            rv['compute'] = 'up'
        else:
            rv['compute'] = 'down'
    if volume_service:
        latest = volume_service['updated_at'] or volume_service['created_at']
        delta = now - latest
        if delta.seconds <= FLAGS.service_down_time:
            rv['volume'] = 'up'
        else:
            rv['volume'] = 'down'
    return rv


def instance_dict(inst):
    return {'name': inst['name'],
            'memory_mb': inst['memory_mb'],
            'vcpus': inst['vcpus'],
            'disk_gb': inst['local_gb'],
            'flavor_id': inst['flavorid']}


def vpn_dict(project, vpn_instance):
    rv = {'project_id': project.id,
          'public_ip': project.vpn_ip,
          'public_port': project.vpn_port}
    if vpn_instance:
        rv['instance_id'] = ec2utils.id_to_ec2_id(vpn_instance['id'])
        rv['created_at'] = utils.isotime(vpn_instance['created_at'])
        address = vpn_instance.get('fixed_ip', None)
        if address:
            rv['internal_ip'] = address['address']
        if project.vpn_ip and project.vpn_port:
            if utils.vpn_ping(project.vpn_ip, project.vpn_port):
                rv['state'] = 'running'
            else:
                rv['state'] = 'down'
        else:
            rv['state'] = 'down - invalid project vpn config'
    else:
        rv['state'] = 'pending'
    return rv


class AdminController(object):
    """
    API Controller for users, hosts, nodes, and workers.
    """

    def __str__(self):
        return 'AdminController'

    def __init__(self):
        self.compute_api = compute.API()

    def describe_instance_types(self, context, **_kwargs):
        """Returns all active instance types data (vcpus, memory, etc.)"""
        return {'instanceTypeSet': [instance_dict(v) for v in
                                   db.instance_type_get_all(context).values()]}

    def describe_user(self, _context, name, **_kwargs):
        """Returns user data, including access and secret keys."""
        return user_dict(manager.AuthManager().get_user(name))

    def describe_users(self, _context, **_kwargs):
        """Returns all users - should be changed to deal with a list."""
        return {'userSet':
                [user_dict(u) for u in manager.AuthManager().get_users()]}

    def register_user(self, context, name, **_kwargs):
        """Creates a new user, and returns generated credentials."""
        LOG.audit(_("Creating new user: %s"), name, context=context)
        return user_dict(manager.AuthManager().create_user(name))

    def deregister_user(self, context, name, **_kwargs):
        """Deletes a single user (NOT undoable.)
           Should throw an exception if the user has instances,
           volumes, or buckets remaining.
        """
        LOG.audit(_("Deleting user: %s"), name, context=context)
        manager.AuthManager().delete_user(name)
        return True

    def describe_roles(self, context, project_roles=True, **kwargs):
        """Returns a list of allowed roles."""
        roles = manager.AuthManager().get_roles(project_roles)
        return {'roles': [{'role': r} for r in roles]}

    def describe_user_roles(self, context, user, project=None, **kwargs):
        """Returns a list of roles for the given user.
           Omitting project will return any global roles that the user has.
           Specifying project will return only project specific roles.
        """
        roles = manager.AuthManager().get_user_roles(user, project=project)
        return {'roles': [{'role': r} for r in roles]}

    def modify_user_role(self, context, user, role, project=None,
                         operation='add', **kwargs):
        """Add or remove a role for a user and project."""
        if operation == 'add':
            if project:
                msg = _("Adding role %(role)s to user %(user)s"
                        " for project %(project)s") % locals()
                LOG.audit(msg, context=context)
            else:
                msg = _("Adding sitewide role %(role)s to"
                        " user %(user)s") % locals()
                LOG.audit(msg, context=context)
            manager.AuthManager().add_role(user, role, project)
        elif operation == 'remove':
            if project:
                msg = _("Removing role %(role)s from user %(user)s"
                        " for project %(project)s") % locals()
                LOG.audit(msg, context=context)
            else:
                msg = _("Removing sitewide role %(role)s"
                        " from user %(user)s") % locals()
                LOG.audit(msg, context=context)
            manager.AuthManager().remove_role(user, role, project)
        else:
            raise exception.ApiError(_('operation must be add or remove'))

        return True

    def generate_x509_for_user(self, context, name, project=None, **kwargs):
        """Generates and returns an x509 certificate for a single user.
           Is usually called from a client that will wrap this with
           access and secret key info, and return a zip file.
        """
        if project is None:
            project = name
        project = manager.AuthManager().get_project(project)
        user = manager.AuthManager().get_user(name)
        msg = _("Getting x509 for user: %(name)s"
                " on project: %(project)s") % locals()
        LOG.audit(msg, context=context)
        return user_dict(user, base64.b64encode(project.get_credentials(user)))

    def describe_project(self, context, name, **kwargs):
        """Returns project data, including member ids."""
        return project_dict(manager.AuthManager().get_project(name))

    def describe_projects(self, context, user=None, **kwargs):
        """Returns all projects - should be changed to deal with a list."""
        return {'projectSet':
            [project_dict(u) for u in
            manager.AuthManager().get_projects(user=user)]}

    def register_project(self, context, name, manager_user, description=None,
                         member_users=None, **kwargs):
        """Creates a new project"""
        msg = _("Create project %(name)s managed by"
                " %(manager_user)s") % locals()
        LOG.audit(msg, context=context)
        return project_dict(
            manager.AuthManager().create_project(
                name,
                manager_user,
                description=None,
                member_users=None))

    def modify_project(self, context, name, manager_user, description=None,
                       **kwargs):
        """Modifies a project"""
        msg = _("Modify project: %(name)s managed by"
                " %(manager_user)s") % locals()
        LOG.audit(msg, context=context)
        manager.AuthManager().modify_project(name,
                                             manager_user=manager_user,
                                             description=description)
        return True

    def deregister_project(self, context, name):
        """Permanently deletes a project."""
        LOG.audit(_("Delete project: %s"), name, context=context)
        manager.AuthManager().delete_project(name)
        return True

    def describe_project_members(self, context, name, **kwargs):
        project = manager.AuthManager().get_project(name)
        result = {
            'members': [{'member': m} for m in project.member_ids]}
        return result

    def modify_project_member(self, context, user, project, operation,
                              **kwargs):
        """Add or remove a user from a project."""
        if operation == 'add':
            msg = _("Adding user %(user)s to project %(project)s") % locals()
            LOG.audit(msg, context=context)
            manager.AuthManager().add_to_project(user, project)
        elif operation == 'remove':
            msg = _("Removing user %(user)s from"
                    " project %(project)s") % locals()
            LOG.audit(msg, context=context)
            manager.AuthManager().remove_from_project(user, project)
        else:
            raise exception.ApiError(_('operation must be add or remove'))
        return True

    def _vpn_for(self, context, project_id):
        """Get the VPN instance for a project ID."""
        for instance in db.instance_get_all_by_project(context, project_id):
            if (instance['image_id'] == str(FLAGS.vpn_image_id)
                and not instance['vm_state'] in [vm_states.DELETED]):
                return instance

    def start_vpn(self, context, project):
        instance = self._vpn_for(context, project)
        if not instance:
            # NOTE(vish) import delayed because of __init__.py
            from nova.cloudpipe import pipelib
            pipe = pipelib.CloudPipe()
            proj = manager.AuthManager().get_project(project)
            user_id = proj.project_manager_id
            try:
                pipe.launch_vpn_instance(project, user_id)
            except db.NoMoreNetworks:
                raise exception.ApiError("Unable to claim IP for VPN instance"
                                         ", ensure it isn't running, and try "
                                         "again in a few minutes")
            instance = self._vpn_for(context, project)
        return {'instance_id': ec2utils.id_to_ec2_id(instance['id'])}

    def describe_vpns(self, context):
        vpns = []
        for project in manager.AuthManager().get_projects():
            instance = self._vpn_for(context, project.id)
            vpns.append(vpn_dict(project, instance))
        return {'items': vpns}

    # FIXME(vish): these host commands don't work yet, perhaps some of the
    #              required data can be retrieved from service objects?

    def describe_hosts(self, context, **_kwargs):
        """Returns status info for all nodes. Includes:
            * Hostname
            * Compute (up, down, None)
            * Instance count
            * Volume (up, down, None)
            * Volume Count
        """
        services = db.service_get_all(context, False)
        now = utils.utcnow()
        hosts = []
        rv = []
        for host in [service['host'] for service in services]:
            if not host in hosts:
                hosts.append(host)
        for host in hosts:
            compute = [s for s in services if s['host'] == host \
                                           and s['binary'] == 'nova-compute']
            if compute:
                compute = compute[0]
            instances = db.instance_get_all_by_host(context, host)
            volume = [s for s in services if s['host'] == host \
                                           and s['binary'] == 'nova-volume']
            if volume:
                volume = volume[0]
            volumes = db.volume_get_all_by_host(context, host)
            rv.append(host_dict(host, compute, instances, volume, volumes,
                                now))
        return {'hosts': rv}

    def _provider_fw_rule_exists(self, context, rule):
        # TODO(todd): we call this repeatedly, can we filter by protocol?
        for old_rule in db.provider_fw_rule_get_all(context):
            if all([rule[k] == old_rule[k] for k in ('cidr', 'from_port',
                                                     'to_port', 'protocol')]):
                return True
        return False

    def block_external_addresses(self, context, cidr):
        """Add provider-level firewall rules to block incoming traffic."""
        LOG.audit(_('Blocking traffic to all projects incoming from %s'),
                  cidr, context=context)
        cidr = urllib.unquote(cidr).decode()
        # raise if invalid
        netaddr.IPNetwork(cidr)
        rule = {'cidr': cidr}
        tcp_rule = rule.copy()
        tcp_rule.update({'protocol': 'tcp', 'from_port': 1, 'to_port': 65535})
        udp_rule = rule.copy()
        udp_rule.update({'protocol': 'udp', 'from_port': 1, 'to_port': 65535})
        icmp_rule = rule.copy()
        icmp_rule.update({'protocol': 'icmp', 'from_port': -1,
                          'to_port': None})
        rules_added = 0
        if not self._provider_fw_rule_exists(context, tcp_rule):
            db.provider_fw_rule_create(context, tcp_rule)
            rules_added += 1
        if not self._provider_fw_rule_exists(context, udp_rule):
            db.provider_fw_rule_create(context, udp_rule)
            rules_added += 1
        if not self._provider_fw_rule_exists(context, icmp_rule):
            db.provider_fw_rule_create(context, icmp_rule)
            rules_added += 1
        if not rules_added:
            raise exception.ApiError(_('Duplicate rule'))
        self.compute_api.trigger_provider_fw_rules_refresh(context)
        return {'status': 'OK', 'message': 'Added %s rules' % rules_added}

    def describe_external_address_blocks(self, context):
        blocks = db.provider_fw_rule_get_all(context)
        # NOTE(todd): use a set since we have icmp/udp/tcp rules with same cidr
        blocks = set([b.cidr for b in blocks])
        blocks = [{'cidr': b} for b in blocks]
        return {'externalIpBlockInfo':
                list(sorted(blocks, key=lambda k: k['cidr']))}

    def remove_external_address_block(self, context, cidr):
        LOG.audit(_('Removing ip block from %s'), cidr, context=context)
        cidr = urllib.unquote(cidr).decode()
        # raise if invalid
        netaddr.IPNetwork(cidr)
        rules = db.provider_fw_rule_get_all_by_cidr(context, cidr)
        for rule in rules:
            db.provider_fw_rule_destroy(context, rule['id'])
        if rules:
            self.compute_api.trigger_provider_fw_rules_refresh(context)
        return {'status': 'OK', 'message': 'Deleted %s rules' % len(rules)}
