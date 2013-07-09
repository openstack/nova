from nova.api.openstack import extensions


class Extended_services(extensions.ExtensionDescriptor):
    """Extended services support."""

    name = "ExtendedServices"
    alias = "os-extended-services"
    namespace = ("http://docs.openstack.org/compute/ext/"
                "extended_services/api/v2")
    updated = "2013-05-17T00:00:00-00:00"
