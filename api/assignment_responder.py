''' assignment_responder.py
    REST API for assignment database
'''

from datetime import datetime, timedelta
from importlib import import_module, reload
import inspect
import json
import os
import platform
import re
import sys
from time import time
from urllib.parse import parse_qs
import elasticsearch
from flask import Flask, g, render_template, request, jsonify
from flask.json import JSONEncoder
from flask_cors import CORS
from flask_swagger import swagger
from kafka import KafkaProducer
from kafka.errors import KafkaError
import pymysql.cursors
import requests

import assignment_utilities
from assignment_utilities import (InvalidUsage, call_responder, get_assignment_by_id,
                                  get_key_type_id, get_task_by_id, sql_error, working_duration)

# pylint: disable=W0611
from orphan_link import Orphan_link
from cleave import Cleave
from tasks import generate_tasks

# SQL statements
READ = {
    'ASSIGNMENT': "SELECT * FROM assignment_vw WHERE id=%s",
    'CVREL': "SELECT subject,relationship,object FROM cv_relationship_vw "
             + "WHERE subject_id=%s OR object_id=%s",
    'CVTERMREL': "SELECT subject,relationship,object FROM "
                 + "cv_term_relationship_vw WHERE subject_id=%s OR "
                 + "object_id=%s",
    'GET_ASSOCIATION': "SELECT object FROM cv_term_relationship_vw WHERE "
                       + "subject=%s AND relationship='associated_with'",
    'PROJECT': "SELECT * FROM project_vw WHERE name=%s",
    'TASK': "SELECT * FROM task_vw WHERE id=%s",
    'TASK_EXISTS': "SELECT * FROM task_vw WHERE project_id=%s AND key_type=%s AND key_text=%s",
    'UNASSIGNED_TASKS': "SELECT id,name,key_type_id,key_text FROM task WHERE project_id=%s AND "
                        + "assignment_id IS NULL ORDER BY id",
}
WRITE = {
    'ASSIGN_TASK': "UPDATE task SET assignment_id=%s,user=%s WHERE assignment_id IS NULL AND id=%s",
    'DELETE_UNASSIGNED': "DELETE FROM task WHERE project_id=%s AND assignment_id IS NULL",
    'INSERT_ASSIGNMENT': "INSERT INTO assignment (name,project_id,user) VALUES(%s,"
                         + "%s,%s)",
    'INSERT_PROJECT': "INSERT INTO project (name,protocol_id) VALUES(%s,"
                      + "getCvTermId('protocol',%s,NULL))",
    'INSERT_CV' : "INSERT INTO cv (name,definition,display_name,version,"
                  + "is_current) VALUES (%s,%s,%s,%s,%s)",
    'INSERT_CVTERM' : "INSERT INTO cv_term (cv_id,name,definition,display_name"
                      + ",is_current,data_type) VALUES (getCvId(%s,''),%s,%s,"
                      + "%s,%s,%s)",
    'INSERT_TASK': "INSERT INTO task (name,project_id,key_type_id,key_text,"
                   + "user) VALUES (%s,%s,getCvTermId('key',%s,NULL),%s,%s)",
    'TASK_AUDIT': "INSERT INTO task_audit (project_id,assignment_id,key_type_id,key_text,"
                  + "disposition,user) VALUES (%s,%s,%s,%s,%s,%s)",
}

# pylint: disable=C0302,C0103,W0703

class CustomJSONEncoder(JSONEncoder):
    ''' Define a custom JSON encoder
    '''
    def default(self, obj):   # pylint: disable=E0202, W0221
        try:
            if isinstance(obj, datetime):
                return obj.strftime('%a, %-d %b %Y %H:%M:%S')
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)

__version__ = '0.2.1'
app = Flask(__name__)
app.json_encoder = CustomJSONEncoder
app.config.from_pyfile("config.cfg")
SERVER = dict()
CORS(app)
try:
    CONN = pymysql.connect(host=app.config['MYSQL_DATABASE_HOST'],
                           user=app.config['MYSQL_DATABASE_USER'],
                           password=app.config['MYSQL_DATABASE_PASSWORD'],
                           db=app.config['MYSQL_DATABASE_DB'],
                           cursorclass=pymysql.cursors.DictCursor)
    CURSOR = CONN.cursor()
except Exception as err:
    ttemplate = "An exception of type {0} occurred. Arguments:\n{1!r}"
    tmessage = ttemplate.format(type(err).__name__, err.args)
    print(tmessage)
    sys.exit(-1)
app.config['STARTTIME'] = time()
app.config['STARTDT'] = datetime.now()
IDCOLUMN = 0
START_TIME = ESEARCH = PRODUCER = ''


# *****************************************************************************
# * Flask                                                                     *
# *****************************************************************************


@app.before_request
def before_request():
    ''' Set transaction start time and increment counters.
        If needed, initilize global variables.
    '''
    # pylint: disable=W0603
    global START_TIME, ESEARCH, SERVER, PRODUCER
    g.db = CONN
    g.c = CURSOR
    if not SERVER:
        try:
            data = call_responder('config', 'config/rest_services')
            assignment_utilities.CONFIG = data['config']
            data = call_responder('config', 'config/servers')
            SERVER = data['config']
        except Exception as err: # pragma: no cover
            temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
            mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
            raise InvalidUsage(mess, 500)
        try:
            ESEARCH = elasticsearch.Elasticsearch(SERVER['elk-elastic']['address'])
        except Exception as err: # pragma: no cover
            temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
            mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
            raise InvalidUsage(mess, 500)
        PRODUCER = KafkaProducer(bootstrap_servers=SERVER['Kafka']['broker_list'])
    START_TIME = time()
    app.config['COUNTER'] += 1
    endpoint = request.endpoint if request.endpoint else '(Unknown)'
    app.config['ENDPOINTS'][endpoint] = app.config['ENDPOINTS'].get(endpoint, 0) + 1
    if request.method == 'OPTIONS':
        result = initialize_result()
        return generate_response(result)
    return None


# ******************************************************************************
# * Utility functions                                                          *
# ******************************************************************************


def call_profile(token):
    ''' Get information from a given JWT token
        Keyword arguments:
          token: JWT token
    '''
    url = assignment_utilities.CONFIG['neuprint']['url'] + 'profile'
    url = url.replace('/api', '')
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + token}
    try:
        req = requests.get(url, headers=headers)
    except requests.exceptions.RequestException as err: # pragma no cover
        print(err)
        sys.exit(-1)
    if req.status_code == 200:
        return req.json()
    if req.status_code == 401:
        raise InvalidUsage("Please provide a valid Auth Token", 401)
    print("Could not get response from %s" % (url))
    print(req)
    sys.exit(-1)


def initialize_result():
    ''' Initialize the result dictionary
        An auth header with a JWT token is required for all POST and DELETE requests
    '''
    result = {"rest": {'requester': request.remote_addr,
                       'url': request.url,
                       'endpoint': request.endpoint,
                       'error': False,
                       'elapsed_time': '',
                       'row_count': 0}}
    if 'Authorization' in  request.headers:
        token = re.sub(r'Bearer\s+', '', request.headers['Authorization'])
        dtok = dict()
        assignment_utilities.BEARER = token
        dtok = call_profile(token)
        result['rest']['user'] = dtok['ImageURL']
        app.config['USERS'][dtok['ImageURL']] = app.config['USERS'].get(dtok['ImageURL'], 0) + 1
    elif request.method in ['DELETE', 'POST'] or request.endpoint in app.config['REQUIRE_AUTH']:
        raise InvalidUsage('You must authorize to use this endpoint', 401)
    if app.config['LAST_TRANSACTION'] and time() - app.config['LAST_TRANSACTION'] \
       >= app.config['RECONNECT_SECONDS']:
        g.db.ping()
    app.config['LAST_TRANSACTION'] = time()
    return result


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


def generate_sql(result, sql, query=False):
    ''' Generate a SQL statement and tuple of associated bind variables.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
          query: uses "id" column if true
    '''
    bind = ()
    # pylint: disable=W0603
    global IDCOLUMN
    IDCOLUMN = 0
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
                    IDCOLUMN = 1
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
    return sql, bind


def execute_sql(result, sql, container, query=False):
    ''' Build and execute a SQL statement.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
          container: name of dictionary in result disctionary to return rows
          query: uses "id" column if true
    '''
    sql, bind = generate_sql(result, sql, query)
    if app.config['DEBUG']: # pragma: no cover
        if bind:
            print(sql % bind)
        else:
            print(sql)
    try:
        if bind:
            g.c.execute(sql, bind)
        else:
            g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    result[container] = []
    if rows:
        result[container] = rows
        result['rest']['row_count'] = len(rows)
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
        return 1
    raise InvalidUsage("No rows returned for query %s" % (sql,), 404)


