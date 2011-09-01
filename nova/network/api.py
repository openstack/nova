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

"""Handles all requests relating to instances (guest vms)."""

from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova.db import base


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.network')


class API(base.Base):
    """API for interacting with the network manager."""

    def get_floating_ip(self, context, id):
        rv = self.db.floating_ip_get(context, id)
        return dict(rv.iteritems())

    def get_floating_ip_by_ip(self, context, address):
        res = self.db.floating_ip_get_by_address(context, address)
        return dict(res.iteritems())

    def list_floating_ips(self, context):
        ips = self.db.floating_ip_get_all_by_project(context,
                                                     context.project_id)
        return ips

    def get_vifs_by_instance(self, context, instance_id):
        vifs = self.db.virtual_interface_get_by_instance(context, instance_id)
        return vifs

    def allocate_floating_ip(self, context):
        """Adds a floating ip to a project."""
        # NOTE(vish): We don't know which network host should get the ip
        #             when we allocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        return rpc.call(context,
                        FLAGS.network_topic,
                        {'method': 'allocate_floating_ip',
                         'args': {'project_id': context.project_id}})

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Removes floating ip with address from a project."""
        floating_ip = self.db.floating_ip_get_by_address(context, address)
        if floating_ip['fixed_ip']:
            raise exception.ApiError(_('Floating ip is in use.  '
                             'Disassociate it before releasing.'))
        if not affect_auto_assigned and floating_ip.get('auto_assigned'):
            return
        # NOTE(vish): We don't know which network host should get the ip
        #             when we deallocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        rpc.cast(context,
                 FLAGS.network_topic,
                 {'method': 'deallocate_floating_ip',
                  'args': {'floating_address': floating_ip['address']}})

    def associate_floating_ip(self, context, floating_ip, fixed_ip,
                                       affect_auto_assigned=False):
        """Associates a floating ip with a fixed ip.

        ensures floating ip is allocated to the project in context

        :param fixed_ip: is either fixed_ip object or a string fixed ip address
        :param floating_ip: is a string floating ip address
        """
        # NOTE(tr3buchet): i don't like the "either or" argument type
        # funcationility but i've left it alone for now
        # TODO(tr3buchet): this function needs to be rewritten to move
        # the network related db lookups into the network host code
        if isinstance(fixed_ip, basestring):
            fixed_ip = self.db.fixed_ip_get_by_address(context, fixed_ip)
        floating_ip = self.db.floating_ip_get_by_address(context, floating_ip)
        if not affect_auto_assigned and floating_ip.get('auto_assigned'):
            return
        # Check if the floating ip address is allocated
        if floating_ip['project_id'] is None:
            raise exception.ApiError(_('Address (%s) is not allocated') %
                                       floating_ip['address'])
        # Check if the floating ip address is allocated to the same project
        if floating_ip['project_id'] != context.project_id:
            LOG.warn(_('Address (%(address)s) is not allocated to your '
                       'project (%(project)s)'),
                       {'address': floating_ip['address'],
                       'project': context.project_id})
            raise exception.ApiError(_('Address (%(address)s) is not '
                                       'allocated to your project'
                                       '(%(project)s)') %
                                        {'address': floating_ip['address'],
                                        'project': context.project_id})

        # If this address has been previously associated to a
        # different instance, disassociate the floating_ip
        if floating_ip['fixed_ip'] and floating_ip['fixed_ip'] is not fixed_ip:
            self.disassociate_floating_ip(context, floating_ip['address'])

        # NOTE(vish): if we are multi_host, send to the instances host
        if fixed_ip['network']['multi_host']:
            host = fixed_ip['instance']['host']
        else:
            host = fixed_ip['network']['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.network_topic, host),
                 {'method': 'associate_floating_ip',
                  'args': {'floating_address': floating_ip['address'],
                           'fixed_address': fixed_ip['address']}})

    def disassociate_floating_ip(self, context, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating ip from fixed ip it is associated with."""
        floating_ip = self.db.floating_ip_get_by_address(context, address)
        if not affect_auto_assigned and floating_ip.get('auto_assigned'):
            return
        if not floating_ip.get('fixed_ip'):
            raise exception.ApiError('Address is not associated.')
        # NOTE(vish): if we are multi_host, send to the instances host
        if floating_ip['fixed_ip']['network']['multi_host']:
            host = floating_ip['fixed_ip']['instance']['host']
        else:
            host = floating_ip['fixed_ip']['network']['host']
        rpc.call(context,
                 self.db.queue_get_for(context, FLAGS.network_topic, host),
                 {'method': 'disassociate_floating_ip',
                  'args': {'floating_address': floating_ip['address']}})

    def allocate_for_instance(self, context, instance, **kwargs):
        """Allocates all network structures for an instance.

        :returns: network info as from get_instance_nw_info() below
        """
        args = kwargs
        args['instance_id'] = instance['id']
        args['project_id'] = instance['project_id']
        args['host'] = instance['host']
        args['instance_type_id'] = instance['instance_type_id']

        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'allocate_for_instance',
                         'args': args})

    def deallocate_for_instance(self, context, instance, **kwargs):
        """Deallocates all network structures related to instance."""
        args = kwargs
        args['instance_id'] = instance['id']
        args['project_id'] = instance['project_id']
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'deallocate_for_instance',
                  'args': args})

    def add_fixed_ip_to_instance(self, context, instance_id, host, network_id):
        """Adds a fixed ip to instance from specified network."""
        args = {'instance_id': instance_id,
                'host': host,
                'network_id': network_id}
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'add_fixed_ip_to_instance',
                  'args': args})

    def remove_fixed_ip_from_instance(self, context, instance_id, address):
        """Removes a fixed ip from instance from specified network."""
        args = {'instance_id': instance_id,
                'address': address}
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'remove_fixed_ip_from_instance',
                  'args': args})

    def add_network_to_project(self, context, project_id):
        """Force adds another network to a project."""
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'add_network_to_project',
                  'args': {'project_id': project_id}})

    def get_instance_nw_info(self, context, instance):
        """Returns all network info related to an instance."""
        args = {'instance_id': instance['id'],
                'instance_type_id': instance['instance_type_id'],
                'host': instance['host']}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'get_instance_nw_info',
                         'args': args})

    def validate_networks(self, context, requested_networks):
        """validate the networks passed at the time of creating
        the server
        """
        args = {'networks': requested_networks}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'validate_networks',
                         'args': args})
