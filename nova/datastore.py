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
Datastore:

Providers the Keeper class, a simple pseudo-dictionary that
persists on disk.

MAKE Sure that ReDIS is running, and your flags are set properly,
before trying to run this.
"""

import json
import logging
import os
import sqlite3
import time

from nova import vendor
import redis

from nova import flags
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('datastore_path', utils.abspath('../keeper'),
                    'where keys are stored on disk')
flags.DEFINE_string('redis_host', '127.0.0.1',
                    'Host that redis is running on.')
flags.DEFINE_integer('redis_port', 6379,
                    'Port that redis is running on.')
flags.DEFINE_integer('redis_db', 0, 'Multiple DB keeps tests away')
flags.DEFINE_string('keeper_backend', 'redis',
                    'which backend to use for keeper')


class Redis(object):
    def __init__(self):
        if hasattr(self.__class__, '_instance'):
            raise Exception('Attempted to instantiate singleton')

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            inst = redis.Redis(host=FLAGS.redis_host, port=FLAGS.redis_port, db=FLAGS.redis_db)
            cls._instance = inst
        return cls._instance


class RedisModel(object):
    """ Wrapper around redis-backed properties """
    object_type = 'generic'
    def __init__(self, object_id):
        """ loads an object from the datastore if exists """
        self.object_id = object_id
        self.initial_state = {}
        self.state = Redis.instance().hgetall(self.__redis_key)
        if self.state:
            self.initial_state = self.state
        else:
            self.set_default_state()

    def set_default_state(self):
        self.state = {'state': 0,
                      'state_description': 'pending',
                      'node_name': 'unassigned',
                      'project_id': 'unassigned',
                      'user_id': 'unassigned'}
        self.state[self.object_type+"_id"] = self.object_id
        self.state["create_time"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    @property
    def project(self):
        if self.state.get('project_id', None):
            return self.state['project_id']
        return self.state.get('owner_id', 'unassigned')

    @property
    def __redis_key(self):
        """ Magic string for keys """
        return '%s:%s' % (self.object_type, self.object_id)

    def __repr__(self):
        return "<%s:%s>" % (self.object_type, self.object_id)

    def __str__(self):
        return str(self.state)

    def keys(self):
        return self.state.keys()

    def copy(self):
        copyDict = {}
        for item in self.keys():
            copyDict[item] = self[item]
        return copyDict

    def get(self, item, default):
        return self.state.get(item, default)

    def __getitem__(self, item):
        return self.state[item]

    def __setitem__(self, item, val):
        self.state[item] = val
        return self.state[item]

    def __delitem__(self, item):
        """ We don't support this """
        raise Exception("Silly monkey, we NEED all our properties.")

    def save(self):
        """ update the directory with the state from this instance """
        # TODO(ja): implement hmset in redis-py and use it
        # instead of multiple calls to hset
        for key, val in self.state.iteritems():
            # if (not self.initial_state.has_key(key)
            # or self.initial_state[key] != val):
                Redis.instance().hset(self.__redis_key, key, val)
        if self.initial_state == {}:
            self.first_save()
        self.initial_state = self.state
        return True

    def first_save(self):
        pass

    def destroy(self):
        """ deletes all related records from datastore.
         does NOT do anything to running state.
        """
        Redis.instance().delete(self.__redis_key)
        return True


def slugify(key, prefix=None):
    """
    Key has to be a valid filename. Slugify solves that.
    """
    return "%s%s" % (prefix, key)


