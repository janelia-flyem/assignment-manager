''' assignment_utilities.py
    Assignment manager utilities
'''

import datetime
import json
import random
import re
import string
import time
from urllib.parse import parse_qs
from flask import g
import requests
import holidays as pyholidays
import pandas as pd
from business_duration import businessDuration

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
def add_key_value_pair(key, val, separator, sql, bind):
    ''' Add a key/value pair to the WHERE clause of a SQL statement
        Keyword arguments:
          key: column
          value: value
          separator: logical separator (AND, OR)
          sql: SQL statement
          bind: bind tuple
    '''
    eprefix = ''
    if not isinstance(key, str):
        key = key.decode('utf-8')
    if re.search(r'[!><]$', key):
        match = re.search(r'[!><]$', key)
        eprefix = match.group(0)
        key = re.sub(r'[!><]$', '', key)
    if not isinstance(val[0], str):
        val[0] = val[0].decode('utf-8')
    if '*' in val[0]:
        val[0] = val[0].replace('*', '%')
        if eprefix == '!':
            eprefix = ' NOT'
        else:
            eprefix = ''
        sql += separator + ' ' + key + eprefix + ' LIKE %s'
    else:
        sql += separator + ' ' + key + eprefix + '=%s'
    bind = bind + (val,)
    return sql, bind


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
        raise err
    if req.status_code == 200:
        return req.json()
    print("Could not get response from %s: %s" % (url, req.text))
    #raise InvalidUsage("Could not get response from %s: %s" % (url, req.text))
    raise InvalidUsage(req.text, req.status_code)


def check_permission(user, permission=None):
    ''' Validate that a user has a specified permission
        Keyword arguments:
          user: user name
          permission: single permission or list of permissions
    '''
    if not permission:
        stmt = "SELECT * FROM user_permission_vw WHERE name=%s"
        try:
            g.c.execute(stmt, (user))
            rows = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        perm = [row['permission'] for row in rows]
        return perm
    if type(permission).__name__ == 'str':
        permission = [permission]
    stmt = "SELECT * FROM user_permission_vw WHERE name=%s AND permission=%s"
    for per in permission:
        bind = (user, per)
        try:
            g.c.execute(stmt, bind)
            row = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        if row:
            return 1
    return 0


def check_project(project, ipd):
    ''' Check to ensure that a project exists and is active.
        Keyword arguments:
          project: project instance
          ipd: request payload
    '''
    if not project:
        raise InvalidUsage("Project %s does not exist" % ipd['project_name'], 404)
    if not project['active']:
        raise InvalidUsage("Project %s is not active" % project['name'])


def generate_sql(request, result, sql, query=False):
    ''' Generate a SQL statement and tuple of associated bind variables.
        Keyword arguments:
          request: API request
          result: result dictionary
          sql: base SQL statement
          query: uses "id" column if true
    '''
    bind = ()
    # pylint: disable=W0603
    idcolumn = 0
    query_string = 'id='+str(query) if query else request.query_string
    order = ''
    if query_string:
        if not isinstance(query_string, str):
            query_string = query_string.decode('utf-8')
        ipd = parse_qs(query_string)
        separator = ' AND' if ' WHERE ' in sql else ' WHERE'
        for key, val in ipd.items():
            if key == '_sort':
                order = ' ORDER BY ' + val[0]
            elif key == '_columns':
                sql = sql.replace('*', val[0])
                varr = val[0].split(',')
                if 'id' in varr:
                    idcolumn = 1
            elif key == '_distinct':
                if 'DISTINCT' not in sql:
                    sql = sql.replace('SELECT', 'SELECT DISTINCT')
            else:
                sql, bind = add_key_value_pair(key, val, separator, sql, bind)
                separator = ' AND'
    sql += order
    if bind:
        result['rest']['sql_statement'] = sql % bind
    else:
        result['rest']['sql_statement'] = sql
    return sql, bind, idcolumn


def get_assignment_by_name_or_id(aid):
    ''' Get an assignment by name or ID
        Keyword arguments:
          aid: assignment name or ID
    '''
    aid = str(aid)
    stmt = "SELECT * FROM assignment_vw WHERE id=%s" if aid.isdigit() \
           else "SELECT * FROM assignment_vw WHERE name=%s"
    try:
        g.c.execute(stmt, (aid))
        assignment = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return assignment


