<?xml version='1.0' encoding='UTF-8'?>
<flavor xmlns:OS-FLV-EXT-DATA="http://docs.openstack.org/compute/ext/flavor_extra_data/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" disk="1" vcpus="1" ram="512" name="%(flavor_name)s" id="%(flavor_id)s" OS-FLV-EXT-DATA:ephemeral="0">
  <atom:link href="%(host)s/v2/openstack/flavors/%(flavor_id)s" rel="self"/>
  <atom:link href="%(host)s/openstack/flavors/%(flavor_id)s" rel="bookmark"/>
</flavor>
