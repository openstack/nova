{
    "server" : {
        "name" : "new-server-test",
        "imageRef" : "%(glance_host)s/images/%(image_id)s",
        "flavorRef" : "%(host)s/flavors/1",
        "metadata" : {
            "My Server Name" : "Apache1"
        }
    }
}
