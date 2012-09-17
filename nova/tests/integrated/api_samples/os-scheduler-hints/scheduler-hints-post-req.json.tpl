{
    "server": {
        "name": "new-server-test",
        "imageRef": "%(image_id)s",
        "flavorRef": "1"
    },
    "os:scheduler_hints": {
        "hypervisor": "xen",
        "near": "%(image_near)s"
    }
}
