# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
Datastore Model objects for Compute Instances, with
InstanceDirectory manager.

# Create a new instance?
>>> InstDir = InstanceDirectory()
>>> inst = InstDir.new()
>>> inst.destroy()
True
>>> inst = InstDir['i-123']
>>> inst['ip'] = "192.168.0.3"
>>> inst['project_id'] = "projectA"
>>> inst.save()
True

>>> InstDir['i-123']
<Instance:i-123>
>>> InstDir.all.next()
<Instance:i-123>

>>> inst.destroy()
True
"""

import logging
import time

from nova import vendor
import redis

from nova import datastore
from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS


class ConnectionError(exception.Error):
    pass


def absorb_connection_error(fn):
    def _wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except redis.exceptions.ConnectionError, ce:
            raise ConnectionError(str(ce))
    return _wrapper


# TODO(todd): Implement this at the class level for Instance
class InstanceDirectory(object):
    """an api for interacting with the global state of instances"""

    def get(self, instance_id):
        """returns an instance object for a given id"""
        return Instance(instance_id)

    def __getitem__(self, item):
        return self.get(item)

    @absorb_connection_error
    def by_project(self, project):
        """returns a list of instance objects for a project"""
        for instance_id in datastore.Redis.instance().smembers('project:%s:instances' % project):
            yield Instance(instance_id)

    def by_node(self, node_id):
        """returns a list of instances for a node"""

        for instance in self.all:
            if instance['node_name'] == node_id:
                yield instance

    def by_ip(self, ip_address):
        """returns an instance object that is using the IP"""
        for instance in self.all:
            if instance['private_dns_name'] == ip_address:
                return instance
        return None

    def by_volume(self, volume_id):
        """returns the instance a volume is attached to"""
        pass

    @absorb_connection_error
    def exists(self, instance_id):
        return datastore.Redis.instance().sismember('instances', instance_id)

    @property
    @absorb_connection_error
    def all(self):
        """returns a list of all instances"""
        for instance_id in datastore.Redis.instance().smembers('instances'):
            yield Instance(instance_id)

    def new(self):
        """returns an empty Instance object, with ID"""
        instance_id = utils.generate_uid('i')
        return self.get(instance_id)

class BasicModel(object):
    """
    All Redis-backed data derives from this class.

    You MUST specify an identifier() property that returns a unique string
    per instance.

    You MUST have an initializer that takes a single argument that is a value
    returned by identifier() to load a new class with.

    You may want to specify a dictionary for default_state().

    You may also specify override_type at the class left to use a key other
    than __class__.__name__.

    You override save and destroy calls to automatically build and destroy
    associations.
    """

    override_type = None

    @absorb_connection_error
    def __init__(self):
        self.initial_state = {}
        self.state = datastore.Redis.instance().hgetall(self.__redis_key)
        if self.state:
            self.initial_state = self.state
        else:
            self.state = self.default_state()

    def default_state(self):
        """You probably want to define this in your subclass"""
        return {}

    @classmethod
    def _redis_name(cls):
        return self.override_type or cls.__name__

    @classmethod
    def lookup(cls, identifier):
        rv = cls(identifier)
        if rv.is_new_record():
            return None
        else:
            return rv

    @classmethod
    @absorb_connection_error
    def all(cls):
        """yields all objects in the store"""
        redis_set = cls._redis_set_name(cls.__name__)
        for identifier in datastore.Redis.instance().smembers(redis_set):
            yield cls(identifier)

    @classmethod
    @absorb_connection_error
    def associated_to(cls, foreign_type, foreign_id):
        redis_set = cls._redis_association_name(foreign_type, foreign_id)
        for identifier in datastore.Redis.instance().smembers(redis_set):
            yield cls(identifier)

    @classmethod
    def _redis_set_name(cls, kls_name):
        # stupidly pluralize (for compatiblity with previous codebase)
        return kls_name.lower() + "s"

    @classmethod
    def _redis_association_name(cls, foreign_type, foreign_id):
        return cls._redis_set_name("%s:%s:%s" % 
                                   (foreign_type, foreign_id, cls.__name__))

    @property
    def identifier(self):
        """You DEFINITELY want to define this in your subclass"""
        raise NotImplementedError("Your sublcass should define identifier")

    @property
    def __redis_key(self):
        return '%s:%s' % (self.__class__.__name__.lower(), self.identifier)

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__, self.identifier)

    def keys(self):
        return self.state.keys()

    def copy(self):
        copyDict = {}
        for item in self.keys():
            copyDict[item] = self[item]
        return copyDict

    def get(self, item, default):
        return self.state.get(item, default)

    def update(self, update_dict):
        return self.state.update(update_dict)

    def setdefault(self, item, default):
        return self.state.setdefault(item, default)

    def __getitem__(self, item):
        return self.state[item]

    def __setitem__(self, item, val):
        self.state[item] = val
        return self.state[item]

    def __delitem__(self, item):
        """We don't support this"""
        raise Exception("Silly monkey, models NEED all their properties.")

    def is_new_record(self):
        return self.initial_state == {}

    @absorb_connection_error
    def add_to_index(self):
        set_name = self.__class__._redis_set_name(self.__class__.__name__)
        datastore.Redis.instance().sadd(set_name, self.identifier)

    @absorb_connection_error
    def remove_from_index(self):
        set_name = self.__class__._redis_set_name(self.__class__.__name__)
        datastore.Redis.instance().srem(set_name, self.identifier)

    @absorb_connection_error
    def remove_from_index(self):
        set_name = self.__class__._redis_set_name(self.__class__.__name__)
        datastore.Redis.instance().srem(set_name, self.identifier)

    @absorb_connection_error
    def associate_with(self, foreign_type, foreign_id):
        # note the extra 's' on the end is for plurality
        # to match the old data without requiring a migration of any sort
        self.add_associated_model_to_its_set(foreign_type, foreign_id)
        redis_set = self.__class__._redis_association_name(foreign_type,
                                                           foreign_id)
        datastore.Redis.instance().sadd(redis_set, self.identifier)

    @absorb_connection_error
    def unassociate_with(self, foreign_type, foreign_id):
        redis_set = self.__class__._redis_association_name(foreign_type,
                                                           foreign_id)
        datastore.Redis.instance().srem(redis_set, self.identifier)

    def add_associated_model_to_its_set(self, my_type, my_id):
        table = globals()
        klsname = my_type.capitalize()
        if table.has_key(klsname):
            my_class = table[klsname]
            my_inst = my_class(my_id)
            my_inst.save()
        else:
            logging.warning("no model class for %s when building"
                            " association from %s",
                            klsname, self)

    @absorb_connection_error
    def save(self):
        """
        update the directory with the state from this model
        also add it to the index of items of the same type
        then set the initial_state = state so new changes are tracked
        """
        # TODO(ja): implement hmset in redis-py and use it
        # instead of multiple calls to hset
        if self.is_new_record():
            self["create_time"] = utils.isotime()
        for key, val in self.state.iteritems():
            # if (not self.initial_state.has_key(key)
            # or self.initial_state[key] != val):
                datastore.Redis.instance().hset(self.__redis_key, key, val)
        self.add_to_index()
        self.initial_state = self.state
        return True

    @absorb_connection_error
    def destroy(self):
        """
        deletes all related records from datastore.
        does NOT do anything to running libvirt state.
        """
        logging.info("Destroying datamodel for %s %s",
                     self.__class__.__name__, self.identifier)
        datastore.Redis.instance().delete(self.__redis_key)
        self.remove_from_index()
        return True


