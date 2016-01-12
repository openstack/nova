# Copyright (c) 2012 Citrix Systems, Inc.
# Copyright 2010 OpenStack Foundation
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
Management class for Pool-related functions (join, eject, etc).
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six
import six.moves.urllib.parse as urlparse

from nova.compute import rpcapi as compute_rpcapi
from nova import exception
from nova.i18n import _, _LE
from nova.virt.xenapi import pool_states
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)

xenapi_pool_opts = [
    cfg.BoolOpt('use_join_force',
                default=True,
                help='To use for hosts with different CPUs'),
    ]

CONF = cfg.CONF
CONF.register_opts(xenapi_pool_opts, 'xenserver')
CONF.import_opt('host', 'nova.netconf')


class ResourcePool(object):
    """Implements resource pool operations."""
    def __init__(self, session, virtapi):
        host_rec = session.host.get_record(session.host_ref)
        self._host_name = host_rec['hostname']
        self._host_addr = host_rec['address']
        self._host_uuid = host_rec['uuid']
        self._session = session
        self._virtapi = virtapi
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()

    def undo_aggregate_operation(self, context, op, aggregate,
                                  host, set_error):
        """Undo aggregate operation when pool error raised."""
        try:
            if set_error:
                metadata = {pool_states.KEY: pool_states.ERROR}
                aggregate.update_metadata(metadata)
            op(host)
        except Exception:
            LOG.exception(_LE('Aggregate %(aggregate_id)s: unrecoverable '
                              'state during operation on %(host)s'),
                          {'aggregate_id': aggregate.id, 'host': host})

    def add_to_aggregate(self, context, aggregate, host, slave_info=None):
        """Add a compute host to an aggregate."""
        if not pool_states.is_hv_pool(aggregate.metadata):
            return

        invalid = {pool_states.CHANGING: _('setup in progress'),
                   pool_states.DISMISSED: _('aggregate deleted'),
                   pool_states.ERROR: _('aggregate in error')}

        if (aggregate.metadata[pool_states.KEY] in invalid.keys()):
            raise exception.InvalidAggregateActionAdd(
                    aggregate_id=aggregate.id,
                    reason=invalid[aggregate.metadata[pool_states.KEY]])

        if (aggregate.metadata[pool_states.KEY] == pool_states.CREATED):
            aggregate.update_metadata({pool_states.KEY: pool_states.CHANGING})
        if len(aggregate.hosts) == 1:
            # this is the first host of the pool -> make it master
            self._init_pool(aggregate.id, aggregate.name)
            # save metadata so that we can find the master again
            metadata = {'master_compute': host,
                        host: self._host_uuid,
                        pool_states.KEY: pool_states.ACTIVE}
            aggregate.update_metadata(metadata)
        else:
            # the pool is already up and running, we need to figure out
            # whether we can serve the request from this host or not.
            master_compute = aggregate.metadata['master_compute']
            if master_compute == CONF.host and master_compute != host:
                # this is the master ->  do a pool-join
                # To this aim, nova compute on the slave has to go down.
                # NOTE: it is assumed that ONLY nova compute is running now
                self._join_slave(aggregate.id, host,
                                 slave_info.get('compute_uuid'),
                                 slave_info.get('url'), slave_info.get('user'),
                                 slave_info.get('passwd'))
                metadata = {host: slave_info.get('xenhost_uuid'), }
                aggregate.update_metadata(metadata)
            elif master_compute and master_compute != host:
                # send rpc cast to master, asking to add the following
                # host with specified credentials.
                slave_info = self._create_slave_info()

                self.compute_rpcapi.add_aggregate_host(
                    context, aggregate, host, master_compute, slave_info)

    def remove_from_aggregate(self, context, aggregate, host, slave_info=None):
        """Remove a compute host from an aggregate."""
        slave_info = slave_info or dict()
        if not pool_states.is_hv_pool(aggregate.metadata):
            return

        invalid = {pool_states.CREATED: _('no hosts to remove'),
                   pool_states.CHANGING: _('setup in progress'),
                   pool_states.DISMISSED: _('aggregate deleted')}
        if aggregate.metadata[pool_states.KEY] in invalid.keys():
            raise exception.InvalidAggregateActionDelete(
                    aggregate_id=aggregate.id,
                    reason=invalid[aggregate.metadata[pool_states.KEY]])

        master_compute = aggregate.metadata['master_compute']
        if master_compute == CONF.host and master_compute != host:
            # this is the master -> instruct it to eject a host from the pool
            host_uuid = aggregate.metadata[host]
            self._eject_slave(aggregate.id,
                              slave_info.get('compute_uuid'), host_uuid)
            aggregate.update_metadata({host: None})
        elif master_compute == host:
            # Remove master from its own pool -> destroy pool only if the
            # master is on its own, otherwise raise fault. Destroying a
            # pool made only by master is fictional
            if len(aggregate.hosts) > 1:
                # NOTE: this could be avoided by doing a master
                # re-election, but this is simpler for now.
                raise exception.InvalidAggregateActionDelete(
                                    aggregate_id=aggregate.id,
                                    reason=_('Unable to eject %s '
                                             'from the pool; pool not empty')
                                             % host)
            self._clear_pool(aggregate.id)
            aggregate.update_metadata({'master_compute': None, host: None})
        elif master_compute and master_compute != host:
            # A master exists -> forward pool-eject request to master
            slave_info = self._create_slave_info()

            self.compute_rpcapi.remove_aggregate_host(
                context, aggregate.id, host, master_compute, slave_info)
        else:
            # this shouldn't have happened
            raise exception.AggregateError(aggregate_id=aggregate.id,
                                           action='remove_from_aggregate',
                                           reason=_('Unable to eject %s '
                                           'from the pool; No master found')
                                           % host)

    def _join_slave(self, aggregate_id, host, compute_uuid, url, user, passwd):
        """Joins a slave into a XenServer resource pool."""
        try:
            args = {'compute_uuid': compute_uuid,
                    'url': url,
                    'user': user,
                    'password': passwd,
                    'force': jsonutils.dumps(CONF.xenserver.use_join_force),
                    'master_addr': self._host_addr,
                    'master_user': CONF.xenserver.connection_username,
                    'master_pass': CONF.xenserver.connection_password, }
            self._session.call_plugin('xenhost', 'host_join', args)
        except self._session.XenAPI.Failure as e:
            LOG.error(_LE("Pool-Join failed: %s"), e)
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='add_to_aggregate',
                                           reason=_('Unable to join %s '
                                                  'in the pool') % host)

    def _eject_slave(self, aggregate_id, compute_uuid, host_uuid):
        """Eject a slave from a XenServer resource pool."""
        try:
            # shutdown nova-compute; if there are other VMs running, e.g.
            # guest instances, the eject will fail. That's a precaution
            # to deal with the fact that the admin should evacuate the host
            # first. The eject wipes out the host completely.
            vm_ref = self._session.VM.get_by_uuid(compute_uuid)
            self._session.VM.clean_shutdown(vm_ref)

            host_ref = self._session.host.get_by_uuid(host_uuid)
            self._session.pool.eject(host_ref)
        except self._session.XenAPI.Failure as e:
            LOG.error(_LE("Pool-eject failed: %s"), e)
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='remove_from_aggregate',
                                           reason=six.text_type(e.details))

    def _init_pool(self, aggregate_id, aggregate_name):
        """Set the name label of a XenServer pool."""
        try:
            pool_ref = self._session.pool.get_all()[0]
            self._session.pool.set_name_label(pool_ref, aggregate_name)
        except self._session.XenAPI.Failure as e:
            LOG.error(_LE("Unable to set up pool: %s."), e)
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='add_to_aggregate',
                                           reason=six.text_type(e.details))

    def _clear_pool(self, aggregate_id):
        """Clear the name label of a XenServer pool."""
        try:
            pool_ref = self._session.pool.get_all()[0]
            self._session.pool.set_name_label(pool_ref, '')
        except self._session.XenAPI.Failure as e:
            LOG.error(_LE("Pool-set_name_label failed: %s"), e)
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='remove_from_aggregate',
                                           reason=six.text_type(e.details))

    def _create_slave_info(self):
        """XenServer specific info needed to join the hypervisor pool."""
        # replace the address from the xenapi connection url
        # because this might be 169.254.0.1, i.e. xenapi
        # NOTE: password in clear is not great, but it'll do for now
        sender_url = swap_xapi_host(
            CONF.xenserver.connection_url, self._host_addr)

        return {
            "url": sender_url,
            "user": CONF.xenserver.connection_username,
            "passwd": CONF.xenserver.connection_password,
            "compute_uuid": vm_utils.get_this_vm_uuid(None),
            "xenhost_uuid": self._host_uuid,
        }


def swap_xapi_host(url, host_addr):
    """Replace the XenServer address present in 'url' with 'host_addr'."""
    temp_url = urlparse.urlparse(url)
    return url.replace(temp_url.hostname, '%s' % host_addr)
