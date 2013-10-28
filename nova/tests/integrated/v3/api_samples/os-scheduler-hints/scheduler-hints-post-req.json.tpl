{
    "server" : {
        "name" : "new-server-test",
        "image_ref" : "%(glance_host)s/openstack/images/%(image_id)s",
        "flavor_ref" : "%(host)s/openstack/flavors/1",
        "os-scheduler-hints:scheduler_hints": {
            "hypervisor": "xen",
            "near": "%(image_near)s"
        }
    }
}
