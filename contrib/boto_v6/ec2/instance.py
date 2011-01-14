'''
Created on 2010/12/20

@author: Nachi Ueno <ueno.nachi@lab.ntt.co.jp>
'''
import boto
from boto.resultset import ResultSet
from boto.ec2.instance import Reservation
from boto.ec2.instance import Group
from boto.ec2.instance import Instance


class ReservationV6(Reservation):
    def startElement(self, name, attrs, connection):
        if name == 'instancesSet':
            self.instances = ResultSet([('item', InstanceV6)])
            return self.instances
        elif name == 'groupSet':
            self.groups = ResultSet([('item', Group)])
            return self.groups
        else:
            return None


class InstanceV6(Instance):
    def __init__(self, connection=None):
        Instance.__init__(self, connection)
        self.dns_name_v6 = None

    def endElement(self, name, value, connection):
        Instance.endElement(self, name, value, connection)
        if name == 'dnsNameV6':
            self.dns_name_v6 = value

    def _update(self, updated):
        self.__dict__.update(updated.__dict__)
        self.dns_name_v6 = updated.dns_name_v6
