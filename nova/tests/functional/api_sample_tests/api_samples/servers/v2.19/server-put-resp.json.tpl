{
    "server": {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "OS-DCF:diskConfig": "AUTO",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "version": 4
                }
            ]
        },
        "created": "%(isotime)s",
        "flavor": {
            "id": "1",
            "links": [
                {
                    "href": "%(compute_endpoint)s/flavors/1",
                    "rel": "bookmark"
                }
            ]
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
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "metadata": {
            "My Server Name": "Apache1"
        },
        "name": "updated-server-test",
        "description": "updated-server-description",
        "progress": 0,
        "status": "ACTIVE",
        "tenant_id": "6f70656e737461636b20342065766572",
        "updated": "%(isotime)s",
        "user_id": "fake",
        "locked": false
    }
}
