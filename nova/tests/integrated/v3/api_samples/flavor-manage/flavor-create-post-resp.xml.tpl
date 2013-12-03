<?xml version='1.0' encoding='UTF-8'?>
<flavor xmlns:flavor-access="http://docs.openstack.org/compute/core/flavor-access/api/v3" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" disk="10" vcpus="2" ram="1024" name="%(flavor_name)s" id="%(flavor_id)s" disabled="False" ephemeral="0" swap="0" flavor-access:is_public="True">
  <atom:link href="%(host)s/v3/flavors/%(flavor_id)s" rel="self"/>
  <atom:link href="%(host)s/flavors/%(flavor_id)s" rel="bookmark"/>
</flavor>
