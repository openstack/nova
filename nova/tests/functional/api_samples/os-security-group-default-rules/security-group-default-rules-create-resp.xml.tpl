<?xml version='1.0' encoding='UTF-8'?>
<security_group_default_rule xmlns="http://docs.openstack.org/compute/api/v1.1"  id="1">
  <ip_protocol>TCP</ip_protocol>
  <from_port>80</from_port>
  <to_port>80</to_port>
  <ip_range>
    <cidr>10.10.10.0/24</cidr>
  </ip_range>
</security_group_default_rule>