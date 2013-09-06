{
    "servers": [
    {
            "updated": "%(timestamp)s",
            "created": "%(timestamp)s",
            "access_ip_v4": "",
            "access_ip_v6": "",
            "addresses": {
                "private": [
                    {
                        "addr": "%(ip)s",
                        "version": 4,
                        "mac_addr": "aa:bb:cc:dd:ee:ff",
                        "type": "fixed"
                    }
                ]
            },
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
            "id": "%(uuid)s",
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
                    "href": "%(host)s/v3/servers/%(id)s",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/servers/%(id)s",
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
            "user_id": "fake",
            "security_groups": [{"name": "test"}],
            "key_name": null
    }]
}