def get_key_type_id(key_type):
    ''' Determine the ID for a key type
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


def get_project_by_name_or_id(proj):
    ''' Get a project by name or ID
        Keyword arguments:
          proj: project name or ID
    '''
    proj = str(proj)
    stmt = "SELECT * FROM project_vw WHERE id=%s" if proj.isdigit() \
           else "SELECT * FROM project_vw WHERE name=%s"
    try:
        g.c.execute(stmt, (proj))
        project = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return project


def get_tasks_by_assignment_id(aid):
    ''' Get tasks by assignment ID
        Keyword arguments:
          aid: assignment ID
    '''
    try:
        g.c.execute("SELECT * FROM task_vw WHERE assignment_id=%s", (aid))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return tasks


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


def get_user_by_name(uname):
    ''' Given a user name, return the user record
        Keyword arguments:
          uname: user name
        Returns:
          user record
    '''
    try:
        g.c.execute("SELECT * FROM user_vw WHERE name='%s'" % uname)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return row


def get_workday(janelia_id):
    ''' Given a Janelia ID, return the Workday record
        Keyword arguments:
          janelia_id: Janelia ID
        Returns:
          Workday record
    '''
    data = call_responder('config', 'config/workday/' + janelia_id)
    if not data:
        raise InvalidUsage('User %s not found in Workday' % (janelia_id))
    work = data['config']
    return work


def neuprint_custom_query(payload):
    ''' Execute a custom NeuPrint query
        Keyword arguments:
          payload: Cypher payload
    '''
    try:
        response = call_responder('neuprint', 'custom/custom', {"cypher": payload})
    except Exception as err:
        raise err
    return response


def random_string(strlen=8):
    ''' Generate a random string of letters and digits
        Keyword arguments:
          strlen: length of generated string
    '''
    components = string.ascii_letters + string.digits
    return ''.join(random.choice(components) for i in range(strlen))


def return_tasks_json(assignment, result):
    ''' Given an assignment name, return tasks JSON
        Keyword arduments:
          assignment: assignment name
          result: result dictionary
    '''
    # pylint: disable=W0703
    result['task list'] = list()
    sql = 'SELECT t.id AS task_id,type,value,key_type,key_text FROM task_vw t ' \
          + 'LEFT OUTER JOIN task_property_vw tp ON (t.id=tp.task_id) WHERE ' \
          + 't.assignment=%s'
    try:
        g.c.execute(sql, (assignment,))
        taskprops = g.c.fetchall()
    except Exception as err:
        return sql_error(err)
    this_task = ''
    task = {}
    task_count = 0
    for tps in taskprops:
        if this_task != tps['task_id']:
            if this_task:
                result['task list'].append(task)
            this_task = tps['task_id']
            task = {"assignment_manager_task_id": this_task,
                    tps['key_type']: tps['key_text']}
            task_count += 1
        if tps['type']:
            if tps['type'] in ['body ID A', 'body ID B', 'supervoxel ID 1', 'supervoxel ID 2']:
                task[tps['type']] = int(tps['value'])
            elif tps['type'] in ['supervoxel point 1', 'supervoxel point 2',
                                 'body point 1', 'body point 2']:
                task[tps['type']] = json.loads(tps['value'])
            else:
                task[tps['type']] = tps['value']


    if this_task:
        result['task list'].append(task)
    result['rest']['row_count'] = task_count
    return None


def sql_error(err):
    ''' Given a MySQL error, return the error message
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


def update_property(pid, table, name, value):
    ''' Insert/update a property
        Keyword arguments:
          id: parent ID
          result: result dictionary
          table: parent table
          name: CV term
          value: value
    '''
    stmt = "INSERT INTO %s_property (%s_id,type_id,value) VALUES " \
           + "(!s,getCvTermId(!s,!s,NULL),!s) ON DUPLICATE KEY UPDATE value=!s"
    stmt = stmt % (table, table)
    stmt = stmt.replace('!s', '%s')
    bind = (pid, table, name, value, value)
    try:
        g.c.execute(stmt, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def validate_user(user):
    ''' Validate a user
        Keyword arguments:
          user: user name or Janelia ID
    '''
    stmt = "SELECT * FROM user_vw WHERE name=%s OR janelia_id=%s"
    try:
        g.c.execute(stmt, (user, user))
        usr = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if not usr:
        raise InvalidUsage("User %s does not exist" % (user), 400)
    return usr['name'], usr['janelia_id']


def working_duration(start_unix, end_unix):
    ''' Determine working duration (working hours only)
        Keyword arguments:
          start_unix: start time (epoch seconds)
          end_unix: end time (epoch seconds)
    '''
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
