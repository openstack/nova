=================================
Using ports with resource request
=================================

Starting from microversion 2.72 nova supports creating servers with neutron
ports having resource request visible as a admin-only port attribute
``resource_request``. For example a neutron port has resource request if it has
a QoS minimum bandwidth rule attached. Deleting such servers or detaching such
ports works since Stein version of nova without requiring any specific
microversion.

However the following API operations are still not supported in nova:

* Creating servers with neutron networks having QoS minimum bandwidth rule is
  not supported. The user needs to pre-create the port in that neutron network
  and create the server with the pre-created port.

* Attaching Neutron ports and networks having QoS minimum bandwidth rule is not
  supported.

Also the following API operations are not supported in the 19.0.0 (Stein)
version of nova:

* Moving (resizing, migrating, live-migrating, evacuating, unshelving after
  shelve offload) servers with ports having resource request is not yet
  supported.

As of 20.0.0 (Train), nova supports cold migrating and resizing servers with
neutron ports having resource requests if both the source and destination
compute services are upgraded to 20.0.0 (Train) and the
``[upgrade_levels]/compute`` configuration does not prevent the computes from
using the latest RPC version. However cross cell resize and cross cell migrate
operations are still not supported with such ports and Nova will fall back to
same-cell resize if the server has such ports.

As of 21.0.0 (Ussuri), nova supports evacuating, live migrating and unshelving
servers with neutron ports having resource requests.

See :nova-doc:`the admin guide <admin/port_with_resource_request.html>` for
administrative details.
