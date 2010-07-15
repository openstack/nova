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
Datastore:

MAKE Sure that ReDIS is running, and your flags are set properly,
before trying to run this.
"""

import logging

from nova import vendor
import redis

from nova import exception
from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('redis_host', '127.0.0.1',
                    'Host that redis is running on.')
flags.DEFINE_integer('redis_port', 6379,
                    'Port that redis is running on.')
flags.DEFINE_integer('redis_db', 0, 'Multiple DB keeps tests away')


class Redis(object):
    def __init__(self):
        if hasattr(self.__class__, '_instance'):
            raise Exception('Attempted to instantiate singleton')

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            inst = redis.Redis(host=FLAGS.redis_host,
                               port=FLAGS.redis_port,
                               db=FLAGS.redis_db)
            cls._instance = inst
        return cls._instance


class ConnectionError(exception.Error):
    pass


def absorb_connection_error(fn):
    def _wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except redis.exceptions.ConnectionError, ce:
            raise ConnectionError(str(ce))
    return _wrapper


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
        self.state = Redis.instance().hgetall(self.__redis_key)
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
        for identifier in Redis.instance().smembers(redis_set):
            yield cls(identifier)

    @classmethod
    @absorb_connection_error
    def associated_to(cls, foreign_type, foreign_id):
        redis_set = cls._redis_association_name(foreign_type, foreign_id)
        for identifier in Redis.instance().smembers(redis_set):
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
        raise NotImplementedError("Your subclass should define identifier")

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
        Redis.instance().sadd(set_name, self.identifier)

    @absorb_connection_error
    def remove_from_index(self):
        set_name = self.__class__._redis_set_name(self.__class__.__name__)
        Redis.instance().srem(set_name, self.identifier)

    @absorb_connection_error
    def remove_from_index(self):
        set_name = self.__class__._redis_set_name(self.__class__.__name__)
        Redis.instance().srem(set_name, self.identifier)

    @absorb_connection_error
    def associate_with(self, foreign_type, foreign_id):
        # note the extra 's' on the end is for plurality
        # to match the old data without requiring a migration of any sort
        self.add_associated_model_to_its_set(foreign_type, foreign_id)
        redis_set = self.__class__._redis_association_name(foreign_type,
                                                           foreign_id)
        Redis.instance().sadd(redis_set, self.identifier)

    @absorb_connection_error
    def unassociate_with(self, foreign_type, foreign_id):
        redis_set = self.__class__._redis_association_name(foreign_type,
                                                           foreign_id)
        Redis.instance().srem(redis_set, self.identifier)

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
            Redis.instance().hset(self.__redis_key, key, val)
        self.add_to_index()
        self.initial_state = self.state
        return True

    @absorb_connection_error
    def destroy(self):
        """deletes all related records from datastore."""
        logging.info("Destroying datamodel for %s %s",
                     self.__class__.__name__, self.identifier)
        Redis.instance().delete(self.__redis_key)
        self.remove_from_index()
        return True

