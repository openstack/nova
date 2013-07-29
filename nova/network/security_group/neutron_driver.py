# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Nicira, Inc.
# All Rights Reserved
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
#
# @author: Aaron Rosen, Nicira Networks, Inc.

import sys

from neutronclient.common import exceptions as n_exc
from neutronclient.neutron import v2_0 as neutronv20
from oslo.config import cfg
from webob import exc

from nova.compute import api as compute_api
from nova import exception
from nova.network import neutronv2
from nova.network.security_group import security_group_base
from nova.objects import security_group
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import uuidutils
from nova import utils


wrap_check_security_groups_policy = compute_api.policy_decorator(
    scope='compute:security_groups')

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SecurityGroupAPI(security_group_base.SecurityGroupBase):

    id_is_uuid = True

    def create_security_group(self, context, name, description):
        neutron = neutronv2.get_client(context)
        body = self._make_neutron_security_group_dict(name, description)
        try:
            security_group = neutron.create_security_group(
                body).get('security_group')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            LOG.exception(_("Neutron Error creating security group %s"),
                          name)
            if e.status_code == 401:
                # TODO(arosen) Cannot raise generic response from neutron here
                # as this error code could be related to bad input or over
                # quota
                raise exc.HTTPBadRequest()
            elif e.status_code == 409:
                self.raise_over_quota(e.message)
            raise exc_info[0], exc_info[1], exc_info[2]
        return self._convert_to_nova_security_group_format(security_group)

    def update_security_group(self, context, security_group,
                              name, description):
        neutron = neutronv2.get_client(context)
        body = self._make_neutron_security_group_dict(name, description)
        try:
            security_group = neutron.update_security_group(
                security_group['id'], body).get('security_group')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            LOG.exception(_("Neutron Error updating security group %s"),
                          name)
            if e.status_code == 401:
                # TODO(arosen) Cannot raise generic response from neutron here
                # as this error code could be related to bad input or over
                # quota
                raise exc.HTTPBadRequest()
            raise exc_info[0], exc_info[1], exc_info[2]
        return self._convert_to_nova_security_group_format(security_group)

    def _convert_to_nova_security_group_format(self, security_group):
        nova_group = {}
        nova_group['id'] = security_group['id']
        nova_group['description'] = security_group['description']
        nova_group['name'] = security_group['name']
        nova_group['project_id'] = security_group['tenant_id']
        nova_group['rules'] = []
        for rule in security_group.get('security_group_rules', []):
            if rule['direction'] == 'ingress':
                nova_group['rules'].append(
                    self._convert_to_nova_security_group_rule_format(rule))

        return nova_group

    def _convert_to_nova_security_group_rule_format(self, rule):
        nova_rule = {}
        nova_rule['id'] = rule['id']
        nova_rule['parent_group_id'] = rule['security_group_id']
        nova_rule['protocol'] = rule['protocol']
        if (nova_rule['protocol'] and rule.get('port_range_min') is None and
                rule.get('port_range_max') is None):
            if nova_rule['protocol'].upper() == 'ICMP':
                nova_rule['from_port'] = -1
                nova_rule['to_port'] = -1
            elif rule['protocol'].upper() in ['TCP', 'UDP']:
                nova_rule['from_port'] = 1
                nova_rule['to_port'] = 65535
        else:
            nova_rule['from_port'] = rule.get('port_range_min')
            nova_rule['to_port'] = rule.get('port_range_max')
        nova_rule['group_id'] = rule['remote_group_id']
        nova_rule['cidr'] = self.parse_cidr(rule.get('remote_ip_prefix'))
        return nova_rule

    def get(self, context, name=None, id=None, map_exception=False):
        neutron = neutronv2.get_client(context)
        try:
            if not id and name:
                id = neutronv20.find_resourceid_by_name_or_id(
                    neutron, 'security_group', name)
            group = neutron.show_security_group(id).get('security_group')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                LOG.debug(_("Neutron security group %s not found"), name)
                self.raise_not_found(e.message)
            else:
                LOG.error(_("Neutron Error: %s"), e)
                raise exc_info[0], exc_info[1], exc_info[2]

        return self._convert_to_nova_security_group_format(group)

    def list(self, context, names=None, ids=None, project=None,
             search_opts=None):
        """Returns list of security group rules owned by tenant."""
        neutron = neutronv2.get_client(context)
        search_opts = {}
        if names:
            search_opts['name'] = names
        if ids:
            search_opts['id'] = ids
        if project:
            search_opts['tenant_id'] = project
        try:
            security_groups = neutron.list_security_groups(**search_opts).get(
                'security_groups')
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Neutron Error getting security groups"))
        converted_rules = []
        for security_group in security_groups:
            converted_rules.append(
                self._convert_to_nova_security_group_format(security_group))
        return converted_rules

    def validate_id(self, id):
        if not uuidutils.is_uuid_like(id):
            msg = _("Security group id should be uuid")
            self.raise_invalid_property(msg)
        return id

    def destroy(self, context, security_group):
        """This function deletes a security group."""

        neutron = neutronv2.get_client(context)
        try:
            neutron.delete_security_group(security_group['id'])
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                self.raise_not_found(e.message)
            elif e.status_code == 409:
                self.raise_invalid_property(e.message)
            else:
                LOG.error(_("Neutron Error: %s"), e)
                raise exc_info[0], exc_info[1], exc_info[2]

    def add_rules(self, context, id, name, vals):
        """Add security group rule(s) to security group.

        Note: the Nova security group API doesn't support adding muliple
        security group rules at once but the EC2 one does. Therefore,
        this function is writen to support both. Multiple rules are
        installed to a security group in neutron using bulk support.
        """

        neutron = neutronv2.get_client(context)
        body = self._make_neutron_security_group_rules_list(vals)
        try:
            rules = neutron.create_security_group_rule(
                body).get('security_group_rules')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                LOG.exception(_("Neutron Error getting security group %s"),
                              name)
                self.raise_not_found(e.message)
            elif e.status_code == 409:
                LOG.exception(_("Neutron Error adding rules to security "
                                "group %s"), name)
                self.raise_over_quota(e.message)
            else:
                LOG.exception(_("Neutron Error:"))
                raise exc_info[0], exc_info[1], exc_info[2]
        converted_rules = []
        for rule in rules:
            converted_rules.append(
                self._convert_to_nova_security_group_rule_format(rule))
        return converted_rules

    def _make_neutron_security_group_dict(self, name, description):
        return {'security_group': {'name': name,
                                   'description': description}}

    def _make_neutron_security_group_rules_list(self, rules):
        new_rules = []
        for rule in rules:
            new_rule = {}
            # nova only supports ingress rules so all rules are ingress.
            new_rule['direction'] = "ingress"
            new_rule['protocol'] = rule.get('protocol')

            # FIXME(arosen) Nova does not expose ethertype on security group
            # rules. Therefore, in the case of self referential rules we
            # should probably assume they want to allow both IPv4 and IPv6.
            # Unfortunately, this would require adding two rules in neutron.
            # The reason we do not do this is because when the user using the
            # nova api wants to remove the rule we'd have to have some way to
            # know that we should delete both of these rules in neutron.
            # For now, self referential rules only support IPv4.
            if not rule.get('cidr'):
                new_rule['ethertype'] = 'IPv4'
            else:
                new_rule['ethertype'] = utils.get_ip_version(rule.get('cidr'))
            new_rule['remote_ip_prefix'] = rule.get('cidr')
            new_rule['security_group_id'] = rule.get('parent_group_id')
            new_rule['remote_group_id'] = rule.get('group_id')
            if 'from_port' in rule and rule['from_port'] != -1:
                new_rule['port_range_min'] = rule['from_port']
            if 'to_port' in rule and rule['to_port'] != -1:
                new_rule['port_range_max'] = rule['to_port']
            new_rules.append(new_rule)
        return {'security_group_rules': new_rules}

    def remove_rules(self, context, security_group, rule_ids):
        neutron = neutronv2.get_client(context)
        rule_ids = set(rule_ids)
        try:
            # The ec2 api allows one to delete multiple security group rules
            # at once. Since there is no bulk delete for neutron the best
            # thing we can do is delete the rules one by one and hope this
            # works.... :/
            for rule_id in range(0, len(rule_ids)):
                neutron.delete_security_group_rule(rule_ids.pop())
        except n_exc.NeutronClientException as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Neutron Error unable to delete %s"), rule_ids)

    def get_rule(self, context, id):
        neutron = neutronv2.get_client(context)
        try:
            rule = neutron.show_security_group_rule(
                id).get('security_group_rule')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                LOG.debug(_("Neutron security group rule %s not found"), id)
                self.raise_not_found(e.message)
            else:
                LOG.error(_("Neutron Error: %s"), e)
                raise exc_info[0], exc_info[1], exc_info[2]
        return self._convert_to_nova_security_group_rule_format(rule)

    def get_instances_security_groups_bindings(self, context):
        """Returns a dict(instance_id, [security_groups]) to allow obtaining
        all of the instances and their security groups in one shot.
        """
        neutron = neutronv2.get_client(context)
        ports = neutron.list_ports().get('ports')
        security_groups = neutron.list_security_groups().get('security_groups')
        security_group_lookup = {}
        instances_security_group_bindings = {}
        for security_group in security_groups:
            security_group_lookup[security_group['id']] = security_group

        for port in ports:
            for port_security_group in port.get('security_groups', []):
                try:
                    sg = security_group_lookup[port_security_group]
                    # name is optional in neutron so if not specified return id
                    if sg.get('name'):
                        sg_entry = {'name': sg['name']}
                    else:
                        sg_entry = {'name': sg['id']}
                    instances_security_group_bindings.setdefault(
                        port['device_id'], []).append(sg_entry)
                except KeyError:
                    # This should only happen due to a race condition
                    # if the security group on a port was deleted after the
                    # ports were returned. We pass since this security
                    # group is no longer on the port.
                    pass
        return instances_security_group_bindings

    def get_instance_security_groups(self, context, instance_uuid,
                                     detailed=False):
        """Returns the security groups that are associated with an instance.
        If detailed is True then it also returns the full details of the
        security groups associated with an instance.
        """
        neutron = neutronv2.get_client(context)
        params = {'device_id': instance_uuid}
        ports = neutron.list_ports(**params)
        security_groups = neutron.list_security_groups().get('security_groups')

        security_group_lookup = {}
        for security_group in security_groups:
            security_group_lookup[security_group['id']] = security_group

        ret = []
        for port in ports['ports']:
            for security_group in port.get('security_groups', []):
                try:
                    if detailed:
                        ret.append(self._convert_to_nova_security_group_format(
                            security_group_lookup[security_group]))
                    else:
                        name = security_group_lookup[security_group].get(
                            'name')
                        # Since the name is optional for
                        # neutron security groups
                        if not name:
                            name = security_group
                        ret.append({'name': name})
                except KeyError:
                    # This should only happen due to a race condition
                    # if the security group on a port was deleted after the
                    # ports were returned. We pass since this security
                    # group is no longer on the port.
                    pass

        return ret

    def _has_security_group_requirements(self, port):
        port_security_enabled = port.get('port_security_enabled', True)
        has_ip = port.get('fixed_ips')
        if has_ip:
            return port_security_enabled
        return False

    @wrap_check_security_groups_policy
    def add_to_instance(self, context, instance, security_group_name):
        """Add security group to the instance."""

        neutron = neutronv2.get_client(context)
        try:
            security_group_id = neutronv20.find_resourceid_by_name_or_id(
                neutron, 'security_group', security_group_name)
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                msg = ("Security group %s is not found for project %s" %
                       (security_group_name, context.project_id))
                self.raise_not_found(msg)
            else:
                LOG.exception(_("Neutron Error:"))
                raise exc_info[0], exc_info[1], exc_info[2]
        params = {'device_id': instance['uuid']}
        try:
            ports = neutron.list_ports(**params).get('ports')
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Neutron Error:"))

        if not ports:
            msg = ("instance_id %s could not be found as device id on"
                   " any ports" % instance['uuid'])
            self.raise_not_found(msg)

        for port in ports:
            if not self._has_security_group_requirements(port):
                LOG.warn(_("Cannot add security group %(name)s to %(instance)s"
                           " since the port %(port_id)s does not meet security"
                           " requirements"), {'name': security_group_name,
                         'instance': instance['uuid'], 'port_id': port['id']})
                raise exception.SecurityGroupCannotBeApplied()
            if 'security_groups' not in port:
                port['security_groups'] = []
            port['security_groups'].append(security_group_id)
            updated_port = {'security_groups': port['security_groups']}
            try:
                LOG.info(_("Adding security group %(security_group_id)s to "
                           "port %(port_id)s"),
                         {'security_group_id': security_group_id,
                          'port_id': port['id']})
                neutron.update_port(port['id'], {'port': updated_port})
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_("Neutron Error:"))

    @wrap_check_security_groups_policy
    def remove_from_instance(self, context, instance, security_group_name):
        """Remove the security group associated with the instance."""
        neutron = neutronv2.get_client(context)
        try:
            security_group_id = neutronv20.find_resourceid_by_name_or_id(
                neutron, 'security_group', security_group_name)
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                msg = ("Security group %s is not found for project %s" %
                       (security_group_name, context.project_id))
                self.raise_not_found(msg)
            else:
                LOG.exception(_("Neutron Error:"))
                raise exc_info[0], exc_info[1], exc_info[2]
        params = {'device_id': instance['uuid']}
        try:
            ports = neutron.list_ports(**params).get('ports')
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Neutron Error:"))

        if not ports:
            msg = ("instance_id %s could not be found as device id on"
                   " any ports" % instance['uuid'])
            self.raise_not_found(msg)

        found_security_group = False
        for port in ports:
            try:
                port.get('security_groups', []).remove(security_group_id)
            except ValueError:
                # When removing a security group from an instance the security
                # group should be on both ports since it was added this way if
                # done through the nova api. In case it is not a 404 is only
                # raised if the security group is not found on any of the
                # ports on the instance.
                continue

            updated_port = {'security_groups': port['security_groups']}
            try:
                LOG.info(_("Adding security group %(security_group_id)s to "
                           "port %(port_id)s"),
                         {'security_group_id': security_group_id,
                          'port_id': port['id']})
                neutron.update_port(port['id'], {'port': updated_port})
                found_security_group = True
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_("Neutron Error:"))
        if not found_security_group:
            msg = (_("Security group %(security_group_name)s not assocaited "
                     "with the instance %(instance)s"),
                   {'security_group_name': security_group_name,
                    'instance': instance['uuid']})
            self.raise_not_found(msg)

    def populate_security_groups(self, instance, security_groups):
        # Setting to emply list since we do not want to populate this field
        # in the nova database if using the neutron driver
        instance['security_groups'] = security_group.SecurityGroupList()
        instance['security_groups'].objects = []
