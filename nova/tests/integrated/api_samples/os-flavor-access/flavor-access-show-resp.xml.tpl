<?xml version='1.0' encoding='UTF-8'?>
<flavor xmlns:os-flavor-access="http://docs.openstack.org/compute/ext/flavor_access/api/v2" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" disk="1" vcpus="1" ram="512" name="m1.tiny" id="%(flavor_id)s" os-flavor-access:is_public="True">
  <atom:link href="%(host)s/v2/openstack/flavors/%(flavor_id)s" rel="self"/>
  <atom:link href="%(host)s/openstack/flavors/%(flavor_id)s" rel="bookmark"/>
</flavor>
