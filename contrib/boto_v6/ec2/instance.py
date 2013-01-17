'''
Created on 2010/12/20

@author: Nachi Ueno <ueno.nachi@lab.ntt.co.jp>
'''
import boto.ec2.instance
from boto.resultset import ResultSet


class ReservationV6(boto.ec2.instance.Reservation):
    def startElement(self, name, attrs, connection):
        if name == 'instancesSet':
            self.instances = ResultSet([('item', InstanceV6)])
            return self.instances
        elif name == 'groupSet':
            self.groups = ResultSet([('item', boto.ec2.instance.Group)])
            return self.groups
        else:
            return None


class InstanceV6(boto.ec2.instance.Instance):
    def __init__(self, connection=None):
        boto.ec2.instance.Instance.__init__(self, connection)
        self.dns_name_v6 = None

    def endElement(self, name, value, connection):
        boto.ec2.instance.Instance.endElement(self, name, value, connection)
        if name == 'dnsNameV6':
            self.dns_name_v6 = value

    def _update(self, updated):
        self.__dict__.update(updated.__dict__)
        self.dns_name_v6 = updated.dns_name_v6
