{
    "server": {
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
                    "OS-EXT-IPS:type": "fixed",
                    "version": 4
                }
            ]
        },
        "created": "%(isotime)s",
        "flavor": {
            "id": "1",
            "links": [
                {
                    "href": "%(host)s/flavors/1",
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
                    "href": "%(host)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ]
        },
        "links": [
            {
                "href": "%(host)s/v3/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "metadata": {
            "My Server Name": "Apache1"
        },
        "name": "new-server-test",
        "progress": 0,
        "status": "ACTIVE",
        "tenant_id": "openstack",
        "updated": "%(isotime)s",
        "user_id": "fake",
        "security_groups": [{"name": "test"}],
        "key_name": null
    }
}
