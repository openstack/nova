{
    "flavor": {
        "OS-FLV-DISABLED:disabled": false,
        "disk": 1,
        "id": "%(flavor_id)s",
        "links": [
            {
                "href": "%(host)s/v2/openstack/flavors/%(flavor_id)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/openstack/flavors/%(flavor_id)s",
                "rel": "bookmark"
            }
        ],
        "name": "m1.tiny",
        "ram": 512,
        "vcpus": 1
    }
}
