{
    "image": {
        "created": "2011-01-01T01:02:03Z",
        "id": "%(image_id)s",
        "links": [
            {
                "href": "%(host)s/v3/images/%(image_id)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/images/%(image_id)s",
                "rel": "bookmark"
            },
            {
                "href": "%(glance_host)s/images/%(image_id)s",
                "rel": "alternate",
                "type": "application/vnd.openstack.image"
            }
        ],
        "metadata": {
            "architecture": "x86_64",
            "auto_disk_config": "True",
            "kernel_id": "nokernel",
            "ramdisk_id": "nokernel"
        },
        "minDisk": 0,
        "minRam": 0,
        "name": "fakeimage7",
        "OS-EXT-IMG-SIZE:size": %(int)s,
        "progress": 100,
        "status": "ACTIVE",
        "updated": "2011-01-01T01:02:03Z"
    }
}
