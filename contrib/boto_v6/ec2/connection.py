'''
Created on 2010/12/20

@author: Nachi Ueno <ueno.nachi@lab.ntt.co.jp>
'''
import boto
import boto.ec2
from boto_v6.ec2.instance import  ReservationV6


class EC2ConnectionV6(boto.ec2.EC2Connection):
    '''
    EC2Connection for OpenStack IPV6 mode
    '''
    def get_all_instances(self, instance_ids=None, filters=None):
        """
        Retrieve all the instances associated with your account.

        :type instance_ids: list
        :param instance_ids: A list of strings of instance IDs

        :type filters: dict
        :param filters: Optional filters that can be used to limit
                        the results returned.  Filters are provided
                        in the form of a dictionary consisting of
                        filter names as the key and filter values
                        as the value.  The set of allowable filter
                        names/values is dependent on the request
                        being performed.  Check the EC2 API guide
                        for details.

        :rtype: list
        :return: A list of  :class:`boto.ec2.instance.Reservation`
        """
        params = {}
        if instance_ids:
            self.build_list_params(params, instance_ids, 'InstanceId')
        if filters:
            self.build_filter_params(params, filters)
        return self.get_list('DescribeInstances', params,
                             [('item', ReservationV6)])
