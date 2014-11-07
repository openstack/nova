<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:OS-DCF="http://docs.openstack.org/compute/ext/disk_config/api/v1.1" xmlns:OS-EXT-AZ="http://docs.openstack.org/compute/ext/extended_availability_zone/api/v2" xmlns:OS-EXT-SRV-ATTR="http://docs.openstack.org/compute/ext/extended_status/api/v1.1" xmlns:OS-EXT-IPS="http://docs.openstack.org/compute/ext/extended_ips/api/v1.1" xmlns:OS-EXT-IPS-MAC="http://docs.openstack.org/compute/ext/extended_ips_mac/api/v1.1" xmlns:OS-EXT-STS="http://docs.openstack.org/compute/ext/extended_status/api/v1.1" xmlns:os-extended-volumes="http://docs.openstack.org/compute/ext/extended_volumes/api/v1.1" xmlns:OS-SRV-USG="http://docs.openstack.org/compute/ext/server_usage/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="ACTIVE" updated="%(isotime)s" hostId="%(hostid)s" name="new-server-test" created="%(isotime)s" userId="fake" tenantId="openstack" accessIPv4="" accessIPv6="" progress="0" id="%(id)s" key_name="None" config_drive="" OS-EXT-SRV-ATTR:vm_state="active" OS-EXT-SRV-ATTR:task_state="None" OS-EXT-SRV-ATTR:power_state="1" OS-EXT-SRV-ATTR:instance_name="instance-00000001" OS-EXT-SRV-ATTR:host="%(compute_host)s" OS-EXT-SRV-ATTR:hypervisor_hostname="%(hypervisor_hostname)s" OS-EXT-AZ:availability_zone="nova" OS-DCF:diskConfig="AUTO" OS-SRV-USG:launched_at="%(xmltime)s" OS-SRV-USG:terminated_at="None">
  <image id="%(uuid)s">
    <atom:link href="%(host)s/openstack/images/%(uuid)s" rel="bookmark"/>
  </image>
  <flavor id="1">
    <atom:link href="%(host)s/openstack/flavors/1" rel="bookmark"/>
  </flavor>
  <metadata>
    <meta key="My Server Name">Apache1</meta>
  </metadata>
  <addresses>
    <network id="private">
      <ip OS-EXT-IPS:type="fixed" version="4" addr="%(ip)s"
          OS-EXT-IPS-MAC:mac_addr="%(mac_addr)s"/>
    </network>
  </addresses>
  <atom:link href="%(host)s/v2/openstack/servers/%(id)s" rel="self"/>
  <atom:link href="%(host)s/openstack/servers/%(id)s" rel="bookmark"/>
  <security_groups>
    <security_group name="default"/>
  </security_groups>
</server>
