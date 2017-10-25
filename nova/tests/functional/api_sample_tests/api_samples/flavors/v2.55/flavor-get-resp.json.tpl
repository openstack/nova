{
    "flavor": {
        "OS-FLV-DISABLED:disabled": false,
        "disk": 20,
        "OS-FLV-EXT-DATA:ephemeral": 0,
        "id": "%(flavorid)s",
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/flavors/%(flavorid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/flavors/%(flavorid)s",
                "rel": "bookmark"
            }
        ],
        "name": "m1.small.description",
        "os-flavor-access:is_public": true,
        "ram": 2048,
        "swap": "",
        "vcpus": 1,
        "rxtx_factor": 1.0,
        "description": "test description"
    }
}
