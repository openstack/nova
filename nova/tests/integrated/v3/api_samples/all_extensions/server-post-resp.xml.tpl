<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:os-disk-config="http://docs.openstack.org/compute/ext/disk_config/api/v3" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" id="%(id)s" admin_pass="%(password)s" os-disk-config:disk_config="AUTO">
  <metadata/>
  <atom:link href="%(host)s/v3/servers/%(uuid)s" rel="self"/>
  <atom:link href="%(host)s/servers/%(uuid)s" rel="bookmark"/>
  <security_groups>
    <security_group name="default"/>
  </security_groups>
</server>
