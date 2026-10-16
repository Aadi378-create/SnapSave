import requests


def get_user_location(ip=None):

    try:

        if ip:
            url = f"https://ip-api.com/json/{ip}"
        else:
            url = "https://ip-api.com/json"

        r = requests.get(url,timeout=5)

        data = r.json()

        lat = data.get("lat")
        lon = data.get("lon")
        city = data.get("city")

        return lat, lon, city

    except:
        return None, None, None
