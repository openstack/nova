{
    "server" : {
        "OS-DCF:diskConfig": "AUTO",
        "name" : "new-server-test",
        "imageRef" : "%(host)s/images/%(image_id)s",
        "flavorRef" : "%(host)s/flavors/1",
        "metadata" : {
            "My Server Name" : "Apache1"
        }
    }
}
