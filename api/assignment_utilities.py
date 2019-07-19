import datetime
import sys
import time
from business_duration import businessDuration
from flask import g
import holidays as pyholidays
import pandas as pd
import requests

BEARER = ''
CONFIG = {'config': {"url": "http://config.int.janelia.org/"}}
KEY_TYPE_IDS = dict()

# *****************************************************************************
# * Classes                                                                   *
# *****************************************************************************
class InvalidUsage(Exception):
    ''' Return an error response
    '''
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        ''' Build error response
        '''
        retval = dict(self.payload or ())
        retval['rest'] = {'error': self.message}
        return retval


# *****************************************************************************
# * Functions                                                                 *
# *****************************************************************************
def get_assignment_by_id(aid):
    ''' Get an assignment by ID
        Keyword arguments:
          aid: assignment ID
    '''
    try:
        g.c.execute("SELECT * FROM assignment_vw WHERE id=%s", (aid))
        assignment = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return assignment


def get_task_by_id(tid):
    ''' Get a task by ID
        Keyword arguments:
          tid: task ID
    '''
    try:
        g.c.execute("SELECT * FROM task_vw WHERE id=%s", (tid))
        task = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return task


def get_key_type_id(key_type):
    ''' Determthe ID for a key type
        Keyword arguments:
          key_type: key type
    '''
    if key_type not in KEY_TYPE_IDS:
        try:
            g.c.execute("SELECT id,cv_term FROM cv_term_vw WHERE cv='key'")
            cv_terms = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        for term in cv_terms:
            KEY_TYPE_IDS[term['cv_term']] = term['id']
    return KEY_TYPE_IDS[key_type]


def sql_error(err):
    ''' given a MySQL error, return the error message
        Keyword arguments:
          err: MySQL error
    '''
    error_msg = ''
    try:
        error_msg = "MySQL error [%d]: %s" % (err.args[0], err.args[1])
    except IndexError:
        error_msg = "Error: %s" % err
    if error_msg:
        print(error_msg)
    return error_msg


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
    work_duration = businessDuration(startdate, enddate, open_time, close_time,
                                     holidaylist=holidaylist, unit='hour') * 3600
    try:
        work_duration = int(work_duration)
    except ValueError as err:
        print(str(err) + ' for ' + startstring + ', ' + endstring)
        work_duration = end_unix - start_unix
    return work_duration