def show_columns(result, table):
    ''' Return the columns in a given table/view
        Keyword arguments:
          result: result dictionary
          table: MySQL table
    '''
    result['columns'] = []
    try:
        g.c.execute("SHOW COLUMNS FROM " + table)
        rows = g.c.fetchall()
        if rows:
            result['columns'] = rows
            result['rest']['row_count'] = len(rows)
        return 1
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def get_additional_cv_data(sid):
    ''' Return CV relationships
        Keyword arguments:
          sid: CV ID
    '''
    sid = str(sid)
    g.c.execute(READ['CVREL'], (sid, sid))
    cvrel = g.c.fetchall()
    return cvrel


def get_cv_data(result, cvs):
    ''' Get data for a CV
        Keyword arguments:
          result: result dictionary
          cvs: rows of data from cv table
    '''
    result['data'] = []
    try:
        for col in cvs:
            tcv = col
            if ('id' in col) and (not IDCOLUMN):
                cvrel = get_additional_cv_data(col['id'])
                tcv['relationships'] = list(cvrel)
            result['data'].append(tcv)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def get_additional_cv_term_data(sid):
    ''' Return CV term relationships
        Keyword arguments:
          sid: CV term ID
    '''
    sid = str(sid)
    g.c.execute(READ['CVTERMREL'], (sid, sid))
    cvrel = g.c.fetchall()
    return cvrel


def get_cv_term_data(result, cvterms):
    ''' Get data for a CV term
        Keyword arguments:
          result: result dictionary
          cvterms: rows of data from cv table
    '''
    result['data'] = []
    try:
        for col in cvterms:
            cvterm = col
            if ('id' in col) and (not IDCOLUMN):
                cvtermrel = get_additional_cv_term_data(col['id'])
                cvterm['relationships'] = list(cvtermrel)
            result['data'].append(cvterm)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def generate_response(result):
    ''' Generate a response to a request
        Keyword arguments:
          result: result dictionary
    '''
    result['rest']['elapsed_time'] = str(timedelta(seconds=(time() - START_TIME)))
    return jsonify(**result)


def update_property(pid, result, table, name, value):
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
        publish_cdc(result, {"table": table + "_property", "operation": "update"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def receive_payload(result):
    ''' Get a request payload (form or JSON).
        Keyword arguments:
          result: result dictionary
    '''
    pay = dict()
    if not request.get_data():
        return pay
    try:
        if request.form:
            result['rest']['form'] = request.form
            for i in request.form:
                pay[i] = request.form[i]
        elif request.json:
            result['rest']['json'] = request.json
            pay = request.json
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500)
    return pay


def filter_greater_than(project, row, filt):
    ''' Filter NeuPrint record by body size and/or synapses
        Keyword arguments:
          project: project instance
          row: NeuPrint record
          filt: size cutoff
    '''
    for parm in project.allowable_filters:
        if parm in filt:
            if int(row[parm]) < int(filt[parm]):
                return 0
    return 1


def check_missing_parms(ipd, required):
    ''' Check for missing parameters
        Keyword arguments:
          ipd: request payload
          required: list of required parameters
    '''
    missing = ''
    for prm in required:
        if prm not in ipd:
            missing = missing + prm + ' '
    if missing:
        raise InvalidUsage('Missing arguments: ' + missing)


def generate_tasks_DEPRECATED(result, projectins, new_project):
    ''' Generate and persist a list of tasks for a project
        Keyword arguments:
          result: result dictionary
          projectins: project instance
          new_project: indicates if this is a new or existing project
    '''
    perfstart = datetime.now()
    key_type = projectins.unit
    ignored = inserted = 0
    if not new_project:
        # Delete unassigned tasks
        try:
            g.c.execute(WRITE['DELETE_UNASSIGNED'], (result['rest']['inserted_id']))
            result['rest']['row_count'] += g.c.rowcount
            print("Deleted %d unassigned tasks for project %s" \
                  % (g.c.rowcount, result['rest']['inserted_id']))
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    for task in result['tasks']:
        if not new_project:
            try:
                bind = (result['rest']['inserted_id'], key_type, str(task[key_type]))
                g.c.execute(READ['TASK_EXISTS'], bind)
                this_task = g.c.fetchone()
            except Exception as err:
                raise InvalidUsage(sql_error(err), 500)
            if this_task:
                ignored += 1
                continue
        # Insert task
        try:
            name = "%d.%s" % (result['rest']['inserted_id'], str(task[key_type]))
            bind = (name, result['rest']['inserted_id'], key_type,
                    str(task[key_type]), result['rest']['user'],)
            g.c.execute(WRITE['INSERT_TASK'], bind)
            task_id = g.c.lastrowid
            result['rest']['row_count'] += g.c.rowcount
            inserted += 1
            bind = (result['rest']['inserted_id'], None, get_key_type_id(key_type),
                    str(task[key_type]), 'Inserted', result['rest']['user'])
            g.c.execute(WRITE['TASK_AUDIT'], bind)
            publish_cdc(result, {"table": "task", "operation": "insert"})
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        # Insert task properties
        for prop in ['cluster_name', 'post', 'pre', 'status']:
            if prop in task:
                update_property(task_id, result, 'task', prop, task[prop])
                result['rest']['row_count'] += g.c.rowcount
    result['rest']['elapsed_task_generation'] = str(datetime.now() - perfstart)
    if ignored:
        result['rest']['tasks_skipped'] = ignored
    if inserted:
        result['rest']['tasks_inserted'] = inserted


def valid_cv_term(cv, cv_term):
    ''' Determine if a CV term is valid for a given CV
        Keyword arguments:
          cv: CV
          cv_term: CV term
    '''
    if cv not in app.config['VALID_TERMS']:
        g.c.execute("SELECT cv_term FROM cv_term_vw WHERE cv=%s", (cv))
        cv_terms = g.c.fetchall()
        app.config['VALID_TERMS'][cv] = []
        for term in cv_terms:
            app.config['VALID_TERMS'][cv].append(term['cv_term'])
    return 1 if cv_term in app.config['VALID_TERMS'][cv] else 0


def query_neuprint(projectins, result, ipd):
    ''' Build and execute NeuPrint Cypher query and add tasks to result['tasks']
        Keyword arguments:
          projectins: project instance
          result: result dictionary
          ipd: request payload
    '''
    try:
        response = projectins.cypher(result, ipd)
    except AssertionError as err:
        raise InvalidUsage(err.args[0])
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500)
    if not response['data']:
        raise InvalidUsage('No neurons found', 404)
    nlist = []
    if app.config['DEBUG']:
        print("Filtering %s potential tasks" % (len(response['data'])))
    for row in response['data']:
        ndat = row[0]
        if not filter_greater_than(projectins, ndat, ipd):
            continue
        status = ''
        if 'status' in ndat:
            status = ndat['status']
        timestamp = ''
        if 'timestamp' in ndat:
            timestamp = ndat['timeStamp']
        this_dict = {"post": ndat['post'],
                     "pre": ndat['pre'],
                     "size": ndat['size'],
                     "status": status,
                     "timestamp": timestamp}
        if 'clusterName' in ndat:
            this_dict['cluster_name'] = ndat['clusterName']
        this_dict[projectins.unit] = ndat[projectins.cypher_unit]
        nlist.append(this_dict)
    result['tasks'] = sorted(nlist, key=lambda i: i['timestamp'])
    print("%s tasks(s) remain after filtering" % (len(result['tasks'])))


