'''
Created on 2010/12/20

@author: Nachi Ueno <ueno.nachi@lab.ntt.co.jp>
'''
from boto.ec2 import instance
from boto import resultset


class ReservationV6(instance.Reservation):
    def startElement(self, name, attrs, connection):
        if name == 'instancesSet':
            self.instances = resultset.ResultSet([('item', InstanceV6)])
            return self.instances
        elif name == 'groupSet':
            self.groups = resultset.ResultSet([('item', instance.Group)])
            return self.groups
        else:
            return None


class InstanceV6(instance.Instance):
    def __init__(self, connection=None):
        instance.Instance.__init__(self, connection)
        self.dns_name_v6 = None

    def endElement(self, name, value, connection):
        instance.Instance.endElement(self, name, value, connection)
        if name == 'dnsNameV6':
            self.dns_name_v6 = value

    def _update(self, updated):
        self.__dict__.update(updated.__dict__)
        self.dns_name_v6 = updated.dns_name_v6
