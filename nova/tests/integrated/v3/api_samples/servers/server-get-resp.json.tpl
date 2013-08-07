{
    "server": {
        "access_ip_v4": "",
        "access_ip_v6": "",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "mac_addr": "aa:bb:cc:dd:ee:ff",
                    "type": "fixed",
                    "version": 4
                }
            ]
        },
        "created": "%(timestamp)s",
        "flavor": {
            "id": "1",
            "links": [
                {
                    "href": "%(host)s/flavors/1",
                    "rel": "bookmark"
                }
            ]
        },
        "host_id": "%(hostid)s",
        "id": "%(id)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(glance_host)s/images/%(uuid)s",
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
        "updated": "%(timestamp)s",
        "user_id": "fake"
    }
}