def insert_project(ipd, result):
    ''' Insert a new project
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    # Insert project record
    if ipd['project_name'].isdigit():
        raise InvalidUsage("Project name must have at least one alphabetic character", 400)
    try:
        bind = (ipd['project_name'], ipd['protocol'])
        g.c.execute(WRITE['INSERT_PROJECT'], bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['inserted_id'] = g.c.lastrowid
        result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_PROJECT'], bind)
        publish_cdc(result, {"table": "project", "operation": "insert"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def generate_project(protocol, result):
    ''' Generate and persist a project (and its tasks).
        Keyword arguments:
          protocol: project protocol
          result: result dictionary
    '''
    # Get payload
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['project_name'])
    if ipd['project_name'].isdigit():
        raise InvalidUsage("Project name must have at least one alphabetic character", 400)
    if app.config['DEBUG']:
        print("Generating %s project %s" % (protocol, ipd['project_name']))
    ipd['protocol'] = protocol
    # Is this a valid protocol?
    if not valid_cv_term('protocol', protocol):
        raise InvalidUsage("%s in not a valid protocol" % protocol, 400)
    # Instattiate project
    constructor = globals()[protocol.capitalize()]
    projectins = constructor()
    # Create tasks in memory
    method = projectins.task_populate_method
    globals()[method](projectins, result, ipd)
    if not result['tasks']:
        return
    # We have tasks! Create a project (unless it already exists).
    project = get_project_by_name_or_id(ipd['project_name'])
    existing_project = False
    if project:
        ipd['project_name'] = project['name']
        result['rest']['inserted_id'] = project['id']
        existing_project = True
        print("Project %s (ID %s) already exists" % (project['name'], project['id']))
    else:
        insert_project(ipd, result)
    # Add project properties from input parameters
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(result['rest']['inserted_id'], result, 'project', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    # Add the filter as a project property
    update_property(result['rest']['inserted_id'], result, 'project', 'filter', json.dumps(ipd))
    result['rest']['row_count'] += g.c.rowcount
    # Insert tasks into the database
    generate_tasks(result, projectins.unit, projectins.task_insert_props, existing_project)


def get_project_by_name_or_id(proj):
    ''' Get a project by ID
        Keyword arguments:
          proj: project name or ID
    '''
    stmt = "SELECT * FROM project_vw WHERE id=%s" if proj.isdigit() \
           else "SELECT * FROM project_vw WHERE name=%s"
    try:
        g.c.execute(stmt, (proj))
        project = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return project


def get_unassigned_project_tasks(ipd, project_id, num_tasks):
    ''' Get a list of unassigned tasks for a project
        Keyword arguments:
          ipd: request payload
          project_id: project ID
          num_tasks: number of tasks to assign
    '''
    try:
        g.c.execute(READ['UNASSIGNED_TASKS'], (project_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if not tasks:
        raise InvalidUsage("Project %s has no unassigned tasks" % ipd['project_name'], 404)
    if len(tasks) < num_tasks:
        raise InvalidUsage(("Project %s only has %s unassigned tasks, not %s" \
                            % (ipd['project_name'], len(tasks), ipd['tasks'])), 404)
    return tasks


def get_incomplete_assignment_tasks(assignment_id):
    ''' Get a list of completed tasks for an assignment
        Keyword arguments:
          assignment_id: assignment ID
    '''
    try:
        stmt = "SELECT id FROM task WHERE assignment_id=%s AND completion_date IS NULL"
        g.c.execute(stmt, (assignment_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if tasks:
        raise InvalidUsage("Found %s task(s) not yet complete for assignment %s" \
                           % (len(tasks), assignment_id), 400)


def generate_assignment(ipd, result):
    ''' Generate and persist an assignment and update its tasks.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    # Find the project
    project = get_project_by_name_or_id(ipd['project_name'])
    if not project:
        raise InvalidUsage("Project %s does not exist" % ipd['project_name'], 404)
    ipd['project_name'] = project['name']
    constructor = globals()[project['protocol'].capitalize()]
    projectins = constructor()
    if 'tasks' in ipd:
        num_tasks = int(ipd['tasks'])
    else:
        num_tasks = projectins.num_tasks
    tasks = get_unassigned_project_tasks(ipd, project['id'], num_tasks)
    try:
        bind = (ipd['assignment_name'], project['id'], ipd['user'])
        g.c.execute(WRITE['INSERT_ASSIGNMENT'], bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['inserted_id'] = g.c.lastrowid
        result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_ASSIGNMENT'], bind)
        publish_cdc(result, {"table": "assignment", "operation": "insert"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(result['rest']['inserted_id'], result, 'assignment', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    updated = 0
    for task in tasks:
        try:
            bind = (result['rest']['inserted_id'], ipd['user'], task['id'])
            g.c.execute(WRITE['ASSIGN_TASK'], bind)
            result['rest']['row_count'] += g.c.rowcount
            updated += 1
            publish_cdc(result, {"table": "assignment", "operation": "update"})
            bind = (project['id'], result['rest']['inserted_id'], task['key_type_id'],
                    task['key_text'], 'Assigned', ipd['user'])
            g.c.execute(WRITE['TASK_AUDIT'], bind)
            if updated >= num_tasks:
                break
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    if updated != num_tasks:
        raise InvalidUsage("Could not assign tasks for project %s" % ipd['project_name'], 500)
    result['rest']['assigned_tasks'] = updated
    if 'start' in ipd:
        ipd['id'] = result['rest']['inserted_id']
        start_assignment(ipd, result)
    g.db.commit()


def start_assignment(ipd, result):
    ''' Start a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    assignment = get_assignment_by_id(ipd['id'])
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % ipd['id'], 404)
    if assignment['start_date']:
        raise InvalidUsage("Assignment %s was already started" % ipd['id'], 400)
    # Update the assignment
    try:
        stmt = "UPDATE assignment SET start_date=NOW()," \
               + "disposition='In progress' WHERE id=%s AND start_date IS NULL"
        bind = (ipd['id'],)
        start_time = int(time())
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    constructor = globals()[assignment['protocol'].capitalize()]
    projectins = constructor()
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(ipd['id'], result, 'assignment', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    # Update the project
    try:
        g.c.execute("UPDATE project SET disposition='In progress' WHERE "
                    + "name=%s", (assignment['project'],))
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
    message = {"mad_id": assignment['id'], "user": assignment['user'],
               "start_time": start_time, "protocol": assignment['protocol']}
    publish_kafka('assignment_start', result, message)


def get_task_by_key(pid, key_type, key):
    ''' Get a task by project ID/key type/key
        Keyword arguments:
          pid: project ID
          key_type: key type
          key: key
    '''
    bind = (pid, key_type, key)
    g.c.execute("SELECT * from task_vw WHERE project_id=%s AND key_type=%s AND key_text=%s", bind)
    return g.c.fetchone()


def start_task(ipd, result):
    ''' Start a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    task = get_task_by_id(ipd['id'])
    if not task:
        raise InvalidUsage("Task %s does not exist" % ipd['id'], 404)
    if task['start_date']:
        raise InvalidUsage("Task %s was already started" % ipd['id'], 400)
    if not task['assignment_id']:
        raise InvalidUsage("Task %s is not assigned" % ipd['id'], 400)
    # Check the asignment
    assignment = get_assignment_by_id(task['assignment_id'])
    if not assignment['start_date']:
        raise InvalidUsage("Assignment %s (associated with task %s) has not been started" \
                           % (task['assignment_id'], ipd['id']), 400)
    # Update the task
    try:
        stmt = "UPDATE task SET start_date=NOW(),disposition='In progress' " \
               + "WHERE id=%s AND start_date IS NULL"
        bind = (ipd['id'],)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        publish_cdc(result, {"table": "task", "operation": "update"})
        bind = (task['project_id'], assignment['id'], task['key_type_id'], task['key_text'],
                'In progress', task['user'])
        g.c.execute(WRITE['TASK_AUDIT'], bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    assignment = get_assignment_by_id(task['assignment_id'])
    constructor = globals()[assignment['protocol'].capitalize()]
    projectins = constructor()
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(ipd['id'], result, 'task', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    g.db.commit()


def complete_task(ipd, result):
    ''' Complete a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    task = get_task_by_id(ipd['id'])
    if not task:
        raise InvalidUsage("Task %s does not exist" % ipd['id'], 404)
    if not task['start_date']:
        raise InvalidUsage("Task %s was not started" % ipd['id'], 400)
    if task['completion_date']:
        raise InvalidUsage("Task %s was already completed" % ipd['id'], 400)
    start_time = int(task['start_date'].timestamp())
    end_time = int(time())
    duration = end_time - start_time
    working = working_duration(start_time, end_time)
    # Update the task
    # Get the disposition
    disposition = 'Complete'
    if 'disposition' in ipd:
        disposition = ipd['disposition']
        if not valid_cv_term('disposition', disposition):
            raise InvalidUsage("%s in not a valid disposition" % disposition, 400)
    try:
        stmt = "UPDATE task SET completion_date=FROM_UNIXTIME(%s),disposition=%s," \
               + "duration=%s,working_duration=%s WHERE id=%s AND completion_date IS NULL"
        bind = (end_time, disposition, duration, working, ipd['id'],)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        publish_cdc(result, {"table": "task", "operation": "update"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    assignment = get_assignment_by_id(task['assignment_id'])
    bind = (task['project_id'], assignment['id'], task['key_type_id'], task['key_text'],
            disposition, task['user'])
    g.c.execute(WRITE['TASK_AUDIT'], bind)
    constructor = globals()[assignment['protocol'].capitalize()]
    projectins = constructor()
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(ipd['id'], result, 'task', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    g.db.commit()


def publish_kafka(topic, result, message):
    ''' Publish a message to Kafka
        Keyword arguments:
          topic: Kafka topic
          result: result dictionary
          message: message to publish
    '''
    message['uri'] = request.url
    message['client'] = 'assignment_responder'
    if 'user' not in message:
        message['user'] = result['rest']['user']
    message['host'] = os.uname()[1]
    message['status'] = 200
    message['time'] = int(time())
    future = PRODUCER.send(topic, json.dumps(message).encode('utf-8'))
    try:
        future.get(timeout=10)
    except KafkaError:
        print("Failed sending message to Kafka!")


def publish_cdc(result, message):
    ''' Publish a CDC message to Kafka
        Keyword arguments:
          result: result dictionary
          message: message to publish
    '''
    if not app.config['ENABLE_CDC']:
        return
    message['uri'] = request.url
    message['client'] = 'assignment_responder'
    message['user'] = result['rest']['user']
    message['host'] = os.uname()[1]
    message['status'] = 200
    message['time'] = int(time())
    message['id'] = g.c.lastrowid
    message['rows'] = g.c.rowcount
    message['sql'] = g.c._last_executed # pylint: disable=W0212
    future = PRODUCER.send(app.config['KAFKA_TOPIC'], json.dumps(message).encode('utf-8'))
    try:
        future.get(timeout=10)
    except KafkaError:
        print("Failed sending CDC to Kafka!")


def remove_id_from_index(this_id, index, result):
    ''' Remove an assignment from an ElasticSearch index
        Keyword arguments:
          this_id: ID
          index: ES index
          result: result dictionary
    '''
    es_deletes = 0
    payload = {"query": {"term": {"mad_id": this_id}}}
    try:
        searchres = ESEARCH.search(index=index, body=payload)
    except elasticsearch.NotFoundError:
        raise InvalidUsage("Index " + index + " does not exist", 404)
    except Exception as esex: # pragma no cover
        raise InvalidUsage(str(esex))
    for hit in searchres['hits']['hits']:
        try:
            ESEARCH.delete(index=hit['_index'], doc_type='doc', id=hit['_id'])
            es_deletes += 1
        except Exception as esex: # pragma no cover
            raise InvalidUsage(str(esex))
    result['rest']['elasticsearch_deletes'] = es_deletes

# *****************************************************************************
# * Endpoints                                                                 *
# *****************************************************************************
@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    ''' Error handler
        Keyword arguments:
          error: error object
    '''
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


@app.route('/')
def show_swagger():
    ''' Default route
    '''
    return render_template('swagger_ui.html')


@app.route("/spec")
def spec():
    ''' Show specification
    '''
    return get_doc_json()


@app.route('/doc')
def get_doc_json():
    ''' Show documentation
    '''
    swag = swagger(app)
    swag['info']['version'] = __version__
    swag['info']['title'] = "Assignment Responder"
    return jsonify(swag)


@app.route("/stats")
def stats():
    '''
    Show stats
    Show uptime/requests statistics
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Stats
      400:
          description: Stats could not be calculated
    '''
    tbt = time() - app.config['LAST_TRANSACTION']
    result = initialize_result()
    db_connection = True
    try:
        g.db.ping(reconnect=False)
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        result['rest']['error'] = mess
        db_connection = False
    try:
        start = datetime.fromtimestamp(app.config['STARTTIME']).strftime('%Y-%m-%d %H:%M:%S')
        up_time = datetime.now() - app.config['STARTDT']
        result['stats'] = {"version": __version__,
                           "requests": app.config['COUNTER'],
                           "start_time": start,
                           "uptime": str(up_time),
                           "python": sys.version,
                           "pid": os.getpid(),
                           "endpoint_counts": app.config['ENDPOINTS'],
                           "user_counts": app.config['USERS'],
                           "time_since_last_transaction": tbt,
                           "database_connection": db_connection}
        if None in result['stats']['endpoint_counts']:
            del result['stats']['endpoint_counts']
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500)
    return generate_response(result)


@app.route('/processlist/columns', methods=['GET'])
def get_processlist_columns():
    '''
    Get columns from the system processlist table
    Show the columns in the system processlist table, which may be used to
    filter results for the /processlist endpoints.
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Columns in system processlist table
    '''
    result = initialize_result()
    show_columns(result, "information_schema.processlist")
    return generate_response(result)


@app.route('/processlist', methods=['GET'])
def get_processlist_info():
    '''
    Get processlist information (with filtering)
    Return a list of processlist entries (rows from the system processlist
    table). The caller can filter on any of the columns in the system
    processlist table. Inequalities (!=) and some relational operations
    (&lt;= and &gt;=) are supported. Wildcards are supported (use "*").
    Specific columns from the system processlist table can be returned with
    the _columns key. The returned list may be ordered by specifying a column
    with the _sort key. In both cases, multiple columns would be separated
    by a comma.
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: List of information for one or database processes
      404:
          description: Processlist information not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM information_schema.processlist', 'data')
    for row in result['data']:
        row['HOST'] = 'None' if row['HOST'] is None else row['HOST'].decode("utf-8")
    return generate_response(result)


@app.route('/processlist/host', methods=['GET'])
def get_processlist_host_info(): # pragma: no cover
    '''
    Get processlist information for this host
    Return a list of processlist entries (rows from the system processlist
    table) for this host.
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Database process list information for the current host
      404:
          description: Processlist information not found
    '''
    result = initialize_result()
    hostname = platform.node() + '%'
    try:
        sql = "SELECT * FROM information_schema.processlist WHERE host LIKE %s"
        bind = (hostname)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        result['rest']['row_count'] = len(rows)
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
        for row in rows:
            row['HOST'] = 'None' if row['HOST'] is None else row['HOST'].decode("utf-8")
        result['data'] = rows
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return generate_response(result)


@app.route("/ping")
def pingdb():
    '''
    Ping the database connection
    Ping the database connection and reconnect if needed
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Ping successful
      400:
          description: Ping unsuccessful
    '''
    result = initialize_result()
    try:
        g.db.ping()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 400)
    return generate_response(result)


# *****************************************************************************
# * Test endpoints                                                            *
# *****************************************************************************
@app.route('/test_sqlerror', methods=['GET'])
def testsqlerror():
    ''' Test function
    '''
    result = initialize_result()
    try:
        sql = "SELECT some_column FROM non_existent_table"
        result['rest']['sql_statement'] = sql
        g.c.execute(sql)
        rows = g.c.fetchall()
        return rows
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


@app.route('/test_other_error', methods=['GET'])
def testothererror():
    ''' Test function
    '''
    result = initialize_result()
    try:
        testval = 4 / 0
        result['testval'] = testval
        return result
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


# *****************************************************************************
# * CV/CV term endpoints                                                      *
# *****************************************************************************
@app.route('/cvs/columns', methods=['GET'])
def get_cv_columns():
    '''
    Get columns from cv table
    Show the columns in the cv table, which may be used to filter results for
    the /cvs and /cv_ids endpoints.
    ---
    tags:
      - CV
    responses:
      200:
          description: Columns in cv table
    '''
    result = initialize_result()
    show_columns(result, "cv")
    return generate_response(result)


@app.route('/cv_ids', methods=['GET'])
def get_cv_ids():
    '''
    Get CV IDs (with filtering)
    Return a list of CV IDs. The caller can filter on any of the columns in the
    cv table. Inequalities (!=) and some relational operations (&lt;= and &gt;=)
    are supported. Wildcards are supported (use "*"). The returned list may be
    ordered by specifying a column with the _sort key. Multiple columns should
    be separated by a comma.
    ---
    tags:
      - CV
    responses:
      200:
          description: List of one or more CV IDs
      404:
          description: CVs not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM cv', 'temp'):
        result['data'] = []
        for col in result['temp']:
            result['data'].append(col['id'])
        del result['temp']
    return generate_response(result)


@app.route('/cvs/<string:sid>', methods=['GET'])
def get_cv_by_id(sid):
    '''
    Get CV information for a given ID
    Given an ID, return a row from the cv table. Specific columns from the cv
    table can be returned with the _columns key. Multiple columns should be
    separated by a comma.
    ---
    tags:
      - CV
    parameters:
      - in: path
        name: sid
        schema:
          type: string
        required: true
        description: CV ID
    responses:
      200:
          description: Information for one CV
      404:
          description: CV ID not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT * FROM cv', 'temp', sid):
        get_cv_data(result, result['temp'])
        del result['temp']
    return generate_response(result)


@app.route('/cvs', methods=['GET'])
def get_cv_info():
    '''
    Get CV information (with filtering)
    Return a list of CVs (rows from the cv table). The caller can filter on
    any of the columns in the cv table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). Specific columns from the cv table can be returned with the
    _columns key. The returned list may be ordered by specifying a column with
    the _sort key. In both cases, multiple columns would be separated by a
    comma.
    ---
    tags:
      - CV
    responses:
      200:
          description: List of information for one or more CVs
      404:
          description: CVs not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT * FROM cv', 'temp'):
        get_cv_data(result, result['temp'])
        del result['temp']
    return generate_response(result)


@app.route('/cv', methods=['OPTIONS', 'POST'])
def add_cv(): # pragma: no cover
    '''
    Add CV
    ---
    tags:
      - CV
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: CV name
      - in: query
        name: definition
        schema:
          type: string
        required: true
        description: CV description
      - in: query
        name: display_name
        schema:
          type: string
        required: false
        description: CV display name (defaults to CV name)
      - in: query
        name: version
        schema:
          type: string
        required: false
        description: CV version (defaults to 1)
      - in: query
        name: is_current
        schema:
          type: string
        required: false
        description: is CV current? (defaults to 1)
    responses:
      200:
          description: CV added
      400:
          description: Missing arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['definition', 'name'])
    if 'display_name' not in ipd:
        ipd['display_name'] = ipd['name']
    if 'version' not in ipd:
        ipd['version'] = 1
    if 'is_current' not in ipd:
        ipd['is_current'] = 1
    if not result['rest']['error']:
        try:
            bind = (ipd['name'], ipd['definition'], ipd['display_name'],
                    ipd['version'], ipd['is_current'],)
            g.c.execute(WRITE['INSERT_CV'], bind)
            result['rest']['row_count'] = g.c.rowcount
            result['rest']['inserted_id'] = g.c.lastrowid
            result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_CV'], bind)
            g.db.commit()
            publish_cdc(result, {"table": "cv", "operation": "insert"})
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    return generate_response(result)


@app.route('/cvterms/columns', methods=['GET'])
def get_cv_term_columns():
    '''
    Get columns from cv_term_vw table
    Show the columns in the cv_term_vw table, which may be used to filter
    results for the /cvterms and /cvterm_ids endpoints.
    ---
    tags:
      - CV
    responses:
      200:
          description: Columns in cv_term_vw table
    '''
    result = initialize_result()
    show_columns(result, "cv_term_vw")
    return generate_response(result)


@app.route('/cvterm_ids', methods=['GET'])
def get_cv_term_ids():
    '''
    Get CV term IDs (with filtering)
    Return a list of CV term IDs. The caller can filter on any of the columns
    in the cv_term_vw table. Inequalities (!=) and some relational operations
    (&lt;= and &gt;=) are supported. Wildcards are supported (use "*"). The
    returned list may be ordered by specifying a column with the _sort key.
    Multiple columns should be separated by a comma.
    ---
    tags:
      - CV
    responses:
      200:
          description: List of one or more CV term IDs
      404:
          description: CV terms not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM cv_term_vw', 'temp'):
        result['data'] = []
        for col in result['temp']:
            result['data'].append(col['id'])
        del result['temp']
    return generate_response(result)


@app.route('/cvterms/<string:sid>', methods=['GET'])
def get_cv_term_by_id(sid):
    '''
    Get CV term information for a given ID
    Given an ID, return a row from the cv_term_vw table. Specific columns from
    the cv_term_vw table can be returned with the _columns key. Multiple columns
    should be separated by a comma.
    ---
    tags:
      - CV
    parameters:
      - in: path
        name: sid
        schema:
          type: string
        required: true
        description: CV term ID
    responses:
      200:
          description: Information for one CV term
      404:
          description: CV term ID not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT * FROM cv_term_vw', 'temp', sid):
        get_cv_term_data(result, result['temp'])
        del result['temp']
    return generate_response(result)


@app.route('/cvterms', methods=['GET'])
def get_cv_term_info():
    '''
    Get CV term information (with filtering)
    Return a list of CV terms (rows from the cv_term_vw table). The caller can
    filter on any of the columns in the cv_term_vw table. Inequalities (!=)
    and some relational operations (&lt;= and &gt;=) are supported. Wildcards
    are supported (use "*"). Specific columns from the cv_term_vw table can be
    returned with the _columns key. The returned list may be ordered by
    specifying a column with the _sort key. In both cases, multiple columns
    would be separated by a comma.
    ---
    tags:
      - CV
    responses:
      200:
          description: List of information for one or more CV terms
      404:
          description: CV terms not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT * FROM cv_term_vw', 'temp'):
        get_cv_term_data(result, result['temp'])
        del result['temp']
    return generate_response(result)


@app.route('/cvterm', methods=['OPTIONS', 'POST'])
def add_cv_term(): # pragma: no cover
    '''
    Add CV term
    ---
    tags:
      - CV
    parameters:
      - in: query
        name: cv
        schema:
          type: string
        required: true
        description: CV name
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: CV term name
      - in: query
        name: definition
        schema:
          type: string
        required: true
        description: CV term description
      - in: query
        name: display_name
        schema:
          type: string
        required: false
        description: CV term display name (defaults to CV term name)
      - in: query
        name: is_current
        schema:
          type: string
        required: false
        description: is CV term current? (defaults to 1)
      - in: query
        name: data_type
        schema:
          type: string
        required: false
        description: data type (defaults to text)
    responses:
      200:
          description: CV term added
      400:
          description: Missing arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['cv', 'definition', 'name'])
    if 'display_name' not in ipd:
        ipd['display_name'] = ipd['name']
    if 'is_current' not in ipd:
        ipd['is_current'] = 1
    if 'data_type' not in ipd:
        ipd['data_type'] = 'text'
    if not result['rest']['error']:
        try:
            bind = (ipd['cv'], ipd['name'], ipd['definition'],
                    ipd['display_name'], ipd['is_current'],
                    ipd['data_type'],)
            g.c.execute(WRITE['INSERT_CVTERM'], bind)
            result['rest']['row_count'] = g.c.rowcount
            result['rest']['inserted_id'] = g.c.lastrowid
            result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_CVTERM'], bind)
            publish_cdc(result, {"table": "cv_term", "operation": "insert"})
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    return generate_response(result)


# *****************************************************************************
# * Protocol endpoints                                                        *
# *****************************************************************************
@app.route('/protocols', methods=['GET'])
def get_protocol_info():
    '''
    Get protocol information
    Return a list of protocols (rows from the cv_term_vw table).
    ---
    tags:
      - Protocol
    responses:
      200:
          description: List of protocols
      404:
          description: Protocols not found
    '''
    result = initialize_result()
    execute_sql(result, "SELECT cv_term FROM cv_term_vw WHERE cv='protocol' ORDER BY 1", 'temp')
    result['data'] = dict()
    for prot in result['temp']:
        result['data'][prot['cv_term']] = dict()
        record = result['data'][prot['cv_term']]
        record['module_loaded'] = bool(prot['cv_term'] in sys.modules)
        if record['module_loaded']:
            PROTOCOL = prot['cv_term'].capitalize()
            constructor = globals()[PROTOCOL]
            projectins = constructor()
            for name, data in inspect.getmembers(projectins):
                if name.startswith('__') or 'method' in str(data):
                    continue
                record[name] = str(data)
    del result['temp']
    return generate_response(result)


@app.route('/protocol/<string:protocol>/reload', methods=['OPTIONS', 'POST'])
def reload_protocol(protocol):
    '''
    Reload a protocol module
    Reload a protocol's module.
    ---
    tags:
      - Protocol
    parameters:
      - in: path
        name: protocol
        schema:
          type: string
        required: true
        description: protocol
    responses:
      200:
          description: Protocol reloaded
      404:
          description: Protocol not reloaded
    '''
    result = initialize_result()
    if not protocol in sys.modules:
        raise InvalidUsage("Protocol %s is not loaded" % protocol, 400)
    modobj = import_module(protocol)
    reload(modobj)
    return generate_response(result)


# *****************************************************************************
# * Project endpoints                                                         *
# *****************************************************************************
@app.route('/projects/columns', methods=['GET'])
def get_project_columns():
    '''
    Get columns from project_vw table
    Show the columns in the project_vw table, which may be used to filter
    results for the /projects and /project_ids endpoints.
    ---
    tags:
      - Project
    responses:
      200:
          description: Columns in project_vw table
    '''
    result = initialize_result()
    show_columns(result, "project_vw")
    return generate_response(result)


@app.route('/project_ids', methods=['GET'])
def get_project_ids():
    '''
    Get project IDs (with filtering)
    Return a list of project IDs. The caller can filter on any of the
    columns in the project_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). The returned list may be ordered by specifying a column with
    the _sort key. Multiple columns should be separated by a comma.
    ---
    tags:
      - Project
    responses:
      200:
          description: List of one or more project IDs
      404:
          description: Projects not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM project_vw', 'temp'):
        result['data'] = []
        for col in result['temp']:
            result['data'].append(col['id'])
        del result['temp']
    return generate_response(result)


@app.route('/projects/<string:project_id>', methods=['GET'])
def get_projects_by_id(project_id):
    '''
    Get project information for a given ID
    Given an ID, return a row from the project_vw table. Specific columns
    from the project_vw table can be returned with the _columns key.
    Multiple columns should be separated by a comma.
    ---
    tags:
      - Project
    parameters:
      - in: path
        name: project_id
        schema:
          type: string
        required: true
        description: project ID
    responses:
      200:
          description: Information for one project
      404:
          description: Project ID not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM project_vw', 'data', project_id)
    return generate_response(result)


@app.route('/projects', methods=['GET'])
def get_project_info():
    '''
    Get project information (with filtering)
    Return a list of projects (rows from the project_vw table). The
    caller can filter on any of the columns in the project_vw table.
    Inequalities (!=) and some relational operations (&lt;= and &gt;=) are
    supported. Wildcards are supported (use "*"). Specific columns from the
    project_vw table can be returned with the _columns key. The returned
    list may be ordered by specifying a column with the _sort key. In both
    cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Project
    responses:
      200:
          description: List of information for one or more projects
      404:
          description: Projects not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM project_vw', 'data')
    return generate_response(result)


@app.route('/projectprops/columns', methods=['GET'])
def get_projectprop_columns():
    '''
    Get columns from project_property_vw table
    Show the columns in the project_property_vw table, which may be used to
    filter results for the /projectprops and /projectprop_ids endpoints.
    ---
    tags:
      - Project
    responses:
      200:
          description: Columns in project_prop_vw table
    '''
    result = initialize_result()
    show_columns(result, "project_property_vw")
    return generate_response(result)


@app.route('/projectprop_ids', methods=['GET'])
def get_projectprop_ids():
    '''
    Get project property IDs (with filtering)
    Return a list of project property IDs. The caller can filter on any of
    the columns in the project_property_vw table. Inequalities (!=) and
    some relational operations (&lt;= and &gt;=) are supported. Wildcards are
    supported (use "*"). The returned list may be ordered by specifying a
    column with the _sort key. Multiple columns should be separated by a
    comma.
    ---
    tags:
      - Project
    responses:
      200:
          description: List of one or more project property IDs
      404:
          description: Project properties not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM project_property_vw', 'temp'):
        result['data'] = []
        for rtmp in result['temp']:
            result['data'].append(rtmp['id'])
        del result['temp']
    return generate_response(result)


@app.route('/projectprops/<string:pid>', methods=['GET'])
def get_projectprops_by_id(pid):
    '''
    Get project property information for a given ID
    Given an ID, return a row from the project_property_vw table. Specific
    columns from the project_property_vw table can be returned with the
    _columns key. Multiple columns should be separated by a comma.
    ---
    tags:
      - Project
    parameters:
      - in: path
        name: pid
        schema:
          type: string
        required: true
        description: project property ID
    responses:
      200:
          description: Information for one project property
      404:
          description: Project property ID not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM project_property_vw', 'data', pid)
    return generate_response(result)


@app.route('/projectprops', methods=['GET'])
def get_projectprop_info():
    '''
    Get project property information (with filtering)
    Return a list of project properties (rows from the
    project_property_vw table). The caller can filter on any of the columns
    in the project_property_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). Specific columns from the project_property_vw table can be
    returned with the _columns key. The returned list may be ordered by
    specifying a column with the _sort key. In both cases, multiple columns
    would be separated by a comma.
    ---
    tags:
      - Project
    responses:
      200:
          description: List of information for one or more project
                       properties
      404:
          description: Project properties not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM project_property_vw', 'data')
    return generate_response(result)


@app.route('/project/<string:protocol>', methods=['OPTIONS', 'POST'])
def process_project(protocol):
    '''
    Generate a new project
    Given a protocol and a JSON payload containing specifics, generate
    a new project and return its ID and a list of tasks. A "project_name"
    parameter is required. There are several optional parameters - check
    the "protocols" endpoint to see which protocols support which parameters.
    Parameters may be passed in as form-data or JSON.
    ---
    tags:
      - Project
    parameters:
      - in: path
        name: protocol
        schema:
          type: string
        required: true
        description: protocol
      - in: query
        name: project_name (or ID for an existing project)
        schema:
          type: string
        required: true
        description: project name
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: project note
      - in: query
        name: post
        schema:
          type: string
        required: false
        description: neuron "post" filter
      - in: query
        name: pre
        schema:
          type: string
        required: false
        description: neuron "pre" filter
      - in: query
        name: size
        schema:
          type: string
        required: false
        description: neuron "size" filter
    responses:
      200:
        description: New project ID and list of tasks
      404:
        description: No neurons found
    '''
    result = initialize_result()
    # Create the project
    generate_project(protocol, result)
    return generate_response(result)


# *****************************************************************************
# * Assignment endpoints                                                      *
# *****************************************************************************
@app.route('/assignments/columns', methods=['GET'])
def get_assignment_columns():
    '''
    Get columns from assignment_vw table
    Show the columns in the assignment_vw table, which may be used to filter
    results for the /assignments and /assignment_ids endpoints.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: Columns in assignment_vw table
    '''
    result = initialize_result()
    show_columns(result, "assignment_vw")
    return generate_response(result)


@app.route('/assignment_ids', methods=['GET'])
def get_assignment_ids():
    '''
    Get assignment IDs (with filtering)
    Return a list of assignment IDs. The caller can filter on any of the
    columns in the assignment_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). The returned list may be ordered by specifying a column with
    the _sort key. Multiple columns should be separated by a comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of one or more assignment IDs
      404:
          description: Assignments not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM assignment_vw', 'temp'):
        result['data'] = []
        for col in result['temp']:
            result['data'].append(col['id'])
        del result['temp']
    return generate_response(result)


@app.route('/assignments/<string:assignment_id>', methods=['GET'])
def get_assignments_by_id(assignment_id):
    '''
    Get assignment information for a given ID
    Given an ID, return a row from the assignment_vw table. Specific columns
    from the assignment_vw table can be returned with the _columns key.
    Multiple columns should be separated by a comma.
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: assignment_id
        schema:
          type: string
        required: true
        description: assignment ID
    responses:
      200:
          description: Information for one assignment
      404:
          description: Assignment ID not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM assignment_vw', 'data', assignment_id)
    return generate_response(result)


@app.route('/assignments', methods=['GET'])
def get_assignment_info():
    '''
    Get assignment information (with filtering)
    Return a list of assignments (rows from the assignment_vw table). The
    caller can filter on any of the columns in the assignment_vw table.
    Inequalities (!=) and some relational operations (&lt;= and &gt;=) are
    supported. Wildcards are supported (use "*"). Specific columns from the
    assignment_vw table can be returned with the _columns key. The returned
    list may be ordered by specifying a column with the _sort key. In both
    cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of information for one or more assignments
      404:
          description: Assignments not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM assignment_vw', 'data')
    return generate_response(result)


@app.route('/assignments_completed', methods=['GET'])
def get_assignment_completed_info():
    '''
    Get completed assignment information (with filtering)
    Return a list of assignments (rows from the assignment_vw table) that have
    been completed. The caller can filter on any of the columns in the
    assignment_vw table. Inequalities (!=) and some relational operations
    (&lt;= and &gt;=) are supported. Wildcards are supported (use "*"). Specific
    columns from the assignment_vw table can be returned with the _columns key.
    The returned list may be ordered by specifying a column with the _sort key.
    In both cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of information for one or more completed assignments
      404:
          description: Assignments not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM assignment_vw WHERE completion_date IS NOT NULL', 'data')
    return generate_response(result)


@app.route('/assignments_remaining', methods=['GET'])
def get_assignment_remaining_info():
    '''
    Get remaining assignment information (with filtering)
    Return a list of assignments (rows from the assignment_vw table) that
    haven't been completed yet. The caller can filter on any of the columns
    in the assignment_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). Specific columns from the assignment_vw table can be returned
    with the _columns key. The returned list may be ordered by specifying a
    column with the _sort key. In both cases, multiple columns would be
    separated by a comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of information for one or more remaining
                       assignments
      404:
          description: Assignments not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM assignment_vw WHERE start_date '
                + 'IS NULL AND completion_date IS NULL', 'data')
    return generate_response(result)


@app.route('/assignments_started', methods=['GET'])
def get_assignment_started():
    '''
    Get started assignment information (with filtering)
    Return a list of assignments (rows from the assignment_vw table) that have
    been started but not completed. The caller can filter on any of the columns
    in the assignment_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). Specific columns from the assignment_vw table can be returned
    with the _columns key. The returned list may be ordered by specifying a
    column with the _sort key. In both cases, multiple columns would be
    separated by a comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of information for one or more started assignments
      404:
          description: Assignments not found
    '''
    result = initialize_result()
    execute_sql(result, "SELECT * FROM assignment_vw WHERE start_date IS NOT NULL "
                + "AND completion_date IS NULL", 'data')
    return generate_response(result)


@app.route('/assignmentprops/columns', methods=['GET'])
def get_assignmentprop_columns():
    '''
    Get columns from assignment_property_vw table
    Show the columns in the assignment_property_vw table, which may be used to
    filter results for the /assignmentprops and /assignmentprop_ids endpoints.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: Columns in assignment_prop_vw table
    '''
    result = initialize_result()
    show_columns(result, "assignment_property_vw")
    return generate_response(result)


@app.route('/assignmentprop_ids', methods=['GET'])
def get_assignmentprop_ids():
    '''
    Get assignment property IDs (with filtering)
    Return a list of assignment property IDs. The caller can filter on any of
    the columns in the assignment_property_vw table. Inequalities (!=) and
    some relational operations (&lt;= and &gt;=) are supported. Wildcards are
    supported (use "*"). The returned list may be ordered by specifying a
    column with the _sort key. Multiple columns should be separated by a
    comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of one or more assignment property IDs
      404:
          description: Assignment properties not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM assignment_property_vw', 'temp'):
        result['data'] = []
        for rtmp in result['temp']:
            result['data'].append(rtmp['id'])
        del result['temp']
    return generate_response(result)


@app.route('/assignmentprops/<string:aid>', methods=['GET'])
def get_assignmentprops_by_id(aid):
    '''
    Get assignment property information for a given ID
    Given an ID, return a row from the assignment_property_vw table. Specific
    columns from the assignment_property_vw table can be returned with the
    _columns key. Multiple columns should be separated by a comma.
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: aid
        schema:
          type: string
        required: true
        description: assignment property ID
    responses:
      200:
          description: Information for one assignment property
      404:
          description: Assignment property ID not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM assignment_property_vw', 'data', aid)
    return generate_response(result)


@app.route('/assignmentprops', methods=['GET'])
def get_assignmentprop_info():
    '''
    Get assignment property information (with filtering)
    Return a list of assignment properties (rows from the
    assignment_property_vw table). The caller can filter on any of the columns
    in the assignment_property_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). Specific columns from the assignment_property_vw table can be
    returned with the _columns key. The returned list may be ordered by
    specifying a column with the _sort key. In both cases, multiple columns
    would be separated by a comma.
    ---
    tags:
      - Assignment
    responses:
      200:
          description: List of information for one or more assignment
                       properties
      404:
          description: Assignment properties not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM assignment_property_vw', 'data')
    return generate_response(result)


