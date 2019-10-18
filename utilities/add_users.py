import requests

USERS = {"alvaradoc": "alvaradocx4",
         "ballingers": "sam.ballinger96",
         "bergs": "stuarteberg",
         "ducloso": "octave2014",
         "eubanksb": "bryoneubanks11",
         "finleys": "sammie42finley",
         "forknalln": "nforknall",
         "francisa": "alfrancis1996",
         "katzw": "billkatz",
         "hornej": "janeannehorne",
         "hubbardp": "hubbardpneu",
         "hsuj": "jlhsu225",
         "joycee": "emily.m.joyce1",
         "knechtc": "cjk7067",
         "lauchies": "Slauchie",
         "manleye": "emanley8794",
         "neacee": "erika.neace",
         "ogundeyio": "omotaraogundeyi",
         "olbrisd": "olbris",
         "ordishc": "cordish25",
         "parekhr": "ruchi.janelia",
         "patersont": "paterson1391",
         "ribeiroc": "ribeirocaitlin",
         "rivlinp": "patrivlin",
         "sammonsm": "megansammons44",
         "scotta": "Scott.AshleyLauren",
         "scotta10": "anniekayscott",
         "shinomiyaa": "quatretribunal",
         "shinomiyak": "kshinomniya",
         "smithc": "csmith792",
         "smithn": "natalielynnsmith",
         "suleimana": "aliansuleiman95",
         "svirskasr": "robsvi",
         "takemurasa": "satn2030",
         "talebii": "lifesabeach0011",
         "tenshawe": "emilytenshaw",
         "tiscarenoc": "charli.tiscareno",
         "umayaml": "lumayam",
         "yangt": "tansygarvey",
         "zhaot": "tingzhao"
        }
BEARER = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InJvYnN2aUBnbWFpbC5jb20iLCJsZXZlbCI6Im5vYXV0aCIsImltYWdlLXVybCI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hLS9BQXVFN21CSW5mWGE2dVBuMnV5VG5vN3FBdThzdEZMMWtPdjR3Yk0zemJvWEpRP3N6PTUwIiwiZXhwIjoxNzQ3NjE5MDM3fQ.Ycu57B6qJKUtEiphhBf48AvfiWTnOFrmhLkRLeppP1c'

def call_responder(url, endpoint, payload=''):
    url += endpoint
    try:
        if payload:
            headers = {"Content-Type": "application/json",
                       "Authorization": "Bearer " + BEARER}
            req = requests.post(url, headers=headers, json=payload)
        else:
            req = requests.get(url)
    except requests.exceptions.RequestException as err:
        print(err)
        raise err
    if req.status_code == 200:
        return req.json()
    if 'is already' in req.text:
        print(req.json()['rest']['error'])
    else:
        print(req.text)


for user in USERS:
    payload = {"janelia_id": user,
               "name": USERS[user] + '@gmail.com'}
    response = call_responder('http://flyem-assignment.int.janelia.org/', 'adduser', payload)
