{
    "server": {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "version": 4
                }
            ]
        },
        "adminPass": "%(password)s",
        "created": "%(isotime)s",
        "flavor": {
            "disk": 1,
            "ephemeral": 0,
            "extra_specs": {},
            "original_name": "m1.tiny",
            "ram": 512,
            "swap": 0,
            "vcpus": 1
        },
        "hostId": "%(hostid)s",
        "id": "%(uuid)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(compute_endpoint)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ]
        },
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "locked": false,
        "metadata": {
            "meta_var": "meta_val"
        },
        "name": "%(name)s",
        "key_name": "%(key_name)s",
        "description": "%(description)s",
        "progress": 0,
        "OS-DCF:diskConfig": "AUTO",
        "status": "ACTIVE",
        "tenant_id": "6f70656e737461636b20342065766572",
        "updated": "%(isotime)s",
        "user_id": "admin",
        "tags": [],
        "user_data": "ZWNobyAiaGVsbG8gd29ybGQi"
    }
}
