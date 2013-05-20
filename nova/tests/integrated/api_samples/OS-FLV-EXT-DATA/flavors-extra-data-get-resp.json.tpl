{
    "flavor": {
        "OS-FLV-EXT-DATA:ephemeral": 0,
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
        "name": "%(flavor_name)s",
        "ram": 512,
        "vcpus": 1
    }
}