@app.route('/assignment/<string:project_name>', methods=['OPTIONS', 'POST'])
def new_assignment(project_name):
    '''
    Generate a new assignment
    Given a JSON payload containing specifics, generate a new assignment
    and return its ID. A "project_name" parameter is required. If a "start"
    parameter is specified, the assignment will be immediately started after creation.
    Parameters may be passed in as form-data or JSON.
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: project_name
        schema:
          type: string
        required: true
        description: project name or ID
    responses:
      200:
          description: Assignment generated
      404:
          description: Assignment not generated
    '''
    result = initialize_result()
    # Get payload
    ipd = receive_payload(result)
    ipd['project_name'] = project_name
    ipd['assignment_name'] = ''
    check_missing_parms(ipd, ['user'])
    generate_assignment(ipd, result)
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>', methods=['OPTIONS', 'DELETE'])
def delete_assignment(assignment_id):
    '''
    Delete an assignment
    Selete an assignment and revert its tasks back to unassigned.
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: assignment_id
        schema:
          type: string
        required: true
        description: assignment ID
    responses:
      200:
          description: Assignment deleted
      404:
          description: Assignment was not deleted
    '''
    result = initialize_result()
    assignment = get_assignment_by_id(assignment_id)
    if not assignment:
        raise InvalidUsage("Assignment %s was not found" % assignment_id, 404)
    try:
        g.c.execute("SELECT * FROM task_vw WHERE assignment_id=%s", (assignment_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    for task in tasks:
        if task['start_date']:
            raise InvalidUsage("Assignment %s has one or more started tasks" % assignment_id, 400)
    try:
        stmt = "UPDATE task SET assignment_id=NULL WHERE assignment_id = %s"
        bind = (assignment_id)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        for task in tasks:
            bind = (task['project_id'], assignment_id, task['key_type_id'], task['key_text'],
                    'Unassigned', task['user'])
            g.c.execute(WRITE['TASK_AUDIT'], bind)
        g.c.execute("DELETE from assignment WHERE id=%s", (assignment_id))
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>/start', methods=['OPTIONS', 'POST'])
def start_assignment_by_id(assignment_id): # pragma: no cover
    '''
    Start an assignment
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: assignment_id
        schema:
          type: string
        required: true
        description: assignment ID
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
    responses:
      200:
          description: Assignment started
      400:
          description: Assignment not started
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    ipd['id'] = assignment_id
    start_assignment(ipd, result)
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>/complete', methods=['OPTIONS', 'POST'])
def complete_assignment_by_id(assignment_id): # pragma: no cover
    '''
    Complete an assignment
    ---
    tags:
      - Assignment
    parameters:
      - in: query
        name: assignment_id
        schema:
          type: string
        required: true
        description: assignment ID
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
    responses:
      200:
          description: Assignment completed
      400:
          description: Assignment not completed
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    ipd['id'] = assignment_id
    assignment = get_assignment_by_id(ipd['id'])
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % ipd['id'], 404)
    if not assignment['start_date']:
        raise InvalidUsage("Assignment %s was not started" % ipd['id'], 400)
    if assignment['completion_date']:
        raise InvalidUsage("Assignment %s was already completed" % ipd['id'], 400)
    get_incomplete_assignment_tasks(assignment_id)
    start_time = int(assignment['start_date'].timestamp())
    end_time = int(time())
    duration = end_time - start_time
    working = working_duration(start_time, end_time)
    stmt = "UPDATE assignment SET completion_date=FROM_UNIXTIME(%s),disposition='Complete'," \
           + "duration=%s,working_duration=%s WHERE id=%s AND completion_date IS NULL"
    try:
        bind = (end_time, duration, working, ipd['id'],)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        publish_cdc(result, {"table": "assignment", "operation": "update"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if result['rest']['row_count'] == 0:
        raise InvalidUsage("Assignment %s was not updated" % (ipd['id']), 400)
    constructor = globals()[assignment['protocol'].capitalize()]
    projectins = constructor()
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(ipd['id'], result, 'assignment', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    g.db.commit()
    message = {"mad_id": assignment['id'], "user": assignment['user'],
               "start_time": start_time, "end_time": end_time,
               "duration": end_time - start_time, "working_duration": working,
               "type": assignment['protocol']}
    publish_kafka('assignment_complete', result, message)
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>/reset', methods=['OPTIONS', 'POST'])
def reset_assignment_by_id(assignment_id): # pragma: no cover
    '''
    Reset an assignment (remove start and completion times)
    ---
    tags:
      - Assignment
    parameters:
      - in: query
        name: assignment_id
        schema:
          type: string
        required: true
        description: assignment ID
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
    responses:
      200:
          description: Assignment reset
      400:
          description: Assignment not reset
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    assignment = get_assignment_by_id(assignment_id)
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % assignment_id, 404)
    if not assignment['start_date']:
        raise InvalidUsage("Assignment %s was not started" % assignment_id, 400)
    # Look for started tasks
    try:
        stmt = "SELECT id FROM task WHERE assignment_id=%s AND start_date IS NOT NULL"
        g.c.execute(stmt, (assignment_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if tasks:
        raise InvalidUsage("Found %s task(s) already started for assignment %s" \
                           % (len(tasks), assignment_id), 400)
    try:
        stmt = "UPDATE assignment SET start_date=NULL,completion_date=NULL " \
               + "WHERE id=%s"
        bind = (assignment_id,)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        publish_cdc(result, {"table": "assignment", "operation": "update"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if g.c.rowcount == 0:
        raise InvalidUsage("Assignment %s was not reset" % (ipd['name']), 404)
    # Remove from ElasticSearch
    remove_id_from_index(assignment_id, 'assignment_start-*', result)
    remove_id_from_index(assignment_id, 'assignment_complete-*', result)
    result['rest']['row_count'] = g.c.rowcount
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * Task endpoints                                                            *
# *****************************************************************************
@app.route('/tasks/<string:protocol>/<string:project_name>', methods=['OPTIONS', 'POST'])
def new_tasks_for_project(protocol, project_name):
    '''
    Generate one or more new tasks for a new or existing project
    Given a JSON payload containing specifics, generate new tasks for a
    new or existing project and return the task IDs.
    Parameters may be passed in as JSON.
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: protocol
        schema:
          type: string
        required: true
        description: protocol
      - in: path
        name: project_name
        schema:
          type: string
        required: true
        description: project name (or ID)
    responses:
      200:
          description: Assignment generated
      404:
          description: Assignment not generated
    '''
    result = initialize_result()
    # Get payload
    ipd = receive_payload(result)
    ipd['protocol'] = protocol
    ipd['project_name'] = project_name
    project = get_project_by_name_or_id(project_name)
    if not isinstance(ipd['keys'], (list)):
        raise InvalidUsage("Payload must be a JSON list of body IDs")
    if not project:
        insert_project(ipd, result)
        project = dict()
        project['id'] = result['rest']['inserted_id']
    constructor = globals()[protocol.capitalize()]
    projectins = constructor()
    for key in ipd['keys']:
        task = get_task_by_key(project['id'], projectins.unit, key)
        if task:
            raise InvalidUsage("Task exists for %s %s in project %s" \
                               % (projectins.unit, key, project['id']))
    result['tasks'] = dict()
    for key in ipd['keys']:
        bind = ('', project['id'], projectins.unit,
                str(key), result['rest']['user'],)
        try:
            g.c.execute(WRITE['INSERT_TASK'], bind)
            result['rest']['row_count'] += g.c.rowcount
            result['tasks'][key] = g.c.lastrowid
            bind = (project['id'], None, get_key_type_id(projectins.unit),
                    key, 'Inserted', result['rest']['user'])
            g.c.execute(WRITE['TASK_AUDIT'], bind)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
    return generate_response(result)


@app.route('/tasks/columns', methods=['GET'])
def get_task_columns():
    '''
    Get columns from task_vw table
    Show the columns in the task_vw table, which may be used to filter
    results for the /tasks and /task_ids endpoints.
    ---
    tags:
      - Task
    responses:
      200:
          description: Columns in task_vw table
    '''
    result = initialize_result()
    show_columns(result, "task_vw")
    return generate_response(result)


@app.route('/task_ids', methods=['GET'])
def get_task_ids():
    '''
    Get task IDs (with filtering)
    Return a list of task IDs. The caller can filter on any of the
    columns in the task_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). The returned list may be ordered by specifying a column with
    the _sort key. Multiple columns should be separated by a comma.
    ---
    tags:
      - Task
    responses:
      200:
          description: List of one or more task IDs
      404:
          description: Tasks not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM task_vw', 'temp'):
        result['data'] = []
        for col in result['temp']:
            result['data'].append(col['id'])
        del result['temp']
    return generate_response(result)


@app.route('/tasks/<string:task_id>', methods=['GET'])
def get_tasks_by_id(task_id):
    '''
    Get task information for a given ID
    Given an ID, return a row from the task_vw table. Specific columns
    from the task_vw table can be returned with the _columns key.
    Multiple columns should be separated by a comma.
    ---
    tags:
      - Task
    parameters:
      - in: path
        name: task_id
        schema:
          type: string
        required: true
        description: task ID
    responses:
      200:
          description: Information for one task
      404:
          description: Task ID not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM task_vw', 'data', task_id)
    return generate_response(result)


@app.route('/tasks', methods=['GET'])
def get_task_info():
    '''
    Get task information (with filtering)
    Return a list of tasks (rows from the task_vw table). The
    caller can filter on any of the columns in the task_vw table.
    Inequalities (!=) and some relational operations (&lt;= and &gt;=) are
    supported. Wildcards are supported (use "*"). Specific columns from the
    task_vw table can be returned with the _columns key. The returned
    list may be ordered by specifying a column with the _sort key. In both
    cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Task
    responses:
      200:
          description: List of information for one or more tasks
      404:
          description: Tasks not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM task_vw', 'data')
    return generate_response(result)


@app.route('/task/<string:task_id>/start', methods=['OPTIONS', 'POST'])
def start_task_by_id(task_id): # pragma: no cover
    '''
    Start a task
    ---
    tags:
      - Task
    parameters:
      - in: path
        name: task_id
        schema:
          type: string
        required: true
        description: task ID
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
    responses:
      200:
          description: Task started
      400:
          description: Task not started
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    ipd['id'] = task_id
    start_task(ipd, result)
    return generate_response(result)


@app.route('/task/<string:task_id>/complete', methods=['OPTIONS', 'POST'])
def complete_task_by_id(task_id): # pragma: no cover
    '''
    Complete a task
    ---
    tags:
      - Task
    parameters:
      - in: path
        name: task_id
        schema:
          type: string
        required: true
        description: task ID
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
    responses:
      200:
          description: Task completed
      400:
          description: Task not completed
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    ipd['id'] = task_id
    complete_task(ipd, result)
    return generate_response(result)


@app.route('/taskprops/columns', methods=['GET'])
def get_taskprop_columns():
    '''
    Get columns from task_property_vw table
    Show the columns in the task_property_vw table, which may be used to
    filter results for the /taskprops and /taskprop_ids endpoints.
    ---
    tags:
      - Task
    responses:
      200:
          description: Columns in task_prop_vw table
    '''
    result = initialize_result()
    show_columns(result, "task_property_vw")
    return generate_response(result)


@app.route('/taskprop_ids', methods=['GET'])
def get_taskprop_ids():
    '''
    Get task property IDs (with filtering)
    Return a list of task property IDs. The caller can filter on any of
    the columns in the task_property_vw table. Inequalities (!=) and
    some relational operations (&lt;= and &gt;=) are supported. Wildcards are
    supported (use "*"). The returned list may be ordered by specifying a
    column with the _sort key. Multiple columns should be separated by a
    comma.
    ---
    tags:
      - Task
    responses:
      200:
          description: List of one or more task property IDs
      404:
          description: Task properties not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM task_property_vw', 'temp'):
        result['data'] = []
        for rtmp in result['temp']:
            result['data'].append(rtmp['id'])
        del result['temp']
    return generate_response(result)


@app.route('/taskprops/<string:tid>', methods=['GET'])
def get_taskprops_by_id(tid):
    '''
    Get task property information for a given ID
    Given an ID, return a row from the task_property_vw table. Specific
    columns from the task_property_vw table can be returned with the
    _columns key. Multiple columns should be separated by a comma.
    ---
    tags:
      - Task
    parameters:
      - in: path
        name: tid
        schema:
          type: string
        required: true
        description: task property ID
    responses:
      200:
          description: Information for one task property
      404:
          description: Task property ID not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM task_property_vw', 'data', tid)
    return generate_response(result)


@app.route('/taskprops', methods=['GET'])
def get_taskprop_info():
    '''
    Get task property information (with filtering)
    Return a list of task properties (rows from the
    task_property_vw table). The caller can filter on any of the columns
    in the task_property_vw table. Inequalities (!=) and some relational
    operations (&lt;= and &gt;=) are supported. Wildcards are supported
    (use "*"). Specific columns from the task_property_vw table can be
    returned with the _columns key. The returned list may be ordered by
    specifying a column with the _sort key. In both cases, multiple columns
    would be separated by a comma.
    ---
    tags:
      - Task
    responses:
      200:
          description: List of information for one or more task
                       properties
      404:
          description: Task properties not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM task_property_vw', 'data')
    return generate_response(result)


# *****************************************************************************


if __name__ == '__main__':
    app.run(debug=True)