class Instance(BasicModel):
    """Wrapper around stored properties of an instance"""

    def __init__(self, instance_id):
        """loads an instance from the datastore if exists"""
        # set instance data before super call since it uses default_state
        self.instance_id = instance_id
        super(Instance, self).__init__()

    def default_state(self):
        return {'state': 0,
                'state_description': 'pending',
                'instance_id': self.instance_id,
                'node_name': 'unassigned',
                'project_id': 'unassigned',
                'user_id': 'unassigned'}

    @property
    def identifier(self):
        return self.instance_id

    @property
    def project(self):
        if self.state.get('project_id', None):
            return self.state['project_id']
        return self.state.get('owner_id', 'unassigned')

    @property
    def volumes(self):
        """returns a list of attached volumes"""
        pass

    @property
    def reservation(self):
        """Returns a reservation object"""
        pass

    def save(self):
        """Call into superclass to save object, then save associations"""
        # NOTE(todd): doesn't track migration between projects/nodes,
        #             it just adds the first one
        should_update_project = self.is_new_record()
        should_update_node = self.is_new_record()
        success = super(Instance, self).save()
        if success and should_update_project:
            self.associate_with("project", self.project)
        if success and should_update_node:
            self.associate_with("node", self['node_name'])
        return True

    def destroy(self):
        """Destroy associations, then destroy the object"""
        self.unassociate_with("project", self.project)
        return super(Instance, self).destroy()

class Host(BasicModel):
    """A Host is the machine where a Daemon is running."""

    def __init__(self, hostname):
        """loads an instance from the datastore if exists"""
        # set instance data before super call since it uses default_state
        self.hostname = hostname
        super(Host, self).__init__()

    def default_state(self):
        return {"hostname": self.hostname}

    @property
    def identifier(self):
        return self.hostname


class Daemon(BasicModel):
    """A Daemon is a job (compute, api, network, ...) that runs on a host."""

    def __init__(self, host_or_combined, binpath=None):
        """loads an instance from the datastore if exists"""
        # set instance data before super call since it uses default_state
        # since loading from datastore expects a combined key that
        # is equivilent to identifier, we need to expect that, while
        # maintaining meaningful semantics (2 arguments) when creating
        # from within other code like the bin/nova-* scripts
        if binpath:
            self.hostname = host_or_combined
            self.binary = binpath
        else:
            self.hostname, self.binary = host_or_combined.split(":")
        super(Daemon, self).__init__()

    def default_state(self):
        return {"hostname": self.hostname,
                "binary": self.binary,
                "updated_at": utils.isotime()
                }

    @property
    def identifier(self):
        return "%s:%s" % (self.hostname, self.binary)

    def save(self):
        """Call into superclass to save object, then save associations"""
        # NOTE(todd): this makes no attempt to destroy itsself,
        #             so after termination a record w/ old timestmap remains
        success = super(Daemon, self).save()
        if success:
            self.associate_with("host", self.hostname)
        return True

    def destroy(self):
        """Destroy associations, then destroy the object"""
        self.unassociate_with("host", self.hostname)
        return super(Daemon, self).destroy()

    def heartbeat(self):
        self['updated_at'] = utils.isotime()
        self.save()
        return True

    @classmethod
    def by_host(cls, hostname):
        for x in cls.associated_to("host", hostname):
            yield x

if __name__ == "__main__":
    import doctest
    doctest.testmod()
