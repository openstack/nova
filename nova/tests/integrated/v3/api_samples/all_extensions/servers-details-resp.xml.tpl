<?xml version='1.0' encoding='UTF-8'?>
<servers xmlns:os-extended-volumes="http://docs.openstack.org/compute/ext/extended_volumes/api/v3" xmlns:os-extended-availability-zone="http://docs.openstack.org/compute/ext/extended_availability_zone/api/v3" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:os-extended-status="http://docs.openstack.org/compute/ext/extended_status/api/v3" xmlns:os-config-drive="http://docs.openstack.org/compute/ext/config_drive/api/v3" xmlns:os-extended-server-attributes="http://docs.openstack.org/compute/ext/extended_server_attributes/api/v3" xmlns:os-disk-config="http://docs.openstack.org/compute/ext/disk_config/api/v3" xmlns:os-server-usage="http://docs.openstack.org/compute/ext/os-server-usage/api/v3" xmlns="http://docs.openstack.org/compute/api/v1.1">
  <server status="ACTIVE" updated="%(timestamp)s" user_id="fake" name="new-server-test" created="%(timestamp)s" tenant_id="openstack" access_ip_v4="" progress="0" host_id="%(hostid)s" id="%(id)s" access_ip_v6="" os-config-drive:config_drive="" os-server-usage:launched_at="%(timestamp)s" os-server-usage:terminated_at="None" os-extended-status:vm_state="active" os-extended-status:locked_by="None" os-extended-status:power_state="1" os-extended-status:task_state="None" os-disk-config:disk_config="AUTO" os-extended-availability-zone:availability_zone="nova" os-extended-server-attributes:hypervisor_hostname="%(hypervisor_hostname)s" os-extended-server-attributes:instance_name="instance-00000001" os-extended-server-attributes:host="%(compute_host)s" key_name="None">
    <image id="%(uuid)s">
      <atom:link href="%(glance_host)s/images/%(uuid)s" rel="bookmark"/>
    </image>
    <flavor id="1">
      <atom:link href="%(host)s/flavors/1" rel="bookmark"/>
    </flavor>
    <metadata>
      <meta key="My Server Name">Apache1</meta>
    </metadata>
    <addresses>
      <network id="private">
        <ip version="4" type="fixed" addr="%(ip)s" mac_addr="aa:bb:cc:dd:ee:ff"/>
      </network>
    </addresses>
    <atom:link href="%(host)s/v3/servers/%(uuid)s" rel="self"/>
    <atom:link href="%(host)s/servers/%(uuid)s" rel="bookmark"/>
    <security_groups>
      <security_group name="default"/>
    </security_groups>
  </server>
</servers>
