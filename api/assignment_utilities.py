import datetime
from business_duration import businessDuration
import holidays as pyholidays
import pandas as pd
import requests
import time

BEARER = ''
CONFIG = {'config': {"url": "http://config.int.janelia.org/"}}

def call_responder(server, endpoint, payload=''):
    ''' Call a responder
        Keyword arguments:
          server: server
          endpoint: REST endpoint
          payload: payload for POST requests
    '''
    if server not in CONFIG:
        raise Exception("Configuration key %s is not defined" % (server))
    url = CONFIG[server]['url'] + endpoint
    try:
        if payload:
            headers = {"Content-Type": "application/json",
                       "Authorization": "Bearer " + BEARER}
            req = requests.post(url, headers=headers, json=payload)
        else:
            req = requests.get(url)
    except requests.exceptions.RequestException as err:
        print(err)
        sys.exit(-1)
    if req.status_code == 200:
        return req.json()
    print("Could not get response from %s: %s" % (url, req.text))
    raise InvalidUsage(req.text, req.status_code)


def working_duration(start_unix, end_unix):
    open_time = datetime.time(6, 0, 0)
    close_time = datetime.time(18, 0, 0)
    holidaylist = pyholidays.US()
    startstring = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_unix))
    endstring = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_unix))
    startdate = pd.to_datetime(startstring)
    enddate = pd.to_datetime(endstring)
    working_duration = businessDuration(startdate,enddate,open_time,close_time,
                                        holidaylist=holidaylist,unit='hour') * 3600
    try:
        working_duration = int(working_duration)
    except ValueError as err:
        print(str(err) + ' for ' + startstring + ', ' + endstring)
        working_duration = duration
    return working_duration
