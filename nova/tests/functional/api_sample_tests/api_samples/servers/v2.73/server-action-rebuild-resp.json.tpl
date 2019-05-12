{
    "server": {
        "OS-DCF:diskConfig": "AUTO",
        "accessIPv4": "1.2.3.4",
        "accessIPv6": "80fe::",
        "addresses": {
            "private": [
                {
                    "addr": "192.168.0.3",
                    "version": 4
                }
            ]
        },
        "adminPass": "seekr3t",
        "created": "%(isotime)s",
        "description": null,
        "flavor": {
            "disk": 1,
            "ephemeral": 0,
            "extra_specs": {},
            "original_name": "m1.tiny",
            "ram": 512,
            "swap": 0,
            "vcpus": 1
        },
        "hostId": "2091634baaccdc4c5a1d57069c833e402921df696b7f970791b12ec6",
        "id": "%(id)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(compute_endpoint)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ]
        },
        "key_name": null,
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(id)s",
                "rel": "bookmark"
            }
        ],
        "locked": false,
        "locked_reason": null,
        "metadata": {
            "meta_var": "meta_val"
        },
        "name": "foobar",
        "progress": 0,
        "server_groups": [],
        "status": "ACTIVE",
        "tags": [],
        "tenant_id": "6f70656e737461636b20342065766572",
        "trusted_image_certificates": null,
        "updated": "%(isotime)s",
        "user_data": "ZWNobyAiaGVsbG8gd29ybGQi",
        "user_id": "fake"
    }
}