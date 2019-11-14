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

import sys

import netaddr
from neutronclient.common import exceptions as n_exc
from neutronclient.neutron import v2_0 as neutronv20
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import uuidutils
import six
from webob import exc

from nova import exception
from nova.i18n import _
from nova.network.neutronv2 import api as neutronapi
from nova.network.security_group import security_group_base
from nova import utils


LOG = logging.getLogger(__name__)

# NOTE: Neutron client has a max URL length of 8192, so we have
# to limit the number of IDs we include in any single search.  Really
# doesn't seem to be any point in making this a config value.
MAX_SEARCH_IDS = 150


class SecurityGroupAPI(security_group_base.SecurityGroupBase):

    id_is_uuid = True

    def create_security_group(self, context, name, description):
        neutron = neutronapi.get_client(context)
        body = self._make_neutron_security_group_dict(name, description)
        try:
            security_group = neutron.create_security_group(
                body).get('security_group')
        except n_exc.BadRequest as e:
            raise exception.Invalid(six.text_type(e))
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            LOG.exception("Neutron Error creating security group %s", name)
            if e.status_code == 401:
                # TODO(arosen) Cannot raise generic response from neutron here
                # as this error code could be related to bad input or over
                # quota
                raise exc.HTTPBadRequest()
            elif e.status_code == 409:
                self.raise_over_quota(six.text_type(e))
            six.reraise(*exc_info)
        return self._convert_to_nova_security_group_format(security_group)

    def update_security_group(self, context, security_group,
                              name, description):
        neutron = neutronapi.get_client(context)
        body = self._make_neutron_security_group_dict(name, description)
        try:
            security_group = neutron.update_security_group(
                security_group['id'], body).get('security_group')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            LOG.exception("Neutron Error updating security group %s", name)
            if e.status_code == 401:
                # TODO(arosen) Cannot raise generic response from neutron here
                # as this error code could be related to bad input or over
                # quota
                raise exc.HTTPBadRequest()
            six.reraise(*exc_info)
        return self._convert_to_nova_security_group_format(security_group)

    def validate_property(self, value, property, allowed):
        """Validate given security group property.

        :param value:    the value to validate, as a string or unicode
        :param property: the property, either 'name' or 'description'
        :param allowed:  the range of characters allowed, but not used because
                         Neutron is allowing any characters.
        """

        # NOTE: If using nova-network as the backend, min_length is 1. However
        # if using Neutron, Nova has allowed empty string as its history.
        # So this min_length should be 0 for passing the existing requests.
        utils.check_string_length(value, name=property, min_length=0,
                                  max_length=255)

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
            if rule['protocol'].upper() in ['TCP', 'UDP']:
                nova_rule['from_port'] = 1
                nova_rule['to_port'] = 65535
            else:
                nova_rule['from_port'] = -1
                nova_rule['to_port'] = -1
        else:
            nova_rule['from_port'] = rule.get('port_range_min')
            nova_rule['to_port'] = rule.get('port_range_max')
        nova_rule['group_id'] = rule['remote_group_id']
        nova_rule['cidr'] = self.parse_cidr(rule.get('remote_ip_prefix'))
        return nova_rule

    def get(self, context, name=None, id=None, map_exception=False):
        neutron = neutronapi.get_client(context)
        try:
            if not id and name:
                # NOTE(flwang): The project id should be honoured so as to get
                # the correct security group id when user(with admin role but
                # non-admin project) try to query by name, so as to avoid
                # getting more than duplicated records with the same name.
                id = neutronv20.find_resourceid_by_name_or_id(
                    neutron, 'security_group', name, context.project_id)
            group = neutron.show_security_group(id).get('security_group')
            return self._convert_to_nova_security_group_format(group)
        except n_exc.NeutronClientNoUniqueMatch as e:
            raise exception.NoUniqueMatch(six.text_type(e))
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                LOG.debug("Neutron security group %s not found", name)
                raise exception.SecurityGroupNotFound(six.text_type(e))
            else:
                LOG.error("Neutron Error: %s", e)
                six.reraise(*exc_info)
        except TypeError as e:
            LOG.error("Neutron Error: %s", e)
            msg = _("Invalid security group name: %(name)s.") % {"name": name}
            raise exception.SecurityGroupNotFound(six.text_type(msg))

    def list(self, context, names=None, ids=None, project=None,
             search_opts=None):
        """Returns list of security group rules owned by tenant."""
        neutron = neutronapi.get_client(context)
        params = {}
        search_opts = search_opts if search_opts else {}
        if names:
            params['name'] = names
        if ids:
            params['id'] = ids

        # NOTE(jeffrey4l): list all the security groups when following
        # conditions are met
        #   * names and ids don't exist.
        #   * it is admin context and all_tenants exist in search_opts.
        #   * project is not specified.
        list_all_tenants = (context.is_admin and
                            'all_tenants' in search_opts and
                            not any([names, ids]))
        # NOTE(jeffrey4l): The neutron doesn't have `all-tenants` concept.
        # All the security group will be returned if the project/tenant
        # id is not passed.
        if project and not list_all_tenants:
            params['tenant_id'] = project
        try:
            security_groups = neutron.list_security_groups(**params).get(
                'security_groups')
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception("Neutron Error getting security groups")
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

        neutron = neutronapi.get_client(context)
        try:
            neutron.delete_security_group(security_group['id'])
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                self.raise_not_found(six.text_type(e))
            elif e.status_code == 409:
                self.raise_invalid_property(six.text_type(e))
            else:
                LOG.error("Neutron Error: %s", e)
                six.reraise(*exc_info)

    def add_rules(self, context, id, name, vals):
        """Add security group rule(s) to security group.

        Note: the Nova security group API doesn't support adding multiple
        security group rules at once but the EC2 one does. Therefore,
        this function is written to support both. Multiple rules are
        installed to a security group in neutron using bulk support.
        """

        neutron = neutronapi.get_client(context)
        body = self._make_neutron_security_group_rules_list(vals)
        try:
            rules = neutron.create_security_group_rule(
                body).get('security_group_rules')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                LOG.exception("Neutron Error getting security group %s", name)
                self.raise_not_found(six.text_type(e))
            elif e.status_code == 409:
                LOG.exception("Neutron Error adding rules to security "
                              "group %s", name)
                self.raise_over_quota(six.text_type(e))
            elif e.status_code == 400:
                LOG.exception("Neutron Error: %s", e)
                self.raise_invalid_property(six.text_type(e))
            else:
                six.reraise(*exc_info)
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
                version = netaddr.IPNetwork(rule.get('cidr')).version
                new_rule['ethertype'] = 'IPv6' if version == 6 else 'IPv4'
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
        neutron = neutronapi.get_client(context)
        rule_ids = set(rule_ids)
        try:
            # The ec2 api allows one to delete multiple security group rules
            # at once. Since there is no bulk delete for neutron the best
            # thing we can do is delete the rules one by one and hope this
            # works.... :/
            for rule_id in range(0, len(rule_ids)):
                neutron.delete_security_group_rule(rule_ids.pop())
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception("Neutron Error unable to delete %s", rule_ids)

    def get_rule(self, context, id):
        neutron = neutronapi.get_client(context)
        try:
            rule = neutron.show_security_group_rule(
                id).get('security_group_rule')
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                LOG.debug("Neutron security group rule %s not found", id)
                self.raise_not_found(six.text_type(e))
            else:
                LOG.error("Neutron Error: %s", e)
                six.reraise(*exc_info)
        return self._convert_to_nova_security_group_rule_format(rule)

    def _get_ports_from_server_list(self, servers, neutron):
        """Returns a list of ports used by the servers."""

        def _chunk_by_ids(servers, limit):
            ids = []
            for server in servers:
                ids.append(server['id'])
                if len(ids) >= limit:
                    yield ids
                    ids = []
            if ids:
                yield ids

        # Note: Have to split the query up as the search criteria
        # form part of the URL, which has a fixed max size
        ports = []
        for ids in _chunk_by_ids(servers, MAX_SEARCH_IDS):
            search_opts = {'device_id': ids}
            try:
                ports.extend(neutron.list_ports(**search_opts).get('ports'))
            except n_exc.PortNotFoundClient:
                # There could be a race between deleting an instance and
                # retrieving its port groups from Neutron. In this case
                # PortNotFoundClient is raised and it can be safely ignored
                LOG.debug("Port not found for device with id %s", ids)

        return ports

    def _get_secgroups_from_port_list(self, ports, neutron, fields=None):
        """Returns a dict of security groups keyed by their ids."""

        def _chunk_by_ids(sg_ids, limit):
            sg_id_list = []
            for sg_id in sg_ids:
                sg_id_list.append(sg_id)
                if len(sg_id_list) >= limit:
                    yield sg_id_list
                    sg_id_list = []
            if sg_id_list:
                yield sg_id_list

        # Find the set of unique SecGroup IDs to search for
        sg_ids = set()
        for port in ports:
            sg_ids.update(port.get('security_groups', []))

        # Note: Have to split the query up as the search criteria
        # form part of the URL, which has a fixed max size
        security_groups = {}
        for sg_id_list in _chunk_by_ids(sg_ids, MAX_SEARCH_IDS):
            sg_search_opts = {'id': sg_id_list}
            if fields:
                sg_search_opts['fields'] = fields
            search_results = neutron.list_security_groups(**sg_search_opts)
            for sg in search_results.get('security_groups'):
                security_groups[sg['id']] = sg

        return security_groups

    def get_instances_security_groups_bindings(self, context, servers,
                                               detailed=False):
        """Returns a dict(instance_id, [security_groups]) to allow obtaining
        all of the instances and their security groups in one shot.
        If detailed is False only the security group name is returned.
        """

        neutron = neutronapi.get_client(context)

        ports = self._get_ports_from_server_list(servers, neutron)

        # If detailed is True, we want all fields from the security groups
        # including the potentially slow-to-join security_group_rules field.
        # But if detailed is False, only get the id and name fields since
        # that's all we'll use below.
        fields = None if detailed else ['id', 'name']
        security_groups = self._get_secgroups_from_port_list(
            ports, neutron, fields=fields)

        instances_security_group_bindings = {}
        for port in ports:
            for port_sg_id in port.get('security_groups', []):

                # Note:  have to check we found port_sg as its possible
                # the port has an SG that this user doesn't have access to
                port_sg = security_groups.get(port_sg_id)
                if port_sg:
                    if detailed:
                        sg_entry = self._convert_to_nova_security_group_format(
                                 port_sg)
                        instances_security_group_bindings.setdefault(
                            port['device_id'], []).append(sg_entry)
                    else:
                        # name is optional in neutron so if not specified
                        # return id
                        name = port_sg.get('name')
                        if not name:
                            name = port_sg.get('id')
                        sg_entry = {'name': name}
                        instances_security_group_bindings.setdefault(
                            port['device_id'], []).append(sg_entry)

        return instances_security_group_bindings

    def get_instance_security_groups(self, context, instance, detailed=False):
        """Returns the security groups that are associated with an instance.
        If detailed is True then it also returns the full details of the
        security groups associated with an instance, otherwise just the
        security group name.
        """
        servers = [{'id': instance.uuid}]
        sg_bindings = self.get_instances_security_groups_bindings(
                                  context, servers, detailed)
        return sg_bindings.get(instance.uuid, [])

    def _has_security_group_requirements(self, port):
        port_security_enabled = port.get('port_security_enabled', True)
        has_ip = port.get('fixed_ips')
        deferred_ip = port.get('ip_allocation') == 'deferred'
        if has_ip or deferred_ip:
            return port_security_enabled
        return False

    def add_to_instance(self, context, instance, security_group_name):
        """Add security group to the instance."""

        neutron = neutronapi.get_client(context)
        try:
            security_group_id = neutronv20.find_resourceid_by_name_or_id(
                neutron, 'security_group',
                security_group_name,
                context.project_id)
        except n_exc.NeutronClientNoUniqueMatch as e:
            raise exception.NoUniqueMatch(six.text_type(e))
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                msg = (_("Security group %(name)s is not found for "
                         "project %(project)s") %
                       {'name': security_group_name,
                        'project': context.project_id})
                self.raise_not_found(msg)
            else:
                six.reraise(*exc_info)
        params = {'device_id': instance.uuid}
        try:
            ports = neutron.list_ports(**params).get('ports')
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception("Neutron Error:")

        if not ports:
            msg = (_("instance_id %s could not be found as device id on"
                   " any ports") % instance.uuid)
            self.raise_not_found(msg)

        for port in ports:
            if not self._has_security_group_requirements(port):
                LOG.warning("Cannot add security group %(name)s to "
                            "%(instance)s since the port %(port_id)s "
                            "does not meet security requirements",
                            {'name': security_group_name,
                             'instance': instance.uuid,
                             'port_id': port['id']})
                raise exception.SecurityGroupCannotBeApplied()
            if 'security_groups' not in port:
                port['security_groups'] = []
            port['security_groups'].append(security_group_id)
            updated_port = {'security_groups': port['security_groups']}
            try:
                LOG.info("Adding security group %(security_group_id)s to "
                         "port %(port_id)s",
                         {'security_group_id': security_group_id,
                          'port_id': port['id']})
                neutron.update_port(port['id'], {'port': updated_port})
            except n_exc.NeutronClientException as e:
                exc_info = sys.exc_info()
                if e.status_code == 400:
                    raise exception.SecurityGroupCannotBeApplied(
                        six.text_type(e))
                else:
                    six.reraise(*exc_info)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Neutron Error:")

    def remove_from_instance(self, context, instance, security_group_name):
        """Remove the security group associated with the instance."""
        neutron = neutronapi.get_client(context)
        try:
            security_group_id = neutronv20.find_resourceid_by_name_or_id(
                neutron, 'security_group',
                security_group_name,
                context.project_id)
        except n_exc.NeutronClientException as e:
            exc_info = sys.exc_info()
            if e.status_code == 404:
                msg = (_("Security group %(name)s is not found for "
                         "project %(project)s") %
                       {'name': security_group_name,
                        'project': context.project_id})
                self.raise_not_found(msg)
            else:
                six.reraise(*exc_info)
        params = {'device_id': instance.uuid}
        try:
            ports = neutron.list_ports(**params).get('ports')
        except n_exc.NeutronClientException:
            with excutils.save_and_reraise_exception():
                LOG.exception("Neutron Error:")

        if not ports:
            msg = (_("instance_id %s could not be found as device id on"
                   " any ports") % instance.uuid)
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
                LOG.info("Removing security group %(security_group_id)s from "
                         "port %(port_id)s",
                         {'security_group_id': security_group_id,
                          'port_id': port['id']})
                neutron.update_port(port['id'], {'port': updated_port})
                found_security_group = True
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Neutron Error:")
        if not found_security_group:
            msg = (_("Security group %(security_group_name)s not associated "
                     "with the instance %(instance)s") %
                   {'security_group_name': security_group_name,
                    'instance': instance.uuid})
            self.raise_not_found(msg)

    def get_default_rule(self, context, id):
        msg = _("Network driver does not support this function.")
        raise exc.HTTPNotImplemented(explanation=msg)

    def get_all_default_rules(self, context):
        msg = _("Network driver does not support this function.")
        raise exc.HTTPNotImplemented(explanation=msg)

    def add_default_rules(self, context, vals):
        msg = _("Network driver does not support this function.")
        raise exc.HTTPNotImplemented(explanation=msg)

    def remove_default_rules(self, context, rule_ids):
        msg = _("Network driver does not support this function.")
        raise exc.HTTPNotImplemented(explanation=msg)

    def default_rule_exists(self, context, values):
        msg = _("Network driver does not support this function.")
        raise exc.HTTPNotImplemented(explanation=msg)
