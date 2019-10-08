{
    "server": {
        "OS-DCF:diskConfig": "AUTO",
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "addresses": {
            "private": [
                {
                    "addr": "192.168.1.30",
                    "version": 4
                }
            ]
        },
        "created": "%(isotime)s",
        "description": "Sample description",
        "flavor": {
            "disk": 1,
            "ephemeral": 0,
            "extra_specs": {
                "hw:numa_nodes": "1"
            },
            "original_name": "m1.tiny.specs",
            "ram": 512,
            "swap": 0,
            "vcpus": 1
        },
        "hostId": "%(hostid)s",
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
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(id)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(id)s",
                "rel": "bookmark"
            }
        ],
        "locked": false,
        "metadata": {
            "My Server Name": "Apache1"
        },
        "name": "new-server-test",
        "progress": 0,
        "status": "ACTIVE",
        "tags": [],
        "tenant_id": "6f70656e737461636b20342065766572",
        "trusted_image_certificates": [
                "0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8",
                "674736e3-f25c-405c-8362-bbf991e0ce0a"
        ],
        "updated": "%(isotime)s",
        "user_id": "fake"
    }
}
