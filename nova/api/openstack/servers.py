# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import logging
import traceback

from webob import exc

from nova import exception
from nova import wsgi
from nova.api.openstack import common
from nova.api.openstack import faults
from nova.auth import manager as auth_manager
from nova.compute import api as compute_api
from nova.compute import instance_types
from nova.compute import power_state
import nova.api.openstack


LOG = logging.getLogger('server')
LOG.setLevel(logging.DEBUG)


def checks_lock(function):
    """
    decorator used for preventing action against locked instances
    unless, of course, you happen to be admin

    """

    @functools.wraps(function)
    def decorated_function(*args, **kwargs):

        # grab args to function
        try:
            if 'req' in kwargs:
                req = kwargs['req']
            else:
                req = args[1]
            if 'id' in kwargs:
                _id = kwargs['id']
            else:
                req = args[2]
            context = req.environ['nova.context']
        except:
            logging.error(_("CheckLock: argument error"))

        # if locked and admin call function, otherwise 404
        if(compute_api.ComputeAPI().get_lock(context, _id)):
            if(req.environ['nova.context'].is_admin):
                function(*args, **kwargs)
        # return 404
        return faults.Fault(exc.HTTPUnprocessableEntity())

    return decorated_function


def _entity_list(entities):
    """ Coerces a list of servers into proper dictionary format """
    return dict(servers=entities)


def _entity_detail(inst):
    """ Maps everything to Rackspace-like attributes for return"""
    power_mapping = {
        power_state.NOSTATE: 'build',
        power_state.RUNNING: 'active',
        power_state.BLOCKED: 'active',
        power_state.SUSPENDED: 'suspended',
        power_state.PAUSED: 'error',
        power_state.SHUTDOWN: 'active',
        power_state.SHUTOFF: 'active',
        power_state.CRASHED: 'error'}
    inst_dict = {}

    mapped_keys = dict(status='state', imageId='image_id',
        flavorId='instance_type', name='display_name', id='internal_id')

    for k, v in mapped_keys.iteritems():
        inst_dict[k] = inst[v]

    inst_dict['status'] = power_mapping[inst_dict['status']]
    inst_dict['addresses'] = dict(public=[], private=[])
    inst_dict['metadata'] = {}
    inst_dict['hostId'] = ''

    return dict(server=inst_dict)


def _entity_inst(inst):
    """ Filters all model attributes save for id and name """
    return dict(server=dict(id=inst['internal_id'], name=inst['display_name']))


class Controller(wsgi.Controller):
    """ The Server API controller for the OpenStack API """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "server": ["id", "imageId", "name", "flavorId", "hostId",
                           "status", "progress"]}}}

    def __init__(self):
        self.compute_api = compute_api.ComputeAPI()
        super(Controller, self).__init__()

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        return self._items(req, entity_maker=_entity_inst)

    def detail(self, req):
        """ Returns a list of server details for a given user """
        return self._items(req, entity_maker=_entity_detail)

    def _items(self, req, entity_maker):
        """Returns a list of servers for a given user.

        entity_maker - either _entity_detail or _entity_inst
        """
        instance_list = self.compute_api.get_instances(
            req.environ['nova.context'])
        limited_list = common.limited(instance_list, req)
        res = [entity_maker(inst)['server'] for inst in limited_list]
        return _entity_list(res)

    @checks_lock
    def show(self, req, id):
        """ Returns server details by server id """
        try:
            instance = self.compute_api.get_instance(
                req.environ['nova.context'], int(id))
            return _entity_detail(instance)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

    @checks_lock
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self.compute_api.delete_instance(req.environ['nova.context'],
                int(id))
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPAccepted()

    def create(self, req):
        """ Creates a new server for a given user """
        env = self._deserialize(req.body, req)
        if not env:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        key_pair = auth_manager.AuthManager.get_key_pairs(
            req.environ['nova.context'])[0]
        instances = self.compute_api.create_instances(
            req.environ['nova.context'],
            instance_types.get_by_flavor_id(env['server']['flavorId']),
            env['server']['imageId'],
            display_name=env['server']['name'],
            description=env['server']['name'],
            key_name=key_pair['name'],
            key_data=key_pair['public_key'])
        return _entity_inst(instances[0])

    @checks_lock
    def update(self, req, id):
        """ Updates the server name or password """
        inst_dict = self._deserialize(req.body, req)
        if not inst_dict:
            return faults.Fault(exc.HTTPUnprocessableEntity())

        update_dict = {}
        if 'adminPass' in inst_dict['server']:
            update_dict['admin_pass'] = inst_dict['server']['adminPass']
        if 'name' in inst_dict['server']:
            update_dict['display_name'] = inst_dict['server']['name']

        try:
            self.compute_api.update_instance(req.environ['nova.context'],
                                             instance['id'],
                                             **update_dict)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return exc.HTTPNoContent()

    @checks_lock
    def action(self, req, id):
        """ Multi-purpose method used to reboot, rebuild, and
        resize a server """
        input_dict = self._deserialize(req.body, req)
        try:
            reboot_type = input_dict['reboot']['type']
        except Exception:
            raise faults.Fault(exc.HTTPNotImplemented())
        try:
            # TODO(gundlach): pass reboot_type, support soft reboot in
            # virt driver
            self.compute_api.reboot(req.environ['nova.context'], id)
        except:
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def lock(self, req, id):
        """
        lock the instance with id
        admin only operation

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.lock(context, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("Compute.api::lock %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def unlock(self, req, id):
        """
        unlock the instance with id
        admin only operation

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.unlock(context, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("Compute.api::unlock %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    def get_lock(self, req, id):
        """
        return the boolean state of (instance with id)'s lock

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.get_lock(context, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("Compute.api::get_lock %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    @checks_lock
    def pause(self, req, id):
        """ Permit Admins to Pause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.pause(ctxt, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("Compute.api::pause %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    @checks_lock
    def unpause(self, req, id):
        """ Permit Admins to Unpause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.unpause(ctxt, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("Compute.api::unpause %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    @checks_lock
    def suspend(self, req, id):
        """permit admins to suspend the server"""
        context = req.environ['nova.context']
        try:
            self.compute_api.suspend(context, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("compute.api::suspend %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()

    @checks_lock
    def resume(self, req, id):
        """permit admins to resume the server from suspend"""
        context = req.environ['nova.context']
        try:
            self.compute_api.resume(context, id)
        except:
            readable = traceback.format_exc()
            logging.error(_("compute.api::resume %s"), readable)
            return faults.Fault(exc.HTTPUnprocessableEntity())
        return exc.HTTPAccepted()
