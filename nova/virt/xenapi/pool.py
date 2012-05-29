# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Citrix Systems, Inc.
# Copyright 2010 OpenStack LLC.
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

import json
import urlparse

from nova.compute import aggregate_states
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova import rpc
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)

xenapi_pool_opts = [
    cfg.BoolOpt('use_join_force',
                default=True,
                help='To use for hosts with different CPUs'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(xenapi_pool_opts)


class ResourcePool(object):
    """
    Implements resource pool operations.
    """
    def __init__(self, session):
        self.XenAPI = session.get_imported_xenapi()
        host_ref = session.get_xenapi_host()
        host_rec = session.call_xenapi('host.get_record', host_ref)
        self._host_name = host_rec['hostname']
        self._host_addr = host_rec['address']
        self._host_uuid = host_rec['uuid']
        self._session = session

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        """Add a compute host to an aggregate."""
        if len(aggregate.hosts) == 1:
            # this is the first host of the pool -> make it master
            self._init_pool(aggregate.id, aggregate.name)
            # save metadata so that we can find the master again
            values = {
                'operational_state': aggregate_states.ACTIVE,
                'metadata': {'master_compute': host,
                             host: self._host_uuid},
                }
            db.aggregate_update(context, aggregate.id, values)
        else:
            # the pool is already up and running, we need to figure out
            # whether we can serve the request from this host or not.
            master_compute = aggregate.metadetails['master_compute']
            if master_compute == FLAGS.host and master_compute != host:
                # this is the master ->  do a pool-join
                # To this aim, nova compute on the slave has to go down.
                # NOTE: it is assumed that ONLY nova compute is running now
                self._join_slave(aggregate.id, host,
                                 kwargs.get('compute_uuid'),
                                 kwargs.get('url'), kwargs.get('user'),
                                 kwargs.get('passwd'))
                metadata = {host: kwargs.get('xenhost_uuid'), }
                db.aggregate_metadata_add(context, aggregate.id, metadata)
            elif master_compute and master_compute != host:
                # send rpc cast to master, asking to add the following
                # host with specified credentials.
                forward_request(context, "add_aggregate_host", master_compute,
                                aggregate.id, host,
                                self._host_addr, self._host_uuid)

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        """Remove a compute host from an aggregate."""
        master_compute = aggregate.metadetails.get('master_compute')
        if master_compute == FLAGS.host and master_compute != host:
            # this is the master -> instruct it to eject a host from the pool
            host_uuid = db.aggregate_metadata_get(context, aggregate.id)[host]
            self._eject_slave(aggregate.id,
                              kwargs.get('compute_uuid'), host_uuid)
            db.aggregate_metadata_delete(context, aggregate.id, host)
        elif master_compute == host:
            # Remove master from its own pool -> destroy pool only if the
            # master is on its own, otherwise raise fault. Destroying a
            # pool made only by master is fictional
            if len(aggregate.hosts) > 1:
                # NOTE: this could be avoided by doing a master
                # re-election, but this is simpler for now.
                raise exception.InvalidAggregateAction(
                                    aggregate_id=aggregate.id,
                                    action='remove_from_aggregate',
                                    reason=_('Unable to eject %(host)s '
                                             'from the pool; pool not empty')
                                             % locals())
            self._clear_pool(aggregate.id)
            for key in ['master_compute', host]:
                db.aggregate_metadata_delete(context, aggregate.id, key)
        elif master_compute and master_compute != host:
            # A master exists -> forward pool-eject request to master
            forward_request(context, "remove_aggregate_host", master_compute,
                            aggregate.id, host,
                            self._host_addr, self._host_uuid)
        else:
            # this shouldn't have happened
            raise exception.AggregateError(aggregate_id=aggregate.id,
                                           action='remove_from_aggregate',
                                           reason=_('Unable to eject %(host)s '
                                           'from the pool; No master found')
                                           % locals())

    def _join_slave(self, aggregate_id, host, compute_uuid, url, user, passwd):
        """Joins a slave into a XenServer resource pool."""
        try:
            args = {'compute_uuid': compute_uuid,
                    'url': url,
                    'user': user,
                    'password': passwd,
                    'force': json.dumps(FLAGS.use_join_force),
                    'master_addr': self._host_addr,
                    'master_user': FLAGS.xenapi_connection_username,
                    'master_pass': FLAGS.xenapi_connection_password, }
            self._session.call_plugin('xenhost', 'host_join', args)
        except self.XenAPI.Failure as e:
            LOG.error(_("Pool-Join failed: %(e)s") % locals())
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='add_to_aggregate',
                                           reason=_('Unable to join %(host)s '
                                                  'in the pool') % locals())

    def _eject_slave(self, aggregate_id, compute_uuid, host_uuid):
        """Eject a slave from a XenServer resource pool."""
        try:
            # shutdown nova-compute; if there are other VMs running, e.g.
            # guest instances, the eject will fail. That's a precaution
            # to deal with the fact that the admin should evacuate the host
            # first. The eject wipes out the host completely.
            vm_ref = self._session.call_xenapi('VM.get_by_uuid', compute_uuid)
            self._session.call_xenapi("VM.clean_shutdown", vm_ref)

            host_ref = self._session.call_xenapi('host.get_by_uuid', host_uuid)
            self._session.call_xenapi("pool.eject", host_ref)
        except self.XenAPI.Failure as e:
            LOG.error(_("Pool-eject failed: %(e)s") % locals())
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='remove_from_aggregate',
                                           reason=str(e.details))

    def _init_pool(self, aggregate_id, aggregate_name):
        """Set the name label of a XenServer pool."""
        try:
            pool_ref = self._session.call_xenapi("pool.get_all")[0]
            self._session.call_xenapi("pool.set_name_label",
                                      pool_ref, aggregate_name)
        except self.XenAPI.Failure as e:
            LOG.error(_("Unable to set up pool: %(e)s.") % locals())
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='add_to_aggregate',
                                           reason=str(e.details))

    def _clear_pool(self, aggregate_id):
        """Clear the name label of a XenServer pool."""
        try:
            pool_ref = self._session.call_xenapi('pool.get_all')[0]
            self._session.call_xenapi('pool.set_name_label', pool_ref, '')
        except self.XenAPI.Failure as e:
            LOG.error(_("Pool-set_name_label failed: %(e)s") % locals())
            raise exception.AggregateError(aggregate_id=aggregate_id,
                                           action='remove_from_aggregate',
                                           reason=str(e.details))


def forward_request(context, request_type, master, aggregate_id,
                    slave_compute, slave_address, slave_uuid):
    """Casts add/remove requests to the pool master."""
    # replace the address from the xenapi connection url
    # because this might be 169.254.0.1, i.e. xenapi
    # NOTE: password in clear is not great, but it'll do for now
    sender_url = swap_xapi_host(FLAGS.xenapi_connection_url, slave_address)
    rpc.cast(context, rpc.queue_get_for(context, FLAGS.compute_topic, master),
             {"method": request_type,
              "args": {"aggregate_id": aggregate_id,
                       "host": slave_compute,
                       "url": sender_url,
                       "user": FLAGS.xenapi_connection_username,
                       "passwd": FLAGS.xenapi_connection_password,
                       "compute_uuid": vm_utils.get_this_vm_uuid(),
                       "xenhost_uuid": slave_uuid, },
             })


def swap_xapi_host(url, host_addr):
    """Replace the XenServer address present in 'url' with 'host_addr'."""
    temp_url = urlparse.urlparse(url)
    _netloc, sep, port = temp_url.netloc.partition(':')
    return url.replace(temp_url.netloc, '%s%s%s' % (host_addr, sep, port))