class SqliteKeeper(object):
    """ Keeper implementation in SQLite, mostly for in-memory testing """
    _conn = {} # class variable

    def __init__(self, prefix):
        self.prefix = prefix

    @property
    def conn(self):
        if self.prefix not in self.__class__._conn:
            logging.debug('no sqlite connection (%s), making new', self.prefix)
            if FLAGS.datastore_path != ':memory:':
                try:
                    os.mkdir(FLAGS.datastore_path)
                except Exception:
                    pass
                conn = sqlite3.connect(os.path.join(
                    FLAGS.datastore_path, '%s.sqlite' % self.prefix))
            else:
                conn = sqlite3.connect(':memory:')

            c = conn.cursor()
            try:
                c.execute('''CREATE TABLE data (item text, value text)''')
                conn.commit()
            except Exception:
                logging.exception('create table failed')
            finally:
                c.close()

            self.__class__._conn[self.prefix] = conn

        return self.__class__._conn[self.prefix]

    def __delitem__(self, item):
        #logging.debug('sqlite deleting %s', item)
        c = self.conn.cursor()
        try:
            c.execute('DELETE FROM data WHERE item = ?', (item, ))
            self.conn.commit()
        except Exception:
            logging.exception('delete failed: %s', item)
        finally:
            c.close()

    def __getitem__(self, item):
        #logging.debug('sqlite getting %s', item)
        result = None
        c = self.conn.cursor()
        try:
            c.execute('SELECT value FROM data WHERE item = ?', (item, ))
            row = c.fetchone()
            if row:
                result = json.loads(row[0])
            else:
                result = None
        except Exception:
            logging.exception('select failed: %s', item)
        finally:
            c.close()
        #logging.debug('sqlite got %s: %s', item, result)
        return result

    def __setitem__(self, item, value):
        serialized_value = json.dumps(value)
        insert = True
        if self[item] is not None:
            insert = False
        #logging.debug('sqlite insert %s: %s', item, value)
        c = self.conn.cursor()
        try:
            if insert:
                c.execute('INSERT INTO data VALUES (?, ?)',
                         (item, serialized_value))
            else:
                c.execute('UPDATE data SET item=?, value=? WHERE item = ?',
                          (item, serialized_value, item))

            self.conn.commit()
        except Exception:
            logging.exception('select failed: %s', item)
        finally:
            c.close()

    def clear(self):
        if self.prefix not in self.__class__._conn:
            return
        self.conn.close()
        if FLAGS.datastore_path != ':memory:':
            os.unlink(os.path.join(FLAGS.datastore_path, '%s.sqlite' % self.prefix))
        del self.__class__._conn[self.prefix]

    def clear_all(self):
        for k, conn in self.__class__._conn.iteritems():
            conn.close()
            if FLAGS.datastore_path != ':memory:':
                os.unlink(os.path.join(FLAGS.datastore_path,
                                       '%s.sqlite' % self.prefix))
        self.__class__._conn = {}


    def set_add(self, item, value):
        group = self[item]
        if not group:
            group = []
        group.append(value)
        self[item] = group

    def set_is_member(self, item, value):
        group = self[item]
        if not group:
            return False
        return value in group

    def set_remove(self, item, value):
        group = self[item]
        if not group:
            group = []
        group.remove(value)
        self[item] = group

    def set_members(self, item):
        group = self[item]
        if not group:
            group = []
        return group

    def set_fetch(self, item):
        # TODO(termie): I don't really know what set_fetch is supposed to do
        group = self[item]
        if not group:
            group = []
        return iter(group)

class JsonKeeper(object):
    """
    Simple dictionary class that persists using
    JSON in files saved to disk.
    """
    def __init__(self, prefix):
        self.prefix = prefix

    def __delitem__(self, item):
        """
        Removing a key means deleting a file from disk.
        """
        item = slugify(item, self.prefix)
        path = "%s/%s" % (FLAGS.datastore_path, item)
        if os.path.isfile(path):
            os.remove(path)

    def __getitem__(self, item):
        """
        Fetch file contents and dejsonify them.
        """
        item = slugify(item, self.prefix)
        path = "%s/%s" % (FLAGS.datastore_path, item)
        if os.path.isfile(path):
            return json.load(open(path, 'r'))
        return None

    def __setitem__(self, item, value):
        """
        JSON encode value and save to file.
        """
        item = slugify(item, self.prefix)
        path = "%s/%s" % (FLAGS.datastore_path, item)
        with open(path, "w") as blobfile:
            blobfile.write(json.dumps(value))
        return value


class RedisKeeper(object):
    """
    Simple dictionary class that persists using
    ReDIS.
    """
    def __init__(self, prefix="redis-"):
        self.prefix = prefix
        #Redis.instance().ping()

    def __setitem__(self, item, value):
        """
        JSON encode value and save to file.
        """
        item = slugify(item, self.prefix)
        Redis.instance().set(item, json.dumps(value))
        return value

    def __getitem__(self, item):
        item = slugify(item, self.prefix)
        value = Redis.instance().get(item)
        if value:
            return json.loads(value)

    def __delitem__(self, item):
        item = slugify(item, self.prefix)
        return Redis.instance().delete(item)

    def clear(self):
        raise NotImplementedError()

    def clear_all(self):
        raise NotImplementedError()

    def set_add(self, item, value):
        item = slugify(item, self.prefix)
        return Redis.instance().sadd(item, json.dumps(value))

    def set_is_member(self, item, value):
        item = slugify(item, self.prefix)
        return Redis.instance().sismember(item, json.dumps(value))

    def set_remove(self, item, value):
        item = slugify(item, self.prefix)
        return Redis.instance().srem(item, json.dumps(value))

    def set_members(self, item):
        item = slugify(item, self.prefix)
        return [json.loads(v) for v in Redis.instance().smembers(item)]

    def set_fetch(self, item):
        item = slugify(item, self.prefix)
        for obj in  Redis.instance().sinter([item]):
            yield json.loads(obj)


def Keeper(prefix=''):
    KEEPERS = {'redis': RedisKeeper,
               'sqlite': SqliteKeeper}
    return KEEPERS[FLAGS.keeper_backend](prefix)

