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

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import quota
from nova import rpc
from nova.db import base

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.network')


class API(base.Base):
    """API for interacting with the network manager."""

    def allocate_floating_ip(self, context):
        if quota.allowed_floating_ips(context, 1) < 1:
            LOG.warn(_("Quota exceeeded for %s, tried to allocate "
                           "address"),
                         context.project_id)
            raise quota.QuotaError(_("Address quota exceeded. You cannot "
                                     "allocate any more addresses"))
        # NOTE(vish): We don't know which network host should get the ip
        #             when we allocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        return rpc.call(context,
                        FLAGS.network_topic,
                        {"method": "allocate_floating_ip",
                         "args": {"project_id": context.project_id}})

    def release_floating_ip(self, context, address):
        floating_ip = self.db.floating_ip_get_by_address(context, address)
        # NOTE(vish): We don't know which network host should get the ip
        #             when we deallocate, so just send it to any one.  This
        #             will probably need to move into a network supervisor
        #             at some point.
        rpc.cast(context,
                 FLAGS.network_topic,
                 {"method": "deallocate_floating_ip",
                  "args": {"floating_address": floating_ip['address']}})

    def associate_floating_ip(self, context, floating_ip, fixed_ip):
        """rpc.casts to network associate_floating_ip

        fixed_ip is either a fixed_ip object or a string fixed ip address
        floating_ip is a string floating ip address
        """
        if isinstance(fixed_ip, basestring):
            fixed_ip = self.db.fixed_ip_get_by_address(context, fixed_ip)
        floating_ip = self.db.floating_ip_get_by_address(context, floating_ip)
        # Check if the floating ip address is allocated
        if floating_ip['project_id'] is None:
            raise exception.ApiError(_("Address (%s) is not allocated") %
                                       floating_ip['address'])
        # Check if the floating ip address is allocated to the same project
        if floating_ip['project_id'] != context.project_id:
            LOG.warn(_("Address (%(address)s) is not allocated to your "
                       "project (%(project)s)"),
                       {'address': floating_ip['address'],
                       'project': context.project_id})
            raise exception.ApiError(_("Address (%(address)s) is not "
                                       "allocated to your project"
                                       "(%(project)s)") %
                                        {'address': floating_ip['address'],
                                        'project': context.project_id})
        # NOTE(vish): Perhaps we should just pass this on to compute and
        #             let compute communicate with network.
        host = fixed_ip['network']['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.network_topic, host),
                 {"method": "associate_floating_ip",
                  "args": {"floating_address": floating_ip['address'],
                           "fixed_address": fixed_ip['address']}})

    def disassociate_floating_ip(self, context, address):
        floating_ip = self.db.floating_ip_get_by_address(context, address)
        if not floating_ip.get('fixed_ip'):
            raise exception.ApiError('Address is not associated.')
        host = floating_ip['host']
        rpc.call(context,
                 self.db.queue_get_for(context, FLAGS.network_topic, host),
                 {"method": "disassociate_floating_ip",
                  "args": {"floating_address": floating_ip['address']}})

    def allocate_for_instance(self, context, instance, **kwargs):
        """rpc.calls network manager allocate_for_instance
        handles args and return value serialization
        """
        args = kwargs
        args['instance_id'] = instance['id']
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'allocate_for_instance',
                         'args': args})

    def deallocate_for_instance(self, context, instance, **kwargs):
        """rpc.casts network manager allocate_for_instance
        handles argument serialization
        """
        args = kwargs
        args['instance_id'] = instance['id']
        rpc.cast(context, FLAGS.network_topic,
                 {'method': 'deallocate_for_instance',
                  'args': args})

    def get_instance_nw_info(self, context, instance):
        """rpc.calls network manager get_instance_nw_info
        handles the args and return value serialization
        """
        args = {'instance_id': instance['id'],
                'instance_type_id': instance['instance_type_id']}
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'get_instance_nw_info',
                         'args': args})
