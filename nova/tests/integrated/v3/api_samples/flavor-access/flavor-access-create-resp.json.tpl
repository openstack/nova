{
    "flavor": {
        "disk": 10,
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
        "name": "%(flavor_name)s",
        "flavor-access:is_public": false,
        "ram": 1024,
        "vcpus": 2,
        "disabled": false,
        "ephemeral": 0,
        "swap": 0
    }
}
