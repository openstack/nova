{
    "flavor": {
        "disk": 1,
        "id": "%(flavor_id)s",
        "links": [
            {
                "href": "%(host)s/v3/flavors/%(flavor_id)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/flavors/%(flavor_id)s",
                "rel": "bookmark"
            }
        ],
        "name": "m1.tiny",
        "flavor-access:is_public": true,
        "ram": 512,
        "vcpus": 1,
        "disabled": false,
        "ephemeral": 0,
        "swap": 0
    }
}
