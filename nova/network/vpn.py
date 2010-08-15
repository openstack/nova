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

"""Network Data for projects"""

from nova import datastore
from nova import exception
from nova import flags
from nova import utils

FLAGS = flags.FLAGS


flags.DEFINE_string('vpn_ip', utils.get_my_ip(),
                    'Public IP for the cloudpipe VPN servers')
flags.DEFINE_integer('vpn_start_port', 1000,
                    'Start port for the cloudpipe VPN servers')
flags.DEFINE_integer('vpn_end_port', 2000,
                    'End port for the cloudpipe VPN servers')


class NoMorePorts(exception.Error):
    """No ports available to allocate for the given ip"""
    pass


class NetworkData():
    """Manages network host, and vpn ip and port for projects"""
    def __init__(self, project_id):
        self.project_id = project_id
        super(NetworkData, self).__init__()

    @property
    def identifier(self):
        """Identifier used for key in redis"""
        return self.project_id

    @classmethod
    def create(cls, project_id):
        """Creates a vpn for project

        This method finds a free ip and port and stores the associated
        values in the datastore.
        """
        # TODO(vish): will we ever need multiiple ips per host?
        port = cls.find_free_port_for_ip(FLAGS.vpn_ip)
        network_data = cls(project_id)
        # save ip for project
        network_data['host'] = FLAGS.node_name
        network_data['project'] = project_id
        network_data['ip'] = FLAGS.vpn_ip
        network_data['port'] = port
        network_data.save()
        return network_data

    @classmethod
    def find_free_port_for_ip(cls, vpn_ip):
        """Finds a free port for a given ip from the redis set"""
        # TODO(vish): these redis commands should be generalized and
        #             placed into a base class. Conceptually, it is
        #             similar to an association, but we are just
        #             storing a set of values instead of keys that
        #             should be turned into objects.
        cls._ensure_set_exists(vpn_ip)

        port = datastore.Redis.instance().spop(cls._redis_ports_key(vpn_ip))
        if not port:
            raise NoMorePorts()
        return port

    @classmethod
    def _redis_ports_key(cls, vpn_ip):
        """Key that ports are stored under in redis"""
        return 'ip:%s:ports' % vpn_ip

    @classmethod
    def _ensure_set_exists(cls, vpn_ip):
        """Creates the set of ports for the ip if it doesn't already exist"""
        # TODO(vish): these ports should be allocated through an admin
        #             command instead of a flag
        redis = datastore.Redis.instance()
        if (not redis.exists(cls._redis_ports_key(vpn_ip)) and
            not redis.exists(cls._redis_association_name('ip', vpn_ip))):
            for i in range(FLAGS.vpn_start_port, FLAGS.vpn_end_port + 1):
                redis.sadd(cls._redis_ports_key(vpn_ip), i)

    @classmethod
    def num_ports_for_ip(cls, vpn_ip):
        """Calculates the number of free ports for a given ip"""
        cls._ensure_set_exists(vpn_ip)
        return datastore.Redis.instance().scard('ip:%s:ports' % vpn_ip)

    @property
    def ip(self):  # pylint: disable=C0103
        """The ip assigned to the project"""
        return self['ip']

    @property
    def port(self):
        """The port assigned to the project"""
        return int(self['port'])

    def save(self):
        """Saves the association to the given ip"""
        self.associate_with('ip', self.ip)
        super(NetworkData, self).save()

    def destroy(self):
        """Cleans up datastore and adds port back to pool"""
        self.unassociate_with('ip', self.ip)
        datastore.Redis.instance().sadd('ip:%s:ports' % self.ip, self.port)
        super(NetworkData, self).destroy()
