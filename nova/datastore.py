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

MAKE Sure that ReDIS is running, and your flags are set properly,
before trying to run this.
"""

from nova import vendor
import redis

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

