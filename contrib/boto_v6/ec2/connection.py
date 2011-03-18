'''
Created on 2010/12/20

@author: Nachi Ueno <ueno.nachi@lab.ntt.co.jp>
'''
import boto
import base64
import boto.ec2
from boto_v6.ec2.instance import  ReservationV6
from boto.ec2.securitygroup import SecurityGroup


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
        return self.get_list('DescribeInstancesV6', params,
                             [('item', ReservationV6)])

    def run_instances(self, image_id, min_count=1, max_count=1,
                      key_name=None, security_groups=None,
                      user_data=None, addressing_type=None,
                      instance_type='m1.small', placement=None,
                      kernel_id=None, ramdisk_id=None,
                      monitoring_enabled=False, subnet_id=None,
                      block_device_map=None):
        """
        Runs an image on EC2.

        :type image_id: string
        :param image_id: The ID of the image to run

        :type min_count: int
        :param min_count: The minimum number of instances to launch

        :type max_count: int
        :param max_count: The maximum number of instances to launch

        :type key_name: string
        :param key_name: The name of the key pair with which to
                         launch instances

        :type security_groups: list of strings
        :param security_groups: The names of the security groups with
                                which to associate instances

        :type user_data: string
        :param user_data: The user data passed to the launched instances

        :type instance_type: string
        :param instance_type: The type of instance to run
                              (m1.small, m1.large, m1.xlarge)

        :type placement: string
        :param placement: The availability zone in which to launch
                          the instances

        :type kernel_id: string
        :param kernel_id: The ID of the kernel with which to
                          launch the instances

        :type ramdisk_id: string
        :param ramdisk_id: The ID of the RAM disk with which to
                           launch the instances

        :type monitoring_enabled: bool
        :param monitoring_enabled: Enable CloudWatch monitoring
                                   on the instance.

        :type subnet_id: string
        :param subnet_id: The subnet ID within which to launch
                          the instances for VPC.

        :type block_device_map:
            :class:`boto.ec2.blockdevicemapping.BlockDeviceMapping`
        :param block_device_map: A BlockDeviceMapping data structure
                                 describing the EBS volumes associated
                                 with the Image.

        :rtype: Reservation
        :return: The :class:`boto.ec2.instance.ReservationV6`
                 associated with the request for machines
        """
        params = {'ImageId': image_id,
                  'MinCount': min_count,
                  'MaxCount': max_count}
        if key_name:
            params['KeyName'] = key_name
        if security_groups:
            l = []
            for group in security_groups:
                if isinstance(group, SecurityGroup):
                    l.append(group.name)
                else:
                    l.append(group)
            self.build_list_params(params, l, 'SecurityGroup')
        if user_data:
            params['UserData'] = base64.b64encode(user_data)
        if addressing_type:
            params['AddressingType'] = addressing_type
        if instance_type:
            params['InstanceType'] = instance_type
        if placement:
            params['Placement.AvailabilityZone'] = placement
        if kernel_id:
            params['KernelId'] = kernel_id
        if ramdisk_id:
            params['RamdiskId'] = ramdisk_id
        if monitoring_enabled:
            params['Monitoring.Enabled'] = 'true'
        if subnet_id:
            params['SubnetId'] = subnet_id
        if block_device_map:
            block_device_map.build_list_params(params)
        return self.get_object('RunInstances', params,
                               ReservationV6, verb='POST')
