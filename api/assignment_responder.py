''' assignment_responder.py
    REST API for assignment database
'''

from datetime import datetime, timedelta
from importlib import import_module, reload
import inspect
import json
from multiprocessing import Process
import os
import platform
import re
import sys
from time import mktime, time, sleep, strptime
import elasticsearch
from flask import (Flask, g, make_response, redirect, render_template, request,
                   send_file, jsonify, Response)
from flask.json import JSONEncoder
from flask_cors import CORS
from flask_swagger import swagger
import jwt
from kafka import KafkaProducer
from kafka.errors import KafkaError
import pymysql.cursors
import pymysql.err
import requests

import assignment_utilities
from assignment_utilities import (InvalidUsage, call_responder, check_permission, check_project,
                                  generate_sql, get_assignment_by_name_or_id,
                                  get_project_by_name_or_id, get_task_by_id,
                                  get_tasks_by_assignment_id, get_user_by_name, get_workday,
                                  neuprint_custom_query, random_string, return_tasks_json,
                                  sql_error, update_property,
                                  validate_user, working_duration)

# pylint: disable=W0611
from cell_type_validation import Cell_type_validation
from connection_validation import Connection_validation
from orphan_link import Orphan_link
from cleave import Cleave
from todo import Todo
from focused_merge import Focused_merge
from tasks import create_tasks_from_json, generate_tasks

# SQL statements
READ = {
    'ASSIGNMENT': "SELECT * FROM assignment_vw WHERE id=%s",
    'ASSIGNMENTN': "SELECT a.*,CONCAT(first,' ',last) AS user2 FROM assignment_vw a "
                   + "JOIN user u ON (u.name=a.user) WHERE a.name=%s",
    'CVREL': "SELECT subject,relationship,object FROM cv_relationship_vw "
             + "WHERE subject_id=%s OR object_id=%s",
    'CVTERMREL': "SELECT subject,relationship,object FROM "
                 + "cv_term_relationship_vw WHERE subject_id=%s OR "
                 + "object_id=%s",
    'ELIGIBLE_FOCUSED_MERGE': "SELECT * from focused_merge_task_vw WHERE "
                                     + "assignment_id IS NOT NULL AND start_date IS NULL "
                                     + "ORDER BY project,create_date",
    'ELIGIBLE_CELL_TYPE_VALIDATION': "SELECT * from cell_type_validation_task_vw WHERE "
                                     + "assignment_id IS NOT NULL AND start_date IS NULL "
                                     + "ORDER BY project,create_date",
    'ELIGIBLE_CONNECTION_VALIDATION': "SELECT * from connection_validation_task_vw WHERE "
                                      + "assignment_id IS NOT NULL AND start_date IS NULL "
                                      + "ORDER BY project,create_date",
    'ELIGIBLE_CLEAVE': "SELECT * from cleave_task_vw WHERE assignment_id IS NOT NULL "
                       + "AND start_date IS NULL ORDER BY project,create_date",
    'ELIGIBLE_ORPHAN_LINK': "SELECT * from orphan_link_task_vw WHERE assignment_id IS NOT NULL "
                            + "AND start_date IS NULL ORDER BY project,create_date",
    'ELIGIBLE_TODO': "SELECT * FROM todo_task_vw WHERE start_date IS NULL ORDER BY "
                     + "FIELD(priority,'high','medium','low'),todo_type",
    'GET_ASSOCIATION': "SELECT object FROM cv_term_relationship_vw WHERE "
                       + "subject=%s AND relationship='associated_with'",
    'PROJECTA': "SELECT t.user,CONCAT(first,' ',last) AS proofreader,assignment,t.disposition,"
                + "COUNT(1) AS num,a.start_date,a.completion_date,a.duration,"
                + "TIMEDIFF(NOW(),a.start_date) AS elapsed FROM task_vw t "
                + "JOIN user u ON (u.name=t.user) JOIN assignment_vw a ON (t.assignment_id=a.id) "
                + "WHERE t.project='%s' AND assignment_id IS NOT NULL GROUP BY 1,2,3,4,6,7,8,9",
    'PROJECTUA': "SELECT COUNT(1) AS num FROM task_vw WHERE project='%s' AND assignment_id IS NULL",
    'PSUMMARY': "SELECT t.protocol,p.project_group,t.project,p.active,COUNT(1) AS num,"
                + "p.disposition AS disposition,t.priority,p.create_date FROM task_vw t "
                + "JOIN project_vw p ON (p.id=t.project_id) "
                + "GROUP BY t.project,p.project_group,t.protocol "
                + "ORDER BY t.priority,t.protocol,p.create_date,p.project_group,t.project",
    'DVID_PROJECT_TASKS': "SELECT t.id,tp1.value AS result,tp2.value AS user FROM "
                          + "task_property_vw tp1 JOIN task_vw t ON (t.id=tp1.task_id "
                          + "AND tp1.type='dvid_result') JOIN task_property_vw tp2 "
                          + "ON (t.id=tp2.task_id AND tp2.type='dvid_user') "
                          + "WHERE project=%s ORDER BY 1",
    'TASK': "SELECT * FROM task_vw WHERE id=%s",
    'TASKS': "SELECT id,project,assignment,protocol,priority,start_date,completion_date,"
             + "disposition,SEC_TO_TIME(duration) AS duration FROM task_vw WHERE user=%s "
             + "AND assignment IS NOT NULL "
             + "ORDER BY start_date,priority,protocol,project,assignment,id",
    'TASKSDISP': "SELECT id,project,assignment,protocol,user,priority,start_date,completion_date,"
                 + "disposition,SEC_TO_TIME(duration) AS duration FROM task_vw WHERE "
                 + "disposition=%s AND assignment IS NOT NULL "
                 + "ORDER BY start_date,priority,protocol,project,assignment,id",
    'TASK_EXISTS': "SELECT * FROM task_vw WHERE project_id=%s AND key_type=%s AND key_text=%s",
    'UNASSIGNED_TASKS': "SELECT id,name,key_type_id,key_text FROM task WHERE project_id=%s AND "
                        + "assignment_id IS NULL ORDER BY id",
    'UPSUMMARY': "SELECT t.protocol,p.project_group,t.project,p.active,COUNT(1) AS num,t.priority "
                 + "FROM task_vw t JOIN project_vw p ON (p.id=t.project_id) WHERE "
                 + "assignment_id IS NULL GROUP BY t.project,p.project_group,t.protocol,t.priority "
                 + "ORDER BY t.priority,t.protocol,p.project_group,t.project",
}
WRITE = {
    'ASSIGN_TASK': "UPDATE task SET assignment_id=%s,user=%s WHERE assignment_id IS NULL AND id=%s",
    'COMPLETE_TASK': "UPDATE task SET completion_date=FROM_UNIXTIME(%s),disposition=%s,"
                     + "duration=%s,working_duration=%s WHERE id=%s AND completion_date IS NULL",
    'INSERT_ASSIGNMENT': "INSERT INTO assignment (name,project_id,user) VALUES(%s,"
                         + "%s,%s)",
    'INSERT_PROJECT': "INSERT INTO project (name,protocol_id,priority) VALUES(%s,"
                      + "getCvTermId('protocol',%s,NULL),%s)",
    'INSERT_CV': "INSERT INTO cv (name,definition,display_name,version,"
                 + "is_current) VALUES (%s,%s,%s,%s,%s)",
    'INSERT_CVTERM': "INSERT INTO cv_term (cv_id,name,definition,display_name"
                     + ",is_current,data_type) VALUES (getCvId(%s,''),%s,%s,"
                     + "%s,%s,%s)",
    'INSERT_USER': "INSERT INTO user (name,first,last,janelia_id,email,organization) "
                   + "VALUES (%s,%s,%s,%s,%s,%s)",
    'START_TASK': "UPDATE task SET start_date=NOW(),disposition=%s,user=%s WHERE id=%s "
                  + "AND start_date IS NULL",
    'TASK_AUDIT': "INSERT INTO task_audit (task_id,project_id,assignment_id,key_type_id,key_text,"
                  + "disposition,note,user) VALUES (%s,%s,%s,getCvTermId('key',%s,NULL),"
                  + "%s,%s,%s,%s)",
}


# pylint: disable=C0302,C0103,W0703

class CustomJSONEncoder(JSONEncoder):
    ''' Define a custom JSON encoder
    '''
    def default(self, obj):   # pylint: disable=E0202, W0221
        try:
            if isinstance(obj, datetime):
                return obj.strftime('%a, %-d %b %Y %H:%M:%S')
            if isinstance(obj, timedelta):
                seconds = obj.total_seconds()
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                seconds = seconds % 60
                return "%02d:%02d:%.2f" % (hours, minutes, seconds)
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)

__version__ = '0.20.2'
app = Flask(__name__, template_folder='templates')
app.json_encoder = CustomJSONEncoder
app.config.from_pyfile("config.cfg")
# Override Flask's usual behavior of sorting keys (interferes with prioritization)
app.config['JSON_SORT_KEYS'] = False
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
app.config['LAST_TRANSACTION'] = time()
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
        assignment_utilities.BEARER = assignment_utilities.CONFIG['neuprint']['bearer']
        try:
            g.c.execute("SELECT cv_term,display_name FROM cv_term_vw WHERE "
                        + "cv='protocol' ORDER BY 2")
            rows = g.c.fetchall()
        except Exception as err: # pragma: no cover
            temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
            mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
            raise InvalidUsage(mess, 500)
        for row in rows:
            app.config['PROTOCOLS'][row['cv_term']] = row['display_name']
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


def decode_token(token):
    ''' Decode a given JWT token
        Keyword arguments:
          token: JWT token
        Returns:
          decoded token JSON
    '''
    try:
        response = jwt.decode(token, 'k12Z1IwhNfBmIPEXR_T2pK9CF1s', algorithms='HS256')
    except jwt.ExpiredSignatureError:
        raise InvalidUsage("token is expired", 401)
    except jwt.InvalidSignatureError:
        raise InvalidUsage("Signature verification failed for token", 401)
    except Exception:
        raise InvalidUsage("Could not decode token", 500)
    return response


def initialize_result():
    ''' Initialize the result dictionary
        An auth header with a JWT token is required for all POST and DELETE requests
        Returns:
          decoded partially populated result dictionary
    '''
    result = {"rest": {'requester': request.remote_addr,
                       'url': request.url,
                       'endpoint': request.endpoint,
                       'error': False,
                       'elapsed_time': '',
                       'row_count': 0,
                       'pid': os.getpid()}}
    if 'Authorization' in request.headers:
        token = re.sub(r'Bearer\s+', '', request.headers['Authorization'])
        dtok = dict()
        # assignment_utilities.BEARER = token
        if token in app.config['AUTHORIZED']:
            authuser = app.config['AUTHORIZED'][token]
        else:
            dtok = decode_token(token)
            if not dtok or 'email' not in dtok:
                raise InvalidUsage('Invalid token used for authorization', 401)
            authuser = dtok['email']
            if not get_user_id(authuser):
                raise InvalidUsage('User %s is not known to the assignment_manager' % authuser)
            app.config['AUTHORIZED'][token] = authuser
        result['rest']['user'] = authuser
        app.config['USERS'][authuser] = app.config['USERS'].get(authuser, 0) + 1
    elif request.method in ['DELETE', 'POST'] or request.endpoint in app.config['REQUIRE_AUTH']:
        raise InvalidUsage('You must authorize to use this endpoint', 401)
    if app.config['LAST_TRANSACTION'] and time() - app.config['LAST_TRANSACTION'] \
       >= app.config['RECONNECT_SECONDS']:
        print("Seconds since last transaction: %d" % (time() - app.config['LAST_TRANSACTION']))
        g.db.ping()
    app.config['LAST_TRANSACTION'] = time()
    return result


def execute_sql(result, sql, container, query=False):
    ''' Build and execute a SQL statement.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
          container: name of dictionary in result disctionary to return rows
          query: uses "id" column if true
    '''
    # pylint: disable=W0603
    global IDCOLUMN
    sql, bind, IDCOLUMN = generate_sql(request, result, sql, query)
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
        Returns:
          fetched CV relationship data
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
        Returns:
          CV data list
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
        Returns:
          fgetched CV term relationship data
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
        Returns:
          CV term data list
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
        Returns:
          JSON response
    '''
    result['rest']['elapsed_time'] = str(timedelta(seconds=(time() - START_TIME)))
    return jsonify(**result)


def receive_payload(result):
    ''' Get a request payload (form or JSON).
        Keyword arguments:
          result: result dictionary
        Returns:
          payload dictionary
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
        response = projectins.cypher(result, ipd, app.config['NEUPRINT_SOURCE'])
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
        raise InvalidUsage("Project name must have at least one alphabetic character")
    try:
        bind = (ipd['project_name'], ipd['protocol'], ipd['priority'])
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
        raise InvalidUsage("Project name must have at least one alphabetic character")
    if app.config['DEBUG']:
        print("Generating %s project %s" % (protocol, ipd['project_name']))
    ipd['protocol'] = protocol
    # Is this a valid protocol?
    if not valid_cv_term('protocol', protocol):
        raise InvalidUsage("%s is not a valid protocol" % protocol)
    # Instattiate project
    constructor = globals()[protocol.capitalize()]
    projectins = constructor()
    # Create tasks in memory
    method = projectins.task_populate_method
    globals()[method](projectins, result, ipd)
    if not result['tasks']:
        return 1
    # We have tasks! Create a project (unless it already exists).
    project = get_project_by_name_or_id(ipd['project_name'])
    if project and not ('append' in ipd and ipd['append']):
        return 0
    existing_project = False
    if project:
        ipd['project_name'] = project['name']
        result['rest']['inserted_id'] = project['id']
        existing_project = True
        print("Project %s (ID %s) already exists" % (project['name'], project['id']))
    else:
        ipd['priority'] = ipd['priority'] if 'priority' in ipd else 10
        insert_project(ipd, result)
    # Add project properties from input parameters
    ipd['source'] = 'unknown' if 'source' not in ipd else ipd['source']
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(result['rest']['inserted_id'], 'project', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    # Add the filter as a project property
    update_property(result['rest']['inserted_id'], 'project', 'filter', json.dumps(ipd))
    result['rest']['row_count'] += g.c.rowcount
    # Insert tasks into the database
    if len(result['tasks']) > app.config['FOREGROUND_TASK_LIMIT']:
        g.db.commit()
        pro = Process(target=generate_tasks, args=(result, projectins.unit,
                                                   projectins.task_insert_props, existing_project))
        pro.start()
        result['rest']['tasks_inserted'] = -1
    else:
        generate_tasks(result, projectins.unit, projectins.task_insert_props, existing_project)
    return 1


def get_project_properties(project):
    ''' Get a project's properties
        Keyword arguments:
          project: project record
    '''
    pprops = []
    active = "<span style='color:%s'>%s</span>" \
             % (('lime', 'YES') if project['active'] else ('red', 'NO'))
    pprops.append(['Active:', active])
    pprops.append(['Protocol:', app.config['PROTOCOLS'][project['protocol']]])
    pprops.append(['Priority:', project['priority']])
    try:
        g.c.execute("SELECT type_display,value FROM project_property_vw WHERE name=%s"
                    "ORDER BY 1", (project['name'],))
        props = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    for prop in props:
        if not prop['value']:
            continue
        pprops.append([prop['type_display'], prop['value']])
    return pprops


def colorize_tasks(num_assigned, num_unassigned, num_tasks):
    ''' Colorize addigned and unassigned task percentages
        Keyword arguments:
          num_assigned: number of tasks assigned
          num_unassigned: number of tasks unassigned
          num_tasks: number of tasks
    '''
    dperc = '%.2f%%' % (num_assigned / num_tasks * 100.0)
    if not num_assigned:
        assignedt = '<span style="color:crimson">%s</span>' % (dperc)
    elif num_assigned == num_tasks:
        assignedt = '<span style="color:lime">%s</span>' % (dperc)
    else:
        assignedt = '<span style="color:gold">%s</span>' % (dperc)
    assignedt = '%d (%s)' % (num_assigned, assignedt)
    dperc = '%.2f%%' % (num_unassigned / num_tasks * 100.0)
    if not num_unassigned:
        unassignedt = '<span style="color:lime">%s</span>' % (dperc)
    elif num_unassigned == num_tasks:
        unassignedt = '<span style="color:crimson">%s</span>' % (dperc)
    else:
        unassignedt = '<span style="color:gold">%s</span>' % (dperc)
    unassignedt = '%d (%s)' % (num_unassigned, unassignedt)
    return assignedt, unassignedt


def generate_disposition_block(pid, num_assigned, num_unassigned):
    ''' Get a project task disposition block
        Keyword arguments:
          pid: project ID
          num_assigned: number of tasks assigned
          num_unassigned: number of tasks unassigned
        Returns:
          HTML disposition block
    '''
    disposition_block = ''
    try:
        g.c.execute("SELECT disposition,COUNT(1) AS c FROM task_vw WHERE project_id=%s "
                    + "AND assignment IS NOT NULL GROUP BY 1", pid)
        atasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    for row in atasks:
        dperc = "%.2f%%" % (row['c'] / (num_assigned + num_unassigned) * 100.0)
        if not row['disposition']:
            dperc = '<span style="color:gold">%s</span>' % (dperc)
        elif row['disposition'] == 'Complete':
            dperc = '<span style="color:lime">%s</span>' % (dperc)
        disposition_block += '<h4>%s: %d (%s)</h4>' \
                             % (('No activity' if not row['disposition'] else row['disposition']),
                                row['c'], dperc)
    return disposition_block


def generate_task_audit_list(task_id):
    ''' Genarate a list of audit records
        Keyword arguments:
          task_id: task ID
        Returns:
          list of audit records
    '''
    try:
        g.c.execute(("SELECT disposition,CONCAT(last,', ',first) AS user,note,t.create_date  FROM "
                     + "task_audit_vw t JOIN user u ON (t.user=u.name) WHERE task_id=%s "
                     + "ORDER BY 4") % (task_id))
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    audit = []
    last_date = ''
    for row in rows:
        if not last_date:
            elapsed = ''
        else:
            t1 = mktime(strptime(str(last_date), "%Y-%m-%d %H:%M:%S"))
            t2 = mktime(strptime(str(row['create_date']), "%Y-%m-%d %H:%M:%S"))
            elapsed = str(timedelta(seconds=(t2 - t1)))
        audit.append([row['disposition'], row['user'], row['note'], row['create_date'], elapsed])
        last_date = row['create_date']
    return audit


def get_assigned_tasks(tasks, pid, num_unassigned, user):
    ''' Get a project's tasks
        Keyword arguments:
          tasks: list of tasks
          pid: project ID
          num_unassigned: number of unassigned tasks
          user: user
    '''
    num_assigned = 0
    if tasks:
        permissions = check_permission(user)
        assigned = '''
        <table id="ttasks" class="tablesorter standard">
        <thead>
        <tr><th>User</th><th>Assignment</th><th>Disposition</th><th>Count</th><th>Started</th><th>Completed</th><th>Duration</th></tr>
        </thead>
        <tbody>
        '''
        template = '<tr class="%s">' + ''.join('<td>%s</td>')*2 \
                   + ''.join('<td style="text-align: center">%s</td>')*5 + "</tr>"
        for row in tasks:
            num_assigned += int(row['num'])
            link = '<a href="/assignment/%s">%s</a>' % (row['assignment'], row['assignment'])
            if 'admin' not in permissions and 'view' not in permissions and row['user'] != user:
                row['proofreader'] = '-'
                link = row['assignment']
            duration = ''
            if row['duration']:
                duration = row['duration']
            elif row['start_date']:
                duration = "<span style='color:orange'>%s</span>" % row['elapsed']
            rclass = 'complete' if row['disposition'] == 'Complete' else 'open'
            if not row['disposition']:
                rclass = 'notstarted'
            assigned += template % (rclass, row['proofreader'], link, row['disposition'],
                                    row['num'], row['start_date'], row['completion_date'],
                                    duration)
        assigned += "</tbody></table>"
    else:
        assigned = ''
    # Generate  disposition_block
    try:
        disposition_block = generate_disposition_block(pid, num_assigned, num_unassigned)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return assigned, num_assigned, disposition_block


def change_project_active(result, name_or_id, flag):
    ''' Change a project's active flag
        Keyword arguments:
          result: result dictionary
          name: project name or ID
          flag: 1 or 0 (activate or deactivate)
    '''
    column = 'id' if name_or_id.isdigit() else 'name'
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to suspend/activate projects")
    if not get_project_by_name_or_id(name_or_id):
        raise InvalidUsage("Project %s does not exist" % name_or_id, 404)
    stmt = "UPDATE project SET active=%s WHERE %s='%s'"
    bind = (flag, column, name_or_id)
    try:
        g.c.execute(stmt % bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    result['rest']['row_count'] = g.c.rowcount
    result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
    g.db.commit()


def change_project_priority(result, name_or_id, priority):
    ''' Change a project's priority
        Keyword arguments:
          result: result dictionary
          name: project name or ID
          priority: priority
    '''
    column = 'id' if name_or_id.isdigit() else 'name'
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to reprioritize projects")
    if not get_project_by_name_or_id(name_or_id):
        raise InvalidUsage("Project %s does not exist" % name_or_id, 404)
    stmt = "UPDATE project SET priority=%s WHERE %s='%s'"
    bind = (priority, column, name_or_id)
    try:
        g.c.execute(stmt % bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    result['rest']['row_count'] = g.c.rowcount
    result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
    g.db.commit()


def get_unassigned_project_tasks(ipd, project_id, num_tasks):
    ''' Get a list of unassigned tasks for a project
        Keyword arguments:
          ipd: request payload
          project_id: project ID
          num_tasks: number of tasks to assign
    '''
    try:
        print(READ['UNASSIGNED_TASKS'] % (project_id))
        g.c.execute(READ['UNASSIGNED_TASKS'], (project_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if not tasks:
        raise InvalidUsage("Project %s has no unassigned tasks" % ipd['project_name'], 404)
    if len(tasks) < num_tasks and not app.config['ALLOW_PARTIAL_ASSIGNMENTS']:
        raise InvalidUsage(("Project %s only has %s unassigned tasks, not %s" \
                            % (ipd['project_name'], len(tasks), num_tasks)), 404)
    return tasks


def project_summary_query(ipd):
    ''' Build a project summary query
        Keyword arguments:
          ipd: request payload
        Returns:
          SQL query
    '''
    sql = READ['PSUMMARY']
    clause = []
    if 'protocol' in ipd and ipd['protocol']:
        protocol_str = json.dumps(ipd['protocol']).strip('[]')
        clause.append(" t.protocol IN (%s)" % protocol_str)
    if 'start_date' in ipd and ipd['start_date']:
        clause.append(" DATE(p.create_date) >= '%s'" % ipd['start_date'])
    if 'stop_date' in ipd and ipd['stop_date']:
        clause.append(" DATE(p.create_date) <= '%s'" % ipd['stop_date'])
    if clause:
        where = ' AND '.join(clause)
        sql = sql.replace('GROUP BY', 'WHERE ' + where + ' GROUP BY')
    return sql


def assignment_query(ipd):
    ''' Build an assignment query
        Keyword arguments:
          ipd: request payload
        Returns:
          SQL query
    '''
    sql = "SELECT * from project_stats_vw"
    clause = []
    if 'protocol' in ipd and ipd['protocol']:
        protocol_str = json.dumps(ipd['protocol']).strip('[]')
        clause.append(" protocol IN (%s)" % protocol_str)
    if 'proofreader' in ipd and ipd['proofreader']:
        proofreader_str = json.dumps(ipd['proofreader']).strip('[]')
        clause.append(" user IN (%s)" % proofreader_str)
    if 'start_date' in ipd and ipd['start_date']:
        clause.append(" DATE(create_date) >= '%s'" % ipd['start_date'])
    if 'stop_date' in ipd and ipd['stop_date']:
        clause.append(" DATE(create_date) <= '%s'" % ipd['stop_date'])
    if clause:
        sql += ' AND '.join(clause)
        sql = sql.replace('project_stats_vw', 'project_stats_vw WHERE ')
    return sql


def get_incomplete_assignment_tasks(assignment_id):
    ''' Get a list of completed tasks for an assignment
        Keyword arguments:
          assignment_id: assignment ID
    '''
    try:
        stmt = "SELECT id FROM task WHERE assignment_id=%s AND completion_date IS NULL"
        print(stmt % (assignment_id))
        g.c.execute(stmt, (assignment_id))
        return g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def select_user(project, ipd, result):
    ''' Select a user to assign to.
        Keyword arguments:
          project: project instance
          ipd: request payload
          result: result dictionary
        Returns:
          User name
    '''
    if 'user' in ipd:
        # On behalf of
        if not check_permission(result['rest']['user'], 'admin'):
            raise InvalidUsage("You don't have permission to assign jobs")
        assignment_user, janelia_id = validate_user(ipd['user'])
        workday = get_workday(janelia_id)
        need_permission = workday['organization']
        if ipd['user'] != result['rest']['user']:
            if not check_permission(result['rest']['user'], need_permission):
                raise InvalidUsage("You don't have permission to assign jobs to %s"
                                   % (need_permission))
    else:
        assignment_user, janelia_id = validate_user(result['rest']['user'])
    if not check_permission(assignment_user, project['protocol']):
        raise InvalidUsage("%s doesn't have permission to process %s assignments"
                           % (assignment_user, project['protocol']))
    return assignment_user


def get_assignment_controls(assignment, num_tasks, tasks_started, user, user_rows):
    ''' Generate controls for assignment web page
        Keyword arguments:
          assignment: assignment instance
          num_tasks: number of tasks
          tasks_started: number of started tasks
          user: calling user
          user_rows: users to reassign to
        Returns:
          HTML controls
    '''
    controls = ''
    if not tasks_started and check_permission(user, 'admin'):
        if assignment['start_date']:
            controls += '''
            <button type="button" class="btn btn-warning btn-sm" onclick='modify_assignment(%s,"reset");'>Reset assignment</button>
            '''
            controls = controls % (assignment['id'])
    if num_tasks > tasks_started and check_permission(user, 'admin'):
        controls += '''
        <button type="button" class="btn btn-danger btn-sm" onclick='modify_assignment(%s,"deleted");'>Remove unstarted tasks</button>
        '''
        controls = controls % (assignment['id'])
        controls += '''
        <button style="margin-left:20px" type="button" class="btn btn-warning btn-sm" onclick='reassign(%s);'>Reassign to</button>
        <select id="proofreader">
        '''
        controls = controls % (assignment['id'])
        for row in user_rows:
            if row['name'] != assignment['user']:
                controls += '<option value="%s">%s</option>' \
                    % (row['name'], row['proofreader'])
        controls += '</select>'
    return controls


def build_protocols_table(calling_user, user):
    ''' Generate a user protocol table.
        Keyword arguments:
          caslling_user: calling user
          user: user instance
    '''
    permissions = user['permissions'].split(',') if user['permissions'] else []
    # Protocols
    g.c.execute("SELECT cv_term,display_name FROM cv_term_vw WHERE cv='protocol' ORDER BY 1")
    rows = g.c.fetchall()
    parray = []
    template = '<tr><td style="width:300px">%s</td><td style="text-align: center">%s</td></tr>'
    for row in rows:
        display = row['display_name']
        if row['cv_term'] in sys.modules:
            val = 'checked="checked"' if row['cv_term'] in permissions else ''
            check = '<input type="checkbox" %s id="%s" onchange="changebox(this);">' \
                    % (val, row['cv_term'])
        else:
            display = '<span style="color:#666;text-decoration:line-through;">%s</span>' % display
            check = '<input type="checkbox" disabled>'
        if row['cv_term'] in permissions:
            permissions.remove(row['cv_term'])
        parray.append(template % (display, check))
    ptable = '<table><thead><tr style="color:#069"><th>Protocol</th>' \
             + '<th>Enabled</th></tr></thead><tbody>' \
             + ''.join(parray) + '</tbody></table>'
    # Administrative
    parray = []
    disabled = '' if check_permission(calling_user, ['admin', 'super']) else 'disabled'
    for special in ['admin', 'view']:
        val = 'checked="checked"' if special in permissions else ''
        check = '<input type="checkbox" %s id="%s" %s onchange="changebox(this);">' \
                % (val, special, disabled)
        parray.append(template % (special, check))
    ptable += '<table><thead><tr style="color:#069"><th>Permission</th>' \
              + '<th>Enabled</th></tr></thead><tbody>' \
              + ''.join(parray) + '</tbody></table>'
    # Assignment groups
    parray = []
    for perm in app.config['GROUPS']:
        val = 'checked="checked"' if perm in permissions else ''
        check = '<input type="checkbox" %s id="%s" onchange="changebox(this);">' \
                % (val, perm)
        parray.append(template % (perm, check))
    ptable += '<table><thead><tr style="color:#069"><th>Assignment groups</th>' \
              + '<th>Enabled</th></tr></thead><tbody>' \
              + ''.join(parray) + '</tbody></table>'
    return ptable


def protocol_select_list(result):
    ''' Return valid protocols as options for a <select>
        Keyword arguments:
          result: result dictionary
    '''
    execute_sql(result, "SELECT cv_term FROM cv_term_vw WHERE cv='protocol' ORDER BY 1", 'temp')
    protocols = ''
    for row in result['temp']:
        if bool(row['cv_term'] in sys.modules):
            protocols += '<option value="%s" SELECTED>%s</option>' \
                % (row['cv_term'], app.config['PROTOCOLS'][row['cv_term']])
    return protocols


def process_optional_parms(projectins, filt, filtjs):
    ''' Return filters and optional parameter HTML
        Keyword arguments:
          projectins: project instance
          filt: filter HTML
          filtjs: filter JavaScript
        Returns:
          filt: filter HTML
          filtjs: filter JavaScript
          optional: optional HTML
          optionaljs: optional JavaScript
    '''

    optional = optionaljs = ''
    for opt in projectins.optional_properties:
        if opt in ['roi', 'source']:
            continue
        if opt == 'status':
            filt += '<div class="grid-item">Select statuses:</div><div class="grid-item">' \
                        + '<select id="status" class="selectpicker" multiple ' \
                        + 'data-live-search="true" onchange="create_project(1);">'
            payload = "MATCH (n:`%s-Neuron`) RETURN DISTINCT n.statusLabel" \
                      % (app.config['DATASET'].lower())
            statuses = neuprint_custom_query(payload)
            rlist = [i[0] for i in statuses['data'] if i[0]]
            rlist.sort()
            for stat in rlist:
                filt += '<option>%s</option>' % stat
            filt += '</select></div>'
            filtjs += "if ($('#status').val()) {array['status'] = " \
                          + "$('#status').val().join(','); }"
            continue
        optional += '<div class="grid-item">%s:</div><div class="grid-item"><input id="%s"></div>' \
                    % (opt, opt)
        optionaljs += "if ($('#%s').val()) { array['%s'] = $('#%s').val(); }\n" % (opt, opt, opt)
    return filt, filtjs, optional, optionaljs


def process_projectparms(projectins, protocol):
    ''' Return filters and requied/optional parameter HTML
        Keyword arguments:
          projectins: project instance
    '''
    required = filt = filtjs = ''
    # ROI is required for NeuPrint queries
    if projectins.task_populate_method == 'query_neuprint':
        filt += '<div class="grid-item">Select ROIs:</div><div class="grid-item">' \
                + '<select id="roi" class="selectpicker" multiple data-live-search="true"' \
                + ' onchange="create_project(1);">'
        #payload = "MATCH (n:Meta:%s) RETURN n.superLevelRois" % (app.config['DATASET'].lower())
        payload = "MATCH (n:%s_Meta) RETURN n.superLevelRois" % (app.config['DATASET'].lower())
        rois = neuprint_custom_query(payload)
        rlist = rois['data'][0][0]
        rlist.sort()
        for roi in rlist:
            filt += '<option>%s</option>' % roi
        filt += '</select></div>'
    elif projectins.task_populate_method == 'json_upload':
        with open('static/%s.html' % (protocol)) as PJSON:
            json_content = PJSON.read()
        PJSON.close()
        required += '''
        <div class="grid-item">JSON string<a class="infolink" data-toggle="modal" data-target="#jsonModal"></a>:</div>
        <div class="grid-item"><textarea class="form-control" id="input_json" rows="5"></textarea></div>
        <div class="modal fade" id="jsonModal" tabindex="-1" role="dialog" aria-labelledby="exampleModalLabel" aria-hidden="true">
        <div class="modal-dialog" role="document">
        <div class="modal-content">
        <div class="modal-header">
        <h5 class="modal-title" id="exampleModalLabel">%s</h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
          <span aria-hidden="true">&times;</span>
        </button>
        </div>
        <div class="modal-body">%s</div>
        <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
        </div>
        </div>
        </div>
        </div>
        '''
        required = required % (protocol, json_content)
    required += '''
    <div class="grid-item">Priority:</div>
    <div class="grid-item"><input id="slider" width="300" value="10"/><span style="font-size:14pt; color:#fff;" id="priority"></span> (1-50; 1=highest)</div>
    </div>
    <script>
      $('#slider').slider({
        uiLibrary: 'bootstrap4',
        min: 1, max: 50, value: 10,
        slide: function (e, value) {
          document.getElementById('priority').innerText = value;
        }
      });
    </script>
    '''
    # Optional parameters
    filt, filtjs, optional, optionaljs = process_optional_parms(projectins, filt, filtjs)
    # Filter parameters
    for fil in projectins.allowable_filters:
        filt += '<div class="grid-item">%s:</div><div class="grid-item"><input id="%s" ' \
                % (fil, fil) + 'onchange="create_project(1);""></div>'
        filtjs += "if ($('#%s').val()) { array['%s'] = $('#%s').val(); }\n" % (fil, fil, fil)
    if filt:
        filt = '<h4>Search filters:</h4><div class="grid-container" width="500">' + filt + '</div>'
    return required, optional, optionaljs, filt, filtjs


def get_user_metrics(mtype, uname, user_org='user'):
    ''' Return a table of user/organization metrics
        Keyword arguments:
          mtype: "assignment" or "task"
          uname: user
        Returns:
          HTML content
    '''
    if user_org == 'user':
        stmt = 'SELECT protocol,disposition,COUNT(1) AS c,SEC_TO_TIME(AVG(working_duration)) ' \
               + 'AS a FROM ' + mtype + '_vw WHERE user=%s GROUP BY 1,2'
    else:
        if uname == 'All organizations':
            stmt = 'SELECT protocol,disposition,COUNT(1) AS c,SEC_TO_TIME(AVG(working_duration)) ' \
                   + 'AS a FROM ' + mtype + '_vw t GROUP BY 1,2'
        else:
            stmt = 'SELECT protocol,disposition,COUNT(1) AS c,SEC_TO_TIME(AVG(working_duration)) ' \
                   + 'AS a FROM ' + mtype + '_vw t JOIN user u ON (u.name=t.user ' \
                   + 'AND organization=%s) GROUP BY 1,2'
    try:
        if uname == 'All organizations':
            g.c.execute(stmt)
        else:
            g.c.execute(stmt, (uname,))
        rows = g.c.fetchall()
    except Exception as err:
        raise ValueError(sql_error(err))
    content = '<br><h2>No %ss found</h2>' % (mtype, )
    template = '<tr>' + ''.join("<td>%s</td>")*2 \
               + ''.join('<td style="text-align: center">%s</td>')*2 + "</tr>"

    if rows:
        content = '''
        <br><h2>%ss</h2>
        <table id="%ss" class="tablesorter standard">
        <thead>
        <tr><th>Protocol</th><th>Disposition</th><th>Count</th><th>Average working duration</th></tr>
        </thead>
        <tbody>
        '''
        content = content % (mtype.capitalize(), mtype, )
        for row in rows:
            row['a'] = row['a'] if row['a'] else '-'
            content += template % (app.config['PROTOCOLS'][row['protocol']], \
                                   row['disposition'], row['c'], row['a'])
        content += '</tbody></table>'
    return content


def generate_assignment(ipd, result):
    ''' Generate and persist an assignment and update its tasks.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    # Find the project
    project = get_project_by_name_or_id(ipd['project_name'])
    check_project(project, ipd)
    try:
        assignment_user = select_user(project, ipd, result)
    except Exception as err:
        raise err
    ipd['project_name'] = project['name']
    constructor = globals()[project['protocol'].capitalize()]
    projectins = constructor()
    if 'tasks' in ipd:
        num_tasks = int(ipd['tasks'])
    else:
        num_tasks = projectins.num_tasks
    tasks = get_unassigned_project_tasks(ipd, project['id'], num_tasks)
    try:
        bind = (ipd['name'], project['id'], assignment_user)
        g.c.execute(WRITE['INSERT_ASSIGNMENT'], bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['inserted_id'] = g.c.lastrowid
        result['rest']['inserted_name'] = ipd['name']
        result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_ASSIGNMENT'], bind)
        publish_cdc(result, {"table": "assignment", "operation": "insert"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(result['rest']['inserted_id'], 'assignment', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    updated = 0
    if len(tasks) < num_tasks:
        num_tasks = len(tasks)
    print("Assigned %s to %s" % (ipd['name'], assignment_user))
    for task in tasks:
        try:
            bind = (result['rest']['inserted_id'], assignment_user, task['id'])
            g.c.execute(WRITE['ASSIGN_TASK'], bind)
            result['rest']['row_count'] += g.c.rowcount
            updated += 1
            publish_cdc(result, {"table": "assignment", "operation": "update"})
            bind = (task['id'], project['id'], result['rest']['inserted_id'], projectins.unit,
                    task['key_text'], 'Assigned', None, assignment_user)
            g.c.execute(WRITE['TASK_AUDIT'], bind)
            if updated >= num_tasks:
                break
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    if updated != num_tasks:
        raise InvalidUsage("Could not assign tasks for project %s" % ipd['project_name'], 500)
    result['rest']['assigned_tasks'] = updated
    if 'start' in ipd and ipd['start']:
        ipd['id'] = str(result['rest']['inserted_id'])
        start_assignment(ipd, result)
    g.db.commit()


def start_assignment(ipd, result):
    ''' Start a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    assignment = get_assignment_by_name_or_id(ipd['id'])
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % ipd['id'], 404)
    ipd['id'] = assignment['id']
    if assignment['start_date']:
        raise InvalidUsage("Assignment %s was already started" % ipd['id'])
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
            update_property(ipd['id'], 'assignment', parm, ipd[parm])
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


def update_project_disposition(project_name, disposition='Complete'):
    ''' If all tasks in a project have been completed, mark the project as complete
        Keyword arguments:
          project_name: project name
          disposition: disposition [Complete]
    '''
    g.c.execute("SELECT COUNT(1) AS c FROM task_vw WHERE project=%s AND completion_date IS NULL",
                project_name)
    row = g.c.fetchone()
    if not row['c']:
        try:
            g.c.execute("UPDATE project SET disposition=%s WHERE "
                        + "name=%s", (disposition, project_name,))
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)


def complete_assignment(ipd, result, assignment, incomplete_okay=False):
    ''' Start a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
          assignment: assignment record
          incomplete_okay: return if incomplete tasks are found
    '''
    incomplete = get_incomplete_assignment_tasks(assignment['id'])
    if incomplete:
        message = "Found %s task(s) not yet complete for assignment %s" \
                  % (len(incomplete), assignment['id'])
        if incomplete_okay:
            result['rest']['note'] = message
            return
        raise InvalidUsage(message)
    start_time = int(assignment['start_date'].timestamp())
    end_time = int(time())
    working = working_duration(start_time, end_time)
    stmt = "UPDATE assignment SET completion_date=FROM_UNIXTIME(%s),disposition='Complete'," \
           + "duration=%s,working_duration=%s WHERE id=%s AND completion_date IS NULL"
    try:
        bind = (end_time, end_time - start_time, working, assignment['id'],)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        publish_cdc(result, {"table": "assignment", "operation": "update"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if result['rest']['row_count'] == 0:
        raise InvalidUsage("Assignment %s was not updated" % (assignment['id']))
    constructor = globals()[assignment['protocol'].capitalize()]
    projectins = constructor()
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(assignment['id'], 'assignment', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    update_project_disposition(assignment['project'])
    g.db.commit()
    message = {"mad_id": assignment['id'], "user": assignment['user'],
               "start_time": start_time, "end_time": end_time,
               "duration": end_time - start_time, "working_duration": working,
               "type": assignment['protocol']}
    publish_kafka('assignment_complete', result, message)


def build_assignment_table(user, ipd): # pylint: disable=R0914
    ''' Get a list of all assignments and return as a table.
        Also return a dictionary of proofreaders and protocols.
        Keyword arguments:
          user: proofreader
          start: start date
          stop: stop date
        Returns:
          Dictionary of proofreaders
          Assignments HTML
    '''
    proofreaders = ''
    try:
        g.c.execute("SELECT name,CONCAT(last,', ',first) AS proofreader FROM user ORDER BY 2")
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    permission = check_permission(user, ['admin', 'view'])
    for row in rows:
        if permission or row['name'] == user:
            proofreaders += '<option value="%s">%s</option>' \
                % (row['name'], row['proofreader'])
    if not permission:
        ipd['proofreader'] = user
    sql = assignment_query(ipd)
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if rows:
        header = ['Proofreader', 'Project', 'Protocol', 'Assignment', 'Started', 'Completed',
                  'Task disposition', 'Task count', 'Export']
        assignments = '''
        <table id="assignments" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        assignments += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*6 \
                   + ''.join('<td style="text-align: center">%s</td>')*3 + "</tr>"
        del header[-1]
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*8) + "\n"
        for row in rows:
            rclass = 'complete' if row['task_disposition'] == 'Complete' else 'open'
            if not row['task_disposition']:
                rclass = 'notstarted'
            proj = '<a href="/project/%s">%s</a>' % (row['project'], row['project'])
            assn = '<a href="/assignment/%s">%s</a>' % (row['assignment'], row['assignment'])
            this_protocol = app.config['PROTOCOLS'][row['protocol']]
            link = '<a class="text-info" href="/assignment/json/%s" ' \
                   % (row['assignment']) + '>JSON</a>'
            assignments += template % (rclass, row['proofreader'], proj, this_protocol,
                                       assn, row['start_date'], row['completion_date'],
                                       row['task_disposition'], row['tasks'], link)
            fileoutput += ftemplate % (row['proofreader'], row['project'], this_protocol,
                                       row['assignment'], row['start_date'], row['completion_date'],
                                       row['task_disposition'], row['tasks'])
        assignments += "</tbody></table>"
        downloadable = create_downloadable('assignments', header, ftemplate, fileoutput)
        assignments = '<a class="btn btn-outline-info btn-sm" href="/download/%s" ' \
                      % (downloadable) + 'role="button">Download table</a>' + assignments
    else:
        assignments = "There are no open assignments"
    return proofreaders, assignments


def create_assignment_from_tasks(project, assignment_name, ipd, result):
    ''' Coreat an assignment from a list of tasks
        Keyword arguments:
          project: project instance
          assignment_name: assignment
          ipd: request payload
          result: result dictionary
        Returns:
          assignment ID
    '''
    try:
        this_user = select_user(project, ipd, result)
    except Exception as err:
        raise err
    bind = (assignment_name, project['id'], this_user)
    try:
        g.c.execute(WRITE['INSERT_ASSIGNMENT'], bind)
        result['rest']['row_count'] += g.c.rowcount
        result['rest']['inserted_id'] = assignment_id = g.c.lastrowid
        result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_ASSIGNMENT'], bind)
        publish_cdc(result, {"table": "assignment", "operation": "insert"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return assignment_id, this_user


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


def add_point(ipd, key, result):
    ''' Add a point to a started task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    payload = {"cypher" : "MATCH (n :`" + app.config['NEUPRINT_SOURCE'] + "` {bodyId: "
                          + str(key) + "})-[:Contains]->(ss :SynapseSet)-[:Contains]->(s :Synapse) "
                          + "RETURN s.location LIMIT 1"}
    result['rest']['cypher'] = payload['cypher']
    try:
        response = call_responder('neuprint', 'custom/custom', payload)
    except Exception as err:
        print(err)
        return "Couldn't call NeuPrint"
    if 'data' in response:
        if not response['data']:
            return "No entry in NeuPrint for %s" % (key)
        point = json.dumps(response['data'][0][0]['coordinates'])
        update_property(ipd['id'], 'task', 'coordinates', point)
        result['rest']['row_count'] += g.c.rowcount
    return False


def parse_tasks(ipd):
    ''' Parse tasks from inoput JSON
        Keyword arguments:
          ipd: request payload
        Returns:
          error message (or None if no errors)
    '''
    if 'tasks' in ipd:
        if not isinstance(ipd['tasks'], (dict)):
            return "tasks payload must be a JSON dictionary"
    else:
        return "No tasks found in JSON payload"
    return None


def call_task_parser(projectins, ipd):
    ''' Call the appropriate task parser
        Keyword arguments:
          projectins: project instance
          ipd: request payload
        Returns:
          error message (or None if no errors)
    '''
    if hasattr(projectins, 'parse_tasks'):
        error = projectins.parse_tasks(ipd)
    else:
        error = parse_tasks(ipd)
    return error



def check_task(task, ipd, result):
    ''' Check to ensure that a task exists and can be changed by the current user.
        Keyword arguments:
          task: task instance
          ipd: request payload
          result: result dictionary
    '''
    if not task:
        raise InvalidUsage("Task %s does not exist" % ipd['id'], 404)
    if not check_permission(result['rest']['user'], 'admin'):
        if task['user'] != result['rest']['user']:
            raise InvalidUsage("Task %s is assigned to %s, not %s"
                               % (task['id'], task['user'], result['rest']['user']))


def update_task(task, ipd, this_user, result):
    ''' Start a task.
        Keyword arguments:
          task: task record
          ipd: request payload
          this_user: task user
          result: result dictionary
    '''
    disposition = 'In progress'
    if 'disposition' in ipd:
        disposition = ipd['disposition']
        if not valid_cv_term('disposition', disposition):
            raise InvalidUsage("%s is not a valid disposition" % disposition)
    if not this_user:
        this_user = task['user']
    try:
        bind = (disposition, this_user, ipd['id'],)
        g.c.execute(WRITE['START_TASK'], bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(WRITE['START_TASK'], bind)
        publish_cdc(result, {"table": "task", "operation": "update"})
        bind = (ipd['id'], task['project_id'], task['assignment_id'], task['key_type'],
                task['key_text'], 'In progress', None, this_user)
        g.c.execute(WRITE['TASK_AUDIT'], bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def start_task(ipd, result, this_user=None):
    ''' Start a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
          this_user: task user
    '''
    task = get_task_by_id(ipd['id'])
    check_task(task, ipd, result)
    project = get_project_by_name_or_id(task['project_id'])
    if not project['active']:
        raise InvalidUsage("Project %s is not active" % project['name'])
    constructor = globals()[project['protocol'].capitalize()]
    projectins = constructor()
    if task['start_date']:
        raise InvalidUsage("Task %s was already started" % ipd['id'])
    if not hasattr(projectins, 'no_assignment'):
        if not task['assignment_id']:
            raise InvalidUsage("Task %s is not assigned" % ipd['id'])
        # Check the asignment
        assignment = get_assignment_by_name_or_id(task['assignment_id'])
        if not assignment['start_date']:
            start_assignment({"id": task['assignment_id']}, result)
    # Update the task
    update_task(task, ipd, this_user, result)
    # Add optional properties
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(ipd['id'], 'task', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    if projectins.unit == 'body_id':
        # Add a point
        ret = add_point(ipd, task['key_text'], result)
        if ret:
            print(ret)
            #raise InvalidUsage(ret)


def call_dvid(protocol, body):
    ''' Get results from DVID
        Keyword arguments:
          protocol: protocol
          body: body ID
        Returns:
          JSON
    '''
    if protocol != 'cell_type_validation':
        return None
    dresult = call_responder('dvid-' + app.config['DATASET'].lower(), 'api/node/' \
                             + app.config['DVID_ROOT_UUID'] + ':master' \
                             + '/segmentation_cellTypeValidation/key/' \
                             + body)
    return dresult

def add_dvid_results(task):
    ''' Add DVID results to a task
        Keyword arguments:
          task: task dictionary
    '''
    dresult = call_dvid(task['protocol'], task['key_text'])
    dres = dresult['result'] if 'result' in dresult else 'unknown'
    if dres == 'unknown' and 'skipped' in dresult:
        dres = dresult['skipped']
    update_property(task['id'], 'task', 'dvid_result', dres)
    dres = dresult['user'] if 'user' in dresult else 'unknown'
    update_property(task['id'], 'task', 'dvid_user', dres)


def complete_task(ipd, result):
    ''' Complete a task.
        Keyword arguments:
          ipd: request payload
          result: result dictionary
    '''
    task = get_task_by_id(ipd['id'])
    check_task(task, ipd, result)
    project = get_project_by_name_or_id(task['project_id'])
    if not project['active']:
        raise InvalidUsage("Project %s is not active" % project['name'])
    constructor = globals()[project['protocol'].capitalize()]
    projectins = constructor()
    if not task['start_date']:
        raise InvalidUsage("Task %s was not started" % ipd['id'])
    if task['completion_date']:
        raise InvalidUsage("Task %s was already completed" % ipd['id'])
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
            raise InvalidUsage("%s is not a valid disposition" % disposition)
    try:
        bind = (end_time, disposition, duration, working, ipd['id'],)
        g.c.execute(WRITE['COMPLETE_TASK'], bind)
        result['rest']['row_count'] = g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(WRITE['COMPLETE_TASK'], bind)
        publish_cdc(result, {"table": "task", "operation": "update"})
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    bind = (ipd['id'], task['project_id'], task['assignment_id'], task['key_type'],
            task['key_text'], disposition, None, task['user'])
    g.c.execute(WRITE['TASK_AUDIT'], bind)
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(ipd['id'], 'task', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    if project['protocol'] == 'cell_type_validation':
        add_dvid_results(task)
    # If this is the last task, complete the assignment
    assignment = get_assignment_by_name_or_id(task['assignment_id'])
    complete_assignment(ipd, result, assignment, True)


def get_task_properties(result):
    ''' Add task properties to tasks
        Keyword arguments:
          result: result dictionary
    '''
    result['data'] = list()
    for task in result['temp']:
        task['properties'] = dict()
        try:
            g.c.execute("SELECT type,value FROM task_property_vw WHERE task_id=%s", task['id'])
            rows = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        for row in rows:
            task['properties'][row['type']] = row['value']
        result['data'].append(task)


def build_task_table(aname):
    ''' Build a table of an assignment's tasks
        Keyword arguments:
          aname: assignment name
    '''
    try:
        g.c.execute("SELECT key_type_display,id,key_text,create_date,start_date,"
                    + "completion_date,disposition,duration,"
                    + "TIMEDIFF(NOW(),start_date) AS elapsed FROM task_vw WHERE "
                    + "assignment=%s ORDER BY id", (aname,))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    tasks = """
    <table id="tasks" class="tablesorter standard">
    <thead>
    <tr><th>ID</th><th>%s</th><th>Created</th><th>Disposition</th><th>Started</th><th>Completed</th><th>Duration</th></tr>
    </thead>
    <tbody>
    """
    tasks = tasks % rows[0]['key_type_display']
    template = '<tr class="%s">' + ''.join('<td style="text-align: center">%s</td>')*7 + "</tr>"
    num_tasks = tasks_started = 0
    for row in rows:
        num_tasks += 1
        if row['start_date']:
            tasks_started += 1
        duration = ''
        if row['duration'] or (str(row['duration']) == '0:00:00'):
            duration = row['duration']
        elif row['start_date']:
            duration = "<span style='color:orange'>%s</span>" % row['elapsed']
        id_link = '<a href="/task/%s">%s</a>' % (row['id'], row['id'])
        rclass = 'complete' if row['completion_date'] else 'open'
        if not row['disposition']:
            rclass = 'notstarted'
        tasks += template % (rclass, id_link, row['key_text'], row['create_date'],
                             row['disposition'], row['start_date'], row['completion_date'],
                             duration)
    tasks += "</tbody></table>"
    return tasks, num_tasks, tasks_started


def get_task_controls(user, task_id, task):
    ''' Generate controls for task web page
        Keyword arguments:
          user: calling user
          task_id: task ID
          task: task instance
        Returns:
          HTML controls
    '''
    if not check_permission(user, 'admin'):
        return ''
    controls = '<br>'
    if not task['start_date']:
        controls += '''
        <button type="button" class="btn btn-warning btn-sm" onclick='modify_task(%s,"start");'>Start task</button>
        '''
        controls = controls % (task_id)
    else:
        if not task['completion_date']:
            controls += '''
            <button type="button" class="btn btn-warning btn-sm" style="margin-right:20px" onclick='modify_task(%s,"complete");'>Complete task</button>
            '''
            controls = controls % (task_id)
            try:
                g.c.execute("SELECT cv_term FROM cv_term_vw WHERE cv='disposition'")
                rows = g.c.fetchall()
            except Exception as err:
                raise err
            controls += 'Disposition: <select id="disposition" style="margin-right: 20px">'
            for row in rows:
                if row['cv_term'] not in ['In progress']:
                    controls += '<option>%s</option>' % (row['cv_term'])
            controls += '</select>Note: <input id="note" size=40>'
    return controls


def dvid_result_button(protocol, body):
    ''' Generate a button to display a DVID record modal window
        Keyword arguments:
          protocol: protocol
          body: body ID
        Returns:
          link
    '''
    dresult = call_dvid(protocol, body)
    if not dresult:
        return '(not available)'
    content = json.dumps(dresult, sort_keys=True, indent=4)
    html = '''
    <button type="button" class="btn btn-outline-info btn-sm" data-toggle="modal" data-target="#dvid_modal">View</button>
    <div id="dvid_modal" class="modal" tabindex="-1" role="dialog">
      <div class="modal-dialog modal-lg" role="document">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">DVID record</h5>
            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
          <div class="modal-body"><pre>%s</pre></div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>
    '''
    return html % (content)


def neuprint_link(ktype, value):
    ''' Generate a link to NeuPrint
        Keyword arguments:
          ktype: key type
          value: key value
        Returns:
          link
    '''
    url = assignment_utilities.CONFIG['neuprint']['url']
    url = url.replace('api/', 'workstation')
    return '<a href="%s?%s=%s" target="_blank">%s</a>' \
           % (url, ktype, value, value)


def get_user_id(user):
    ''' Get a user's ID from the "user" table
        Keyword arguments:
          user: user
    '''
    try:
        g.c.execute("SELECT id FROM user WHERE name='%s'" % user)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if not row or 'id' not in row:
        raise InvalidUsage("User %s was not found" % user, 404)
    return row['id']


def add_user_permissions(result, user, permissions):
    ''' Add permissions for an existing user
        Keyword arguments:
          result: result dictionary
          user: user
          permissions: list of permissions
    '''
    user_id = get_user_id(user)
    for permission in permissions:
        sql = "INSERT INTO user_permission (user_id,permission) VALUES " \
              + "(%s,'%s') ON DUPLICATE KEY UPDATE permission=permission"
        try:
            bind = (user_id, permission,)
            g.c.execute(sql % bind)
            result['rest']['row_count'] += g.c.rowcount
            publish_cdc(result, {"table": "user_permission", "operation": "insert"})
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)


def generate_user_pulldown(org, category):
    ''' Generate pulldown menu of all users and organizations
        Keyword arguments:
          org: allowable organizations (None=all)
          category: menu category
        Returns:
          HTML menu
    '''
    controls = ''
    try:
        g.c.execute('SELECT DISTINCT u.* FROM user_vw u JOIN task t ON (u.name=t.user) ' \
                    + 'ORDER BY last,first')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    controls = 'Show ' + category
    controls += ' for <select id="proofreader" onchange="select_proofreader(this);">' \
               + '<option value="">Select a proofreader...</option>'
    for row in rows:
        if org:
            rec = get_user_by_name(row['name'])
            if rec['organization'] not in org:
                continue
        controls += '<option value="%s">%s</option>' \
                    % (row['name'], ', '.join([row['last'], row['first']]))
    controls += '</select><br><br>'
    return controls, rows


def generate_user_org_pulldowns():
    ''' Generate pulldown menu of all users and organizations
        Keyword arguments:
          None
        Returns:
          HTML menus
    '''
    controls, rows = generate_user_pulldown(None, 'metrics')
    controls += 'Show metrics for <select id="organization" ' \
                + 'onchange="select_organization(this);">' \
                + '<option value="">Select an organization...</option>' \
                + '<option value="All organizations">All organizations</option>'
    org = dict()
    for row in rows:
        org[row['organization']] = 1
    for row in sorted(org):
        controls += '<option value="%s">%s</option>' % (row, row)
    controls += '</select>'
    return controls


def generate_user_task_pulldown(org):
    ''' Generate pulldown menu of task dispositions
        Keyword arguments:
          org: allowable organizations (None=all)
        Returns:
          HTML menu
    '''
  #SELECT DISTINCT user,disposition FROM task WHERE disposition IS NOT NULL;
    controls = ''
    try:
        g.c.execute('SELECT DISTINCT user,disposition FROM task WHERE disposition IS NOT NULL ' \
                    + 'ORDER BY disposition')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    controls = 'Show tasks with status <select id="proofreader" ' \
               + 'onchange="select_disposition(this);">' \
               + '<option value="">Select a status...</option>'
    added = dict()
    for row in rows:
        if row['disposition'] in added:
            continue
        if org:
            rec = get_user_by_name(row['user'])
            if rec['organization'] not in org:
                continue
        controls += '<option value="%s">%s</option>' \
                    % (row['disposition'], row['disposition'])
        added[row['disposition']] = 1
    controls += '</select><br><br>'
    return controls


def show_user_list(user):
    ''' Generate a list of users that an admin may operate on
        Keyword arguments:
          user: calling user
        Returns:
          HTML menu
    '''
    if not check_permission(user, ['admin', 'view']):
        return ''
    perm = check_permission(user)
    controls, _ = generate_user_pulldown(perm, 'tasks')
    controls += generate_user_task_pulldown(perm)
    return controls


def get_token():
    ''' Get the assignment manager token
    '''
    url = assignment_utilities.CONFIG['neuprint-auth']['url'] + 'api/token/assignment-manager'
    # url = url.replace('api/', '')
    cookies = {'flyem-services': request.cookies.get('flyem-services')}
    headers = {"Content-Type": "application/json"}
    try:
        req = requests.get(url, headers=headers, cookies=cookies)
    except requests.exceptions.RequestException as err: # pragma no cover
        raise InvalidUsage(err, 500)
    if req.status_code == 200:
        resp = req.json()
        return resp['token']
    raise InvalidUsage("No response from %s" % (url))


def get_web_profile(token=None):
    ''' Get the username and picture
        Keyword arguments:
          token: auth token
    '''
    if not token:
        token = request.cookies.get(app.config['TOKEN'])
    resp = decode_token(token)
    user = resp['email']
    face = '<img class="user_image" src="%s" alt="%s">' % (resp['image-url'], user)
    return user, face


def check_token():
    ''' Check to see if the user has a valid token
        Returns:
          user: user name
          face: Workday image HTML
    '''
    if not request.cookies.get(app.config['TOKEN']) or not request.cookies.get('flyem-services'):
        return False, False
    user, face = get_web_profile()
    return user, face


def generate_navbar(active):
    ''' Generate the web navigation bar
        Keyword arguments:
          active: name of active nav
        Returns:
          Navigation bar
    '''
    nav = '''
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
      <div class="collapse navbar-collapse" id="navbarSupportedContent">
        <ul class="navbar-nav mr-auto">
    '''
    for heading in ['Projects', 'Assignments', 'Tasks', 'Protocols', 'Users']:
        if heading == 'Assignments':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Assignments</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/assignmentlist">Show</a>' \
                   + '<a class="dropdown-item" href="/assigntasks">Generate</a>'
            nav += '</div></li>'
        elif heading == 'Tasks':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Tasks</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/tasklist">Show</a>' \
                   + '<a class="dropdown-item" href="/search">Search</a>'
            nav += '</div></li>'
        elif heading == 'Protocols':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Protocols</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            for subhead in app.config['PROTOCOLS']:
                if subhead in sys.modules:
                    nav += '<a class="dropdown-item" href="/userlist/%s">%s</a>' \
                           % (subhead, app.config['PROTOCOLS'][subhead])
            nav += '</div></li>'
        elif heading == 'Users':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Users</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/userlist">Show</a>' \
                   + '<a class="dropdown-item" href="/usermetrics">Metrics</a>'
            nav += '</div></li>'
        else:
            nav += '<li class="nav-item active">' if heading == active else '<li class="nav-item">'
            link = ('/' + heading[:-1] + 'list').lower()
            nav += '<a class="nav-link" href="%s">%s</a>' % (link, heading)
            nav += '</li>'
    nav += '</ul></div></nav>'
    return nav


def create_downloadable(name, header, template, content):
    ''' Generate a dowenloadabe content file
        Keyword arguments:
          name: base file name
          header: table header
          template: header row template
          content: table content
        Returns:
          File name
    '''
    fname = '%s_%s_%s.tsv' % (name, random_string(), datetime.today().strftime('%Y%m%d%H%M%S'))
    text_file = open("/tmp/%s" % (fname), "w")
    text_file.write(template % tuple(header))
    text_file.write(content)
    text_file.close()
    return fname


def generate_disposition_tasklist(rows, user):
    ''' Generate a dowenloadabe content file
        Keyword arguments:
          rows: task rows
          user: user
        Returns:
          Task table HTML
    '''
    tasks = '''
    <table id="tasks" class="tablesorter standard">
    <thead>
    <tr><th>Task</th><th>Project</th><th>Assignment</th><th>User</th><th>Priority</th><th>Started</th><th>Completed</th><th>Disposition</th><th>Duration</th></tr>
    </thead>
    <tbody>
    '''
    template = '<tr class="%s">' + ''.join("<td>%s</td>")*3 \
               + ''.join('<td style="text-align: center">%s</td>')*6 + "</tr>"
    perm = check_permission(user)
    userrec = dict()
    protocols = dict()
    for row in rows:
        if row['user'] in userrec:
            rec = userrec[row['user']]
        else:
            rec = get_user_by_name(row['user'])
            userrec[row['user']] = rec
        if rec['organization'] not in perm:
            continue
        rclass = 'complete' if row['disposition'] == 'Complete' else 'open'
        if not row['start_date']:
            rclass = 'notstarted'
        name = re.sub('[^0-9a-zA-Z]+', '_', row['protocol'])
        rclass += ' ' + name
        protocols[name] = row['protocol']
        idlink = '<a href="/task/%s">%s</a>' % (row['id'], row['id'])
        proj = '<a href="/project/%s">%s</a>' % (row['project'], row['project'])
        assign = '<a href="/assignment/%s">%s</a>' % (row['assignment'], row['assignment'])
        tasks += template % (rclass, idlink, proj, assign, row['user'], row['priority'],
                             row['start_date'], row['completion_date'], row['disposition'],
                             row['duration'])
    tasks += "</tbody></table>"
    return tasks, protocols


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


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    ''' Error handler
        Keyword arguments:
          error: error object
    '''
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


# *****************************************************************************
# * Web content                                                               *
# *****************************************************************************


@app.route('/profile')
def profile():
    ''' Show user profile
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    try:
        rec = get_user_by_name(user)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    uprops = []
    uprops.append(['Name:', ' '.join([rec['first'], rec['last']])])
    uprops.append(['Janelia ID:', rec['janelia_id']])
    uprops.append(['Organization:', rec['organization']])
    uprops.append(['Permissions:', '<br>'.join(rec['permissions'].split(','))])
    token = request.cookies.get(app.config['TOKEN'])
    return render_template('profile.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Users'), uprops=uprops, token=token)


@app.route('/userlist')
def user_list():
    ''' Show list of users
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not check_permission(user, ['super', 'admin', 'view']):
        return redirect("/profile")
    try:
        g.c.execute('SELECT * FROM user_vw ORDER BY janelia_id')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    urows = ''
    template = '<tr class="%s">' + ''.join("<td>%s</td>")*6 + "</tr>"
    organizations = dict()
    for row in rows:
        rclass = re.sub('[^0-9a-zA-Z]+', '_', row['organization'])
        organizations[rclass] = row['organization']
        link = '<a href="/user/%s">%s</a>' % (row['name'], row['name'])
        if not row['permissions']:
            row['permissions'] = '-'
        else:
            showarr = []
            for perm in row['permissions'].split(','):
                if perm in app.config['PROTOCOLS']:
                    this_perm = '<span style="color:cyan">%s</span>' % app.config['PROTOCOLS'][perm]
                elif perm in app.config['GROUPS']:
                    this_perm = '<span style="color:gold">%s</span>' % perm
                else:
                    this_perm = '<span style="color:orange">%s</span>' % perm
                showarr.append(this_perm)
            row['permissions'] = ', '.join(showarr)
        urows += template % (rclass, ', '.join([row['last'], row['first']]), link,
                             row['janelia_id'], row['email'], row['organization'],
                             row['permissions'])
    adduser = ''
    if check_permission(user, 'admin'):
        adduser = '''
        <br>
        <h3>Add a user</h3>
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input1">User name</label>
            <input type="text" class="form-control" id="user_name" aria-describedby="usernameHelp" placeholder="Enter user name">
            <small id="usernameHelp" class="form-text text-muted">This is the NeuPrint user name (Google email address).</small>
          </div>
        </div>
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input2">Janelia ID</label>
            <input type="text" class="form-control" id="janelia_id" aria-describedby="jidHelp" placeholder="Enter Janelia ID">
            <small id="jidHelp" class="form-text text-muted">Enter the Janelia user ID.</small>
          </div>
        </div>
        <button type="submit" id="sb" class="btn btn-primary" onclick="add_user();" href="#">Add user</button>
        '''
    return render_template('userlist.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Users'), organizations=organizations,
                           userrows=urows, adduser=adduser)


@app.route('/userlist/<string:protocol>')
def user_protocol_list(protocol):
    ''' Allow users to be granted/denied a specific protocol
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not check_permission(user, ['admin', 'view']):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's protocols")
    try:
        g.c.execute("SELECT display_name FROM cv_term_vw WHERE cv='protocol' "
                    + "AND cv_term=%s", (protocol,))
        rec = g.c.fetchone()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not rec:
        return render_template('error.html', urlroot=request.url_root,
                               title='Protocol error',
                               message="Protocol %s does not exist" % protocol)
    try:
        g.c.execute('SELECT * FROM user_vw ORDER BY janelia_id')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    urows = ''
    template = '<tr class="%s">' + ''.join("<td>%s</td>")*4 \
               + ''.join('<td style="text-align: center">%s</td>')*1 + "</tr>"
    organizations = dict()
    for row in rows:
        rclass = re.sub('[^0-9a-zA-Z]+', '_', row['organization'])
        link = '<a href="/user/%s">%s</a>' % (row['name'], row['name'])
        val = 'checked="checked"' if row['permissions'] and protocol in row['permissions'] else ''
        check = '<input type="checkbox" %s id="%s" onchange="changebox(this,%s);">' \
                 % (val, row['name'], "'" + protocol + "'")
        organizations[rclass] = row['organization']
        urows += template % (rclass, ', '.join([row['last'], row['first']]), link,
                             row['janelia_id'], row['organization'], check)
    return render_template('userplist.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Protocols'),
                           protocol=app.config['PROTOCOLS'][protocol],
                           organizations=organizations, userrows=urows)


@app.route('/user/<string:uname>')
def user_config(uname):
    ''' Show user profile
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not check_permission(user, ['super', 'admin', 'view']):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's profile")
    try:
        rec = get_user_by_name(uname)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not rec:
        return render_template('error.html', urlroot=request.url_root,
                               title='Not found',
                               message="User %s was not found" % uname)
    uprops = []
    uprops.append(['Name:', ' '.join([rec['first'], rec['last']])])
    uprops.append(['Janelia ID:', rec['janelia_id']])
    uprops.append(['Organization:', rec['organization']])
    ptable = build_protocols_table(user, rec)
    links = ''
    try:
        g.c.execute("SELECT COUNT(1) AS c FROM task WHERE user=%s", (uname, ))
        rec = g.c.fetchone()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if rec and rec['c']:
        links = '''
        <a href="/tasklist/%s">Tasks</a><br>
        <a href="/usermetrics/%s">Metrics</a><br>
        '''
        links = links % tuple([uname] * 2)
    return render_template('user.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=uname,
                           navbar=generate_navbar('Users'), links=links,
                           uprops=uprops, ptable=ptable)


@app.route('/usermetrics')
@app.route('/usermetrics/<string:uname>')
def usermetrics(uname=None):
    ''' Show user metrics
    '''
    # pylint: disable=R0911
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not uname:
        uname = user
    permission = check_permission(user, ['admin', 'view'])
    if user != uname and not permission:
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's metrics")
    # Controls
    controls = '' if not permission else generate_user_org_pulldowns()
    # User name
    try:
        rec = get_user_by_name(uname)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    username = ' '.join([rec['first'], rec['last']])
    try:
        assignments = get_user_metrics('assignment', uname)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    try:
        tasks = get_user_metrics('task', uname)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    return render_template('usermetrics.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=uname,
                           navbar=generate_navbar('Users'), controls=controls,
                           username=username, assignments=assignments, tasks=tasks)


@app.route('/orgmetrics/<string:oname>')
def orgmetrics(oname='All organizations'):
    ''' Show user metrics
    '''
    # pylint: disable=R0911
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    permission = check_permission(user, ['admin', 'view'])
    if not permission:
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's metrics")
    # Controls
    controls = '' if not permission else generate_user_org_pulldowns()
    try:
        assignments = get_user_metrics('assignment', oname, 'org')
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    try:
        tasks = get_user_metrics('task', oname, 'org')
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    return render_template('usermetrics.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Users'), controls=controls,
                           username=oname, assignments=assignments, tasks=tasks)


@app.route('/logout')
def logout():
    ''' Log out
    '''
    if not request.cookies.get(app.config['TOKEN']) or not request.cookies.get('flyem-services'):
        return render_template('error.html', urlroot=request.url_root,
                               title='You are not logged in',
                               message="You can't log out unless you're logged in")
    url = assignment_utilities.CONFIG['neuprint-auth']['url'] + 'logout'
    headers = {"Content-Type": "application/json"}
    cookies = {'flyem-services': request.cookies.get('flyem-services')}
    try:
        requests.post(url, headers=headers, cookies=cookies)
    except requests.exceptions.RequestException as err:
        print(err)
    response = make_response(render_template('logout.html', urlroot=request.url_root))
    response.set_cookie('flyem-services', '', domain='.janelia.org', expires=0)
    response.set_cookie(app.config['TOKEN'], '', domain='.janelia.org', expires=0)
    return response


@app.route('/download/<string:fname>')
def download(fname):
    ''' Downloadable content
    '''
    try:
        return send_file('/tmp/' + fname, attachment_filename=fname)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='Download error', message=err)


@app.route('/')
@app.route('/projectlist', methods=['GET', 'POST'])
def show_projects(): # pylint: disable=R0914,R0912,R0915
    ''' Projects
    '''
    if not request.cookies.get(app.config['TOKEN']):
        if request.cookies.get('flyem-services'):
            token = get_token()
            user, face = get_web_profile(token)
        else:
            return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    else:
        token = request.cookies.get(app.config['TOKEN'])
    if request.cookies.get(app.config['TOKEN']):
        user, face = get_web_profile()
    permissions = check_permission(user)
    result = initialize_result()
    try:
        g.c.execute('SELECT protocol,COUNT(1) AS c FROM project_vw GROUP BY 1')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    projectsummary = ''
    if rows:
        projectsummary = '''
        <h2>Project summary</h2>
        <table id="psumm" class="tablesorter standard">
        <thead><tr><th>Protocol</th><th>Count</th></tr></thead><tbody>
        '''
        template = '<tr><td>%s</td><td style="text-align: center">%s</td></tr>'
        for row in rows:
            row['protocol'] = app.config['PROTOCOLS'][row['protocol']]
            projectsummary += template \
                                 % tuple([row[x] for x in ['protocol', 'c']])
        projectsummary += '</tbody></table>'
    ipd = receive_payload(result)
    try:
        g.c.execute(project_summary_query(ipd))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if rows:
        header = ['Protocol', 'Group', 'Project', 'Tasks', 'Disposition', 'Priority',
                  'Created', 'Active']
        projects = '''
        <table id="projects" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        projects += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*3 \
                   + ''.join('<td style="text-align: center">%s</td>')*5 + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*8) + "\n"
        for row in rows:
            if 'admin' not in permissions and 'view' not in permissions \
               and row['protocol'] not in permissions:
                continue
            rclass = 'complete' if row['disposition'] == 'Complete' else 'open'
            if not row['disposition']:
                rclass = 'open'
            proj = '<a href="/project/%s">%s</a>' % (row['project'], row['project'])
            active = "<span style='color:%s'>%s</span>" \
                     % (('lime', 'YES') if row['active'] else ('red', 'NO'))
            this_protocol = app.config['PROTOCOLS'][row['protocol']]
            projects += template % (rclass, this_protocol, row['project_group'], proj,
                                    row['num'], row['disposition'], row['priority'],
                                    row['create_date'], active)
            fileoutput += ftemplate % (this_protocol, row['project_group'], row['project'],
                                       row['num'], row['disposition'], row['priority'],
                                       row['create_date'], row['active'])
        projects += "</tbody></table>"
        downloadable = create_downloadable('projects', header, ftemplate, fileoutput)
        projects = '<a class="btn btn-outline-info btn-sm" href="/download/%s" ' \
                   % (downloadable) + 'role="button">Download table</a>' + projects
    else:
        projects = "There are no projects"
    if request.method == 'POST':
        return {"projects": projects}
    protocols = protocol_select_list(result)
    newproject = ''
    if check_permission(user, 'admin'):
        newproject = '''
        <span style="font-size: 14pt;font-weight: 500;">Create a new project</span>:
        <select id="pprotocol" onchange='new_project(this);'>
        <option value="all" SELECTED>Select a protocol for a new project...</a>
        '''
        for row in result['temp']:
            if bool(row['cv_term'] in sys.modules):
                newproject += '<option value="%s">%s</option>' % (row['cv_term'], \
                               app.config['PROTOCOLS'][row['cv_term']])
        newproject += '</select><hr style="border: 1px solid gray">'
    if not token:
        token = ''
    response = make_response(render_template('projectlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Projects'),
                                             projectsummary=projectsummary, newproject=newproject,
                                             protocols=protocols, projects=projects))
    response.set_cookie(app.config['TOKEN'], token, domain='.janelia.org')
    return response


@app.route('/assignmentlist', methods=['GET', 'POST'])
@app.route('/assignmentlist/interactive', methods=['GET', 'POST'])
def show_assignments(): # pylint: disable=R0914
    ''' Show assignments
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    result = initialize_result()
    ipd = receive_payload(result)
    initial_start = ''
    if 'interactive' not in request.url:
        initial_start = (datetime.now() - timedelta(days=7)).date()
        ipd['start_date'] = initial_start
    try:
        g.c.execute('SELECT protocol,disposition,COUNT(1) AS c FROM assignment_vw GROUP BY 1,2')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    assignmentsummary = ''
    if rows:
        assignmentsummary = '''
        <h2>Assignment summary</h2>
        <table id="asumm" class="tablesorter standard">
        <thead><tr><th>Protocol</th><th>Disposition</th><th>Count</th></tr></thead><tbody>
        '''
        template = '<tr><td>%s</td><td>%s</td><td style="text-align: center">%s</td></tr>'
        for row in rows:
            row['protocol'] = app.config['PROTOCOLS'][row['protocol']]
            assignmentsummary += template \
                                 % tuple([row[x] for x in ['protocol', 'disposition', 'c']])
        assignmentsummary += '</tbody></table><br>'
    proofreaders, assignments = build_assignment_table(user, ipd)
    if request.method == 'POST':
        return {"assignments": assignments}
    protocols = protocol_select_list(result)
    response = make_response(render_template('assignmentlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Assignments'),
                                             assignmentsummary=assignmentsummary,
                                             start=initial_start, assignments=assignments,
                                             protocols=protocols, proofreaders=proofreaders,))
    return response


@app.route('/assigntasks')
def assign_tasks(): # pylint: disable=R0914
    ''' Assign tasks
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not check_permission(user, 'admin'):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to assign tasks")
    try:
        g.c.execute(READ['UPSUMMARY'])
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if rows:
        header = ['Protocol', 'Group', 'Project', 'Tasks', 'Priority', 'Active', 'Assignment']
        unassigned = '''
        <table id="unassigned" class="tablesorter standard">
        <tr><th>
        '''
        unassigned += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = "<tr>" + ''.join("<td>%s</td>")*3 \
                   + ''.join('<td style="text-align: center">%s</td>')*4 + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*7) + "\n"
        for row in rows:
            active = "<span style='color:%s'>%s</span>" \
                     % (('lime', 'YES') if row['active'] else ('red', 'NO'))
            button = '' if not row['active'] else \
                        '<a class="btn btn-success btn-tiny" style="color:#fff" href="' \
                        + '/assignto/' + row['project'] + '" role="button">Create</a>'
            this_protocol = app.config['PROTOCOLS'][row['protocol']]
            unassigned += template % (this_protocol, row['project_group'],
                                      ('<a href="/project/%s">%s</a>' % (row['project'], \
                                       row['project'])),
                                      row['num'], row['priority'], active, button)
            fileoutput += ftemplate % (this_protocol, row['project_group'], row['project'],
                                       row['num'], row['priority'], row['active'], '-')
        unassigned += "</tbody></table>"
        downloadable = create_downloadable('unassigned', header, ftemplate, fileoutput)
        unassigned = '<br><h2>Projects with unassigned tasks</h2>' \
                     + '<a class="btn btn-outline-info btn-sm" href="/download/%s" ' \
                     % (downloadable) + 'role="button">Download table</a>' + unassigned
    else:
        unassigned = "There are no projects with unassigned tasks"
    response = make_response(render_template('assigntasks.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Assignments'),
                                             unassigned=unassigned))
    return response


@app.route('/tasklist')
@app.route('/tasklist/<string:taskuser>')
def show_tasks(taskuser=None):
    ''' Projects
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if taskuser and not check_permission(user, ['admin', 'view']):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's tasks")
    # Summary table
    try:
        g.c.execute('SELECT cvt.display_name,t.disposition,COUNT(1) AS c FROM task t ' \
                    + 'JOIN project p ON (t.project_id=p.id) JOIN cv_term cvt ON ' \
                    + '(cvt.id=protocol_id) GROUP BY 1,2')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    tasksumm = '''
        <table id="tasksumm" class="tablesorter standard"><thead>
        <tr><th>Protocol</th><th>Disposition</th><th>Count</th></tr>
        </thead>
        <tbody>
    '''
    if not rows:
        tasksumm = 'No tasks were found'
    else:
        for row in rows:
            tasksumm += '<tr><td>%s</td><td>%s</td><td>%s</td></tr>' \
                        % (row['display_name'], row['disposition'], row['c'])
        tasksumm += '</tbody></table>'
        tasksumm += show_user_list(user)
    # Main table
    if not taskuser:
        taskuser = user
    try:
        g.c.execute(READ['TASKS'], taskuser)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    protocols = dict()
    if rows:
        tasks = '''
        <table id="tasks" class="tablesorter standard">
        <thead>
        <tr><th>Task</th><th>Project</th><th>Assignment</th><th>Priority</th><th>Started</th><th>Completed</th><th>Disposition</th><th>Duration</th></tr>
        </thead>
        <tbody>
        '''
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*3 \
                   + ''.join('<td style="text-align: center">%s</td>')*5 + "</tr>"
        for row in rows:
            rclass = 'complete' if row['disposition'] == 'Complete' else 'open'
            if not row['start_date']:
                rclass = 'notstarted'
            name = re.sub('[^0-9a-zA-Z]+', '_', row['protocol'])
            rclass += ' ' + name
            protocols[name] = row['protocol']
            idlink = '<a href="/task/%s">%s</a>' % (row['id'], row['id'])
            proj = '<a href="/project/%s">%s</a>' % (row['project'], row['project'])
            assign = '<a href="/assignment/%s">%s</a>' % (row['assignment'], row['assignment'])
            tasks += template % (rclass, idlink, proj, assign, row['priority'],
                                 row['start_date'], row['completion_date'], row['disposition'],
                                 row['duration'])
        tasks += "</tbody></table>"

    else:
        tasks = "%s has no assigned tasks" % (taskuser)
    return render_template('tasklist.html', urlroot=request.url_root, face=face,
                           user=taskuser, dataset=app.config['DATASET'],
                           navbar=generate_navbar('Tasks'), tasksumm=tasksumm,
                           protocols=protocols, tasks=tasks)


@app.route('/taskstatuslist/<string:disposition>')
def show_tasks_by_disposition(disposition=None):
    ''' Projects
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not check_permission(user, ['admin', 'view']):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's tasks")
    # Main table
    try:
        g.c.execute(READ['TASKSDISP'], disposition)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if rows:
        tasks, protocols = generate_disposition_tasklist(rows, user)
    else:
        tasks = "No tasks found"
    return render_template('taskstatuslist.html', urlroot=request.url_root, face=face,
                           user=user, dataset=app.config['DATASET'],
                           navbar=generate_navbar('Tasks'), tasksumm=show_user_list(user),
                           protocols=protocols, tasks=tasks, disposition=disposition)


@app.route('/project/<string:pname>')
def show_project(pname):
    ''' Show information for a project
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    try:
        g.c.execute("SELECT * FROM project_vw WHERE name=%s", (pname,))
        project = g.c.fetchone()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not project:
        return render_template('error.html', urlroot=request.url_root,
                               title='Not found', message="Project %s was not found" % pname)
    controls = ''
    if check_permission(user, 'admin'):
        if project['active']:
            controls = '''
            <button type="button" class="btn btn-danger btn-sm" onclick='modify_project(%s,"suspended");'>Suspend project</button>
            '''
        else:
            controls = '''
            <button type="button" class="btn btn-success btn-sm" onclick='modify_project(%s,"activated");'>Activate project</button>
            '''
        controls = controls % (project['id'])
        controls += '''
        <div class="rounded" style='width: 320px;border: 1px solid #c3c;'>Set new priority: 
        <input id="slider" width="300" value="%s"  onchange="reprioritize_project('%s');"/><span style="font-size:14pt; color:#fff;" id="priority"></span> (1-50; 1=highest)
        </div>
        <script>
          $('#slider').slider({
            uiLibrary: 'bootstrap4',
            min: 1, max: 50, value: %s,
            slide: function (e, value) {
              document.getElementById('priority').innerText = value;
            }
          });
        </script>
        '''
        controls = controls % (project['priority'], project['name'], project['priority'])
    # Unassigned tasks
    try:
        g.c.execute(READ['PROJECTUA'] % (pname,))
        tasks = g.c.fetchone()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    num_unassigned = tasks['num'] if tasks else 0
    # Assigned tasks
    try:
        g.c.execute(READ['PROJECTA'] % (pname,))
        tasks = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    assigned, num_assigned, disposition_block = get_assigned_tasks(tasks, project['id'],
                                                                   num_unassigned, user)
    num_tasks = num_assigned + num_unassigned
    if not num_tasks:
        num_tasks = -1
    assignedt, unassignedt = colorize_tasks(num_assigned, num_unassigned, num_tasks)
    if num_unassigned and project['active'] and check_permission(user, 'admin'):
        button = '<a class="btn btn-success btn-sm" style="color:#fff" href="' \
                 + '/assignto/' + pname + '" role="button">Create assignment</a>'
        unassignedt += ' ' + button
    if project['protocol'] in app.config['DVID_REPORTS']:
        disposition_block += '<br><a class="btn btn-outline-success btn-sm" style="color:#fff" ' \
                             + 'href="/project/report/task_results/' + pname + '.tsv' \
                             + '" role="button">DVID task result report</a><br><br>'
    if num_tasks == -1:
        num_tasks = '<span style="color:red">(tasks are still being generated)</span>'
    return render_template('project.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], navbar=generate_navbar('Projects'),
                           project=pname, pprops=get_project_properties(project), controls=controls,
                           total=num_tasks, num_unassigned=unassignedt,
                           num_assigned=assignedt, disposition_block=disposition_block,
                           assigned=assigned)


@app.route('/project/report/task_results/<string:name>.tsv', methods=['GET'])
def project_report_task_results(name):
    '''
    Generate a DVID task result report
    Given a project name, generate a DVID task result report.
    ---
    tags:
      - Project
    parameters:
      - in: path
        name: name
        schema:
          type: string
        required: true
        description: project name
    '''
    try:
        g.c.execute(READ['DVID_PROJECT_TASKS'], (name, ))
        tasks = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not tasks:
        return render_template('error.html', urlroot=request.url_root,
                               title='Not found', message="Project %s was not found" % name)
    template = "%s\t%s\t%s\n"
    output = template % ('Task ID', 'Result', 'User')
    for task in tasks:
        output += template % (task['id'], task['result'], task['user'])
    response = Response(output, mimetype='text/tab-separated-values')
    return response


@app.route('/assignment/<string:aname>')
def show_assignment(aname):
    ''' Show information for an assignment
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    try:
        g.c.execute(READ['ASSIGNMENTN'], (aname,))
        assignment = g.c.fetchone()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not check_permission(user, ['admin', 'view']) and assignment['user'] != user:
        return render_template('error.html', urlroot=request.url_root,
                               title='No permission',
                               message="You don't have permission to view " \
                                       + "other proofreader's assignments")
    if not assignment:
        return render_template('error.html', urlroot=request.url_root,
                               message='Assignment %s was not found' % aname)
    aprops = []
    for prop in ['project', 'protocol', 'user2', 'disposition', 'create_date', 'start_date',
                 'completion_date', 'duration', 'working_duration', 'note']:
        if assignment[prop]:
            show = prop.replace('_', ' ')
            show = 'User:' if prop == 'user2' else show.capitalize() + ':'
            if prop == 'project':
                assignment[prop] = '<a href="/project/%s">%s</a>' \
                                   % (assignment[prop], assignment[prop])
            elif prop == 'protocol':
                assignment['protocol'] = app.config['PROTOCOLS'][assignment['protocol']]
            aprops.append([show, assignment[prop]])
    tasks, num_tasks, tasks_started = build_task_table(aname)
    try:
        g.c.execute("SELECT uv.name,CONCAT(last,', ',first)AS proofreader FROM user_vw uv "
                    + "JOIN user_permission_vw upv ON (uv.name=upv.name) "
                    + "WHERE permission=%s ORDER BY janelia_id", assignment['protocol'])
        user_rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    controls = get_assignment_controls(assignment, num_tasks, tasks_started, user, user_rows)
    if assignment['protocol'] in app.config['DVID_REPORTS']:
        controls += '<br><br><a class="btn btn-outline-success btn-sm" style="color:#fff" href="' \
                    + '/assignment/report/task_results/' + aname + '.tsv' \
                    + '" role="button">DVID task result report</a>'
    return render_template('assignment.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], navbar=generate_navbar('Assignments'),
                           assignment=aname, aprops=aprops, controls=controls, tasks=tasks)


@app.route('/assignment/report/task_results/<string:name>.tsv', methods=['GET'])
def assignment_report_task_results(name):
    '''
    Generate a DVID task result report
    Given an assignment name, generate a DVID task result report.
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: name
        schema:
          type: string
        required: true
        description: assignment name
    '''
    stmt = READ['DVID_PROJECT_TASKS'].replace('project', 'assignment')
    try:
        g.c.execute(stmt, (name, ))
        tasks = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not tasks:
        return render_template('error.html', urlroot=request.url_root,
                               title='Not found', message="Assignment %s was not found" % name)
    template = "%s\t%s\t%s\n"
    output = template % ('Task ID', 'Result', 'User')
    for task in tasks:
        output += template % (task['id'], task['result'], task['user'])
    response = Response(output, mimetype='text/tab-separated-values')
    return response


@app.route('/task/<string:task_id>')
def show_task(task_id):
    ''' Show information for a task
    '''
    # pylint: disable=R0911
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    try:
        sql = "SELECT * FROM task_vw WHERE id=%s"
        if not task_id.isdigit():
            sql = sql.replace("id", "name")
        g.c.execute(sql, (task_id,))
        task = g.c.fetchone()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    if not task:
        return render_template('error.html', urlroot=request.url_root,
                               title='Task not found', message="task %s was not found" % task_id)
    if not check_permission(user, ['admin', 'view']) and task['user'] != user:
        return render_template('error.html', urlroot=request.url_root,
                               title='No permission',
                               message="You don't have permission to view " \
                                       + "other proofreader's assignments")
    task_id = task['id']
    tprops = []
    tprops.append(['Project:', '<a href="/project/%s">%s</a>' % (task['project'], task['project'])])
    tprops.append(['Protocol:', app.config['PROTOCOLS'][task['protocol']]])
    tprops.append(['Assignment:', '<a href="/assignment/%s">%s</a>' % (task['assignment'],
                                                                       task['assignment'])])
    val = neuprint_link('bodyid', task['key_text']) \
          if task['key_type_display'] == 'Body ID' else task['key_text']
    tprops.append([task['key_type_display'] + ':', val])
    tprops.append(['Create date:', task['create_date']])
    tprops.append(['Start date:', task['start_date']])
    tprops.append(['Completion date:', task['completion_date']])
    tprops.append(['Duration:', task['duration']])
    tprops.append(['Working duration:', task['working_duration']])
    try:
        g.c.execute("SELECT type_display,value FROM task_property_vw WHERE task_id=%s ORDER BY 1"
                    % (task_id,))
        props = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    for prop in props:
        if not prop['value']:
            continue
        val = neuprint_link('bodyid', prop['value']) \
              if 'Body ID' in prop['type_display'] else prop['value']
        tprops.append([prop['type_display'], val])
        if prop['type_display'] == 'DVID user':
            tprops.append(['DVID record', dvid_result_button(task['protocol'], task['key_text'])])
    # Controls
    try:
        controls = get_task_controls(user, task_id, task)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    # Audit table
    try:
        audit = generate_task_audit_list(task_id)
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    return render_template('task.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], navbar=generate_navbar('Tasks'),
                           task=task_id, tprops=tprops, controls=controls, audit=audit)


@app.route('/newproject/<string:protocol>')
def project_create(protocol):
    ''' Create a new project
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not check_permission(user, 'admin'):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to create projects")
    constructor = globals()[protocol.capitalize()]
    projectins = constructor()
    required, optional, optionaljs, filt, filtjs = process_projectparms(projectins, protocol)
    return render_template('newproject.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], navbar=generate_navbar('Projects'),
                           protocol=protocol, display_protocol=app.config['PROTOCOLS'][protocol],
                           required=required, optionaljs=optionaljs, optional=optional, filt=filt,
                           filtjs=filtjs)


@app.route('/assignto/<string:pname>')
def assign_to(pname):
    ''' Make an assignment for a project
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    project = ''
    if not check_permission(user, 'admin'):
        return render_template('error.html', urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to make assignments")
    project = get_project_by_name_or_id(pname)
    if not project:
        return render_template('error.html', urlroot=request.url_root,
                               title='Project not found',
                               message="Project %s was not found" % pname)
    try:
        g.c.execute('SELECT * FROM user_vw uv JOIN user_permission_vw upv ON (uv.name=upv.name) '
                    + 'WHERE permission=%s ORDER BY janelia_id', project['protocol'])
        rows = g.c.fetchall()
    except Exception as err:
        return render_template('error.html', urlroot=request.url_root,
                               title='SQL error', message=sql_error(err))
    proofreaders = dict()
    for row in rows:
        uname = ' '.join([row['first'], row['last']])
        proofreaders[row['name']] = uname
    constructor = globals()[project['protocol'].capitalize()]
    projectins = constructor()
    return render_template('assignto.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], navbar=generate_navbar('Projects'),
                           project=project['name'], proofreaders=proofreaders,
                           num_tasks=projectins.num_tasks)


@app.route('/search')
def show_search_form():
    ''' Make an assignment for a project
    '''
    user, face = check_token()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    return render_template('search.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], navbar=generate_navbar('Tasks'))


# *****************************************************************************
# * Endpoints                                                                 *
# *****************************************************************************

@app.route('/help')
def show_swagger():
    ''' Show Swagger docs
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


@app.route("/dbstats")
def dbstats():
    '''
    Show database stats
    Show database statistics
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Database tats
      400:
          description: Database stats could not be calculated
    '''
    result = initialize_result()
    sql = "SELECT TABLE_NAME,TABLE_ROWS FROM INFORMATION_SCHEMA.TABLES WHERE " \
          + "TABLE_SCHEMA='assignment' AND TABLE_NAME NOT LIKE '%vw'"
    g.c.execute(sql)
    rows = g.c.fetchall()
    result['rest']['row_count'] = len(rows)
    result['rest']['sql_statement'] = g.c.mogrify(sql)
    result['data'] = dict()
    for r in rows:
        result['data'][r['TABLE_NAME']] = r['TABLE_ROWS']
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
        row['HOST'] = 'None' if not row['HOST'] else row['HOST'] #.decode("utf-8")
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
        raise InvalidUsage(sql_error(err))
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
        raise InvalidUsage("Protocol %s is not loaded" % protocol)
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


@app.route('/neuron_count/<string:protocol>', methods=['OPTIONS', 'POST'])
def neuron_count(protocol):
    ''' Given an ROI and filters, return a neuron count
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if 'roi' not in ipd or (not ipd['roi']):
        result['count'] = 0
        return generate_response(result)
    constructor = globals()[protocol.capitalize()]
    projectins = constructor()
    try:
        response = projectins.cypher(result, ipd, app.config['NEUPRINT_SOURCE'], True)
    except AssertionError as err:
        raise InvalidUsage(err.args[0])
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500)
    if response['data']:
        result['count'] = response['data'][0][0]
    else:
        result['count'] = 0
    return generate_response(result)


@app.route('/project/activate/<string:name>', methods=['OPTIONS', 'POST'])
def activate_project(name):
    '''
    Activate a project
    Set a project's active flag to True.
    ---
    tags:
      - Project
    parameters:
      - in: path
        name: name
        schema:
          type: string
        required: true
        description: project name
    '''
    result = initialize_result()
    change_project_active(result, name, 1)
    return generate_response(result)


@app.route('/project/deactivate/<string:name>', methods=['OPTIONS', 'POST'])
def deactivate_project(name):
    '''
    Deactivate a project
    Set a project's active flag to False.
    ---
    tags:
      - Project
    parameters:
      - in: path
        name: name
        schema:
          type: string
        required: true
        description: project name
    '''
    result = initialize_result()
    change_project_active(result, name, 0)
    return generate_response(result)


@app.route('/project/reprioritize', methods=['OPTIONS', 'POST'])
def reprioritize_project():
    '''
    Reprioritize a project
    Set a project's active flag to False.
    ---
    tags:
      - Project
    parameters:
      - in: query
        name: project_name (or ID for an existing project)
        schema:
          type: string
        required: true
        description: project name
      - in: query
        name: priority
        schema:
          type: integer
        required: false
        description: project priority (defaults to 5)
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to reprioritize projects")
    project = get_project_by_name_or_id(ipd['project_name'])
    if not project:
        raise InvalidUsage("Project %s doesn't exist" % (ipd['project_name']))
    try:
        pnum = int(ipd['priority'])
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 400)
    change_project_priority(result, project['name'], pnum)
    return generate_response(result)


@app.route('/project/<string:protocol>', methods=['OPTIONS', 'POST'])
def process_project(protocol):
    '''
    Generate a new project
    Given a protocol and a JSON payload containing specifics, generate
     a new project and return its ID and a list of tasks. A "project_name"
     parameter is required. There are several optional parameters - check
     the "protocols" endpoint to see which protocols support which parameters.
     Parameters may be passed in as form data or JSON.
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
        name: priority
        schema:
          type: integer
        required: false
        description: project priority (defaults to 5)
      - in: query
        name: group
        schema:
          type: string
        required: false
        description: project group
      - in: query
        name: append
        schema:
          type: string
        required: false
        description: allow appending to existing project if included
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
        name: roi
        schema:
          type: string
        required: false
        description: neuron ROI filter
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
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to create projects")
    # Create the project
    if not generate_project(protocol, result):
        raise InvalidUsage("Project already exists")
    return generate_response(result)


@app.route('/projects/eligible', methods=['GET'])
def get_projects_eligible():
    '''
    Get eligible projects
    Return a list of projects from which the calling user can genearte assignments.
    The "calling user" is determined by the JWT.
    ---
    tags:
      - Project
    responses:
      200:
          description: dictionary of eligible projects (project/protocol)
      404:
          description: Projects not found
    '''
    result = initialize_result()
    if 'user' not in result['rest']:
        raise InvalidUsage('User was not specified')
    permissions = check_permission(result['rest']['user'])
    try:
        g.c.execute(READ['UPSUMMARY'])
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    result['projects'] = dict()
    for row in rows:
        if row['protocol'] in permissions and row['active']:
            result['projects'][row['project']] = row['protocol']
    if not result['projects']:
        raise InvalidUsage('No eligible projects', 404)
    result['rest']['row_count'] = len(result['projects'])
    return generate_response(result)


@app.route('/project/<string:project_name>', methods=['DELETE', 'OPTIONS'])
def delete_project(project_name):
    '''
    Delete a project
    '''
    result = initialize_result()
    if not check_permission(result['rest']['user'], 'super'):
        raise InvalidUsage("You don't have permission to delete projects")
    project = get_project_by_name_or_id(project_name)
    if not project:
        raise InvalidUsage("Project %s doesn't exist" % (project_name))
    bind = (project['id'])
    try:
        g.c.execute('DELETE FROM task_audit WHERE project_id=%s', bind)
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    try:
        g.c.execute('DELETE FROM task WHERE project_id=%s', bind)
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    try:
        g.c.execute('DELETE FROM assignment WHERE project_id=%s', bind)
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    try:
        g.c.execute('DELETE FROM project_property WHERE project_id=%s', bind)
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    try:
        g.c.execute('DELETE FROM project WHERE id=%s', bind)
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
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


@app.route('/assignmentstats/<string:assignment_id>', methods=['GET'])
def get_assignment_stats(assignment_id):
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
    tasks = get_tasks_by_assignment_id(assignment_id)
    result['data'] = dict()
    result['data']['total'] = len(tasks)
    complete = eligible = started = 0
    for task in tasks:
        if task['start_date'] is None:
            eligible += 1
        elif task['completion_date']:
            complete += 1
        else:
            started += 1
    result['data']['eligible'] = eligible
    result['data']['started'] = started
    result['data']['complete'] = complete
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
     haven't been started or completed yet. The caller can filter on any
     of the columns in the assignment_vw table. Inequalities (!=) and some
     relational operations (&lt;= and &gt;=) are supported. Wildcards are
     supported (use "*"). Specific columns from the assignment_vw table can
     be returned with the _columns key. The returned list may be ordered by
     specifying a column with the _sort key. In both cases, multiple columns
     would be separated by a comma.
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
     Parameters may be passed in as form data or JSON.
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
      - in: query
        name: name
        schema:
          type: string
        required: false
        description: assignment name
      - in: query
        name: user
        schema:
          type: string
        required: false
        description: user name (for "on behalf of" use case)
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
    responses:
      200:
          description: Assignment generated
      400:
          description: Assignment not generated (insufficient permission)
      404:
          description: Assignment not generated
    '''
    result = initialize_result()
    # Get payload
    ipd = receive_payload(result)
    ipd['project_name'] = project_name
    if not('name' in ipd and ipd['name'] != ''):
        ipd['name'] = ' '.join([project_name, random_string()])
    generate_assignment(ipd, result)
    return generate_response(result)


@app.route('/assignment/json/<string:aname>')
def return_assignment_json(aname):
    ''' Return JSON for an assignment
    ---
    tags:
      - Assignment
    parameters:
      - in: path
        name: assignment name
        schema:
          type: string
        required: true
        description: assignment name
    responses:
      200:
          description: Assignment JSON
      404:
          description: Assignment not found
    '''
    result = initialize_result()
    if aname.isdigit():
        assignment = get_assignment_by_name_or_id(aname)
        aname = assignment['name']
    try:
        g.c.execute('SELECT p.name FROM project_vw p JOIN assignment a ' \
                    + 'ON (a.project_id=p.id) WHERE a.name=%s', (aname,))
        pname = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if not pname:
        raise InvalidUsage("Assignment %s does not exist" % aname, 404)
    project = get_project_by_name_or_id(pname['name'])
    constructor = globals()[project['protocol'].capitalize()]
    projectins = constructor()
    if hasattr(projectins, 'return_json'):
        error = projectins.return_json(aname, g, result)
    else:
        error = return_tasks_json(aname, result)
    if error:
        raise InvalidUsage(error, 400)
    if project['protocol'] == 'cell_type_validation':
        result.update({"file type": "Neu3 task list",
                       "file version": "1",
                       "ID": "1"})
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
    ipd['id'] = str(assignment_id)
    start_assignment(ipd, result)
    g.db.commit()
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
    assignment = get_assignment_by_name_or_id(ipd['id'])
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % ipd['id'], 404)
    assignment_id = ipd['id'] = assignment['id']
    if not assignment['start_date']:
        raise InvalidUsage("Assignment %s was not started" % ipd['id'])
    if assignment['completion_date']:
        raise InvalidUsage("Assignment %s was already completed" % ipd['id'])
    complete_assignment(ipd, result, assignment)
    g.db.commit()
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>/reset', methods=['OPTIONS', 'POST'])
def reset_assignment_by_id(assignment_id): # pragma: no cover
    '''
    Reset an assignment (remove start time)
    An assignment can only be started if none of its tasks have been started.
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
    assignment = get_assignment_by_name_or_id(assignment_id)
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % assignment_id, 404)
    assignment_id = assignment['id']
    if not assignment['start_date']:
        raise InvalidUsage("Assignment %s was not started" % assignment_id)
    # Look for started tasks
    try:
        stmt = "SELECT id FROM task WHERE assignment_id=%s AND start_date IS NOT NULL"
        g.c.execute(stmt, (assignment_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if tasks:
        raise InvalidUsage("Found %s task(s) already started for assignment %s" \
                           % (len(tasks), assignment_id))
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


@app.route('/assignment/<string:assignment_id>/reassign', methods=['OPTIONS', 'POST'])
def reassign_assignment_by_id(assignment_id): # pragma: no cover
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
        name: user
        schema:
          type: string
        required: true
        description: user
    responses:
      200:
          description: Assignment reassigned
      400:
          description: Assignment not reassigned
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if 'user' not in ipd:
        raise InvalidUsage("You must specify a user to reassign to")
    try:
        g.c.execute("SELECT project_id FROM assignment WHERE id=%s", assignment_id)
        pid = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    project = get_project_by_name_or_id(pid['project_id'])
    try:
        ipd['assignto'] = select_user(project, ipd, result)
    except Exception as err:
        raise err
    try:
        stmt = "UPDATE assignment SET user=%s WHERE id=%s"
        bind = (ipd['user'], assignment_id)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] += g.c.rowcount
        result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    try:
        stmt = "UPDATE task SET user=%s WHERE assignment_id=%s"
        bind = (ipd['user'], assignment_id)
        g.c.execute(stmt, bind)
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    try:
        g.c.execute("SELECT * from task_vw WHERE assignment_id=%s", (assignment_id))
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    audit_list = []
    for task in rows:
        bind = (task['id'], task['project_id'], assignment_id, task['key_type'],
                task['key_text'], 'Reassigned', ('Reassigned to %s' % ipd['user']), task['user'])
        audit_list.append(bind)
    try:
        g.c.executemany(WRITE['TASK_AUDIT'], audit_list)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>/closeout', methods=['OPTIONS', 'POST'])
def closeout_assignment_by_id(assignment_id): # pragma: no cover
    '''
    Start then complete all tasks for an assignment, then complete the assignment
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
          description: Assignment closed out
      400:
          description: Assignment not closed out
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to close out assignments")
    ipd['id'] = assignment_id
    assignment = get_assignment_by_name_or_id(ipd['id'])
    if not assignment:
        raise InvalidUsage("Assignment %s does not exist" % ipd['id'], 404)
    assignment_id = ipd['id'] = assignment['id']
    if not assignment['start_date']:
        raise InvalidUsage("Assignment %s was not started" % ipd['id'])
    if assignment['completion_date']:
        raise InvalidUsage("Assignment %s was already completed" % ipd['id'])
    project = get_project_by_name_or_id(assignment['project'])
    select_user(project, ipd, result)
    try:
        g.c.execute("SELECT id FROM task WHERE assignment_id=%s ORDER BY 1", (assignment_id))
        tasks = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    print("Starting tasks for assignment %s" % (assignment['name']))
    for task in tasks:
        ipd2 = {"id": task['id']}
        start_task(ipd2, result)
    sleep(2)
    print("Completing tasks for assignment %s" % (assignment['name']))
    for task in tasks:
        ipd2 = {"id": task['id']}
        complete_task(ipd2, result)
    g.db.commit()
    return generate_response(result)


@app.route('/assignment/<string:assignment_id>', methods=['OPTIONS', 'DELETE'])
def delete_assignment(assignment_id):
    '''
    Delete an assignment
    Delete an assignment and revert its tasks back to unassigned. Assignments can
    only be deleted if none of their tasks have been started.
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
    assignment = get_assignment_by_name_or_id(assignment_id)
    if not assignment:
        raise InvalidUsage("Assignment %s was not found" % assignment_id, 404)
    assignment_id = assignment['id']
    tasks = get_tasks_by_assignment_id(assignment_id)
    del_assignment = True
    for task in tasks:
        if task['start_date']:
            del_assignment = False
            continue
        try:
            stmt = "UPDATE task SET assignment_id=NULL WHERE id=%s"
            bind = (task['id'])
            g.c.execute(stmt, bind)
            result['rest']['row_count'] += g.c.rowcount
            bind = (task['id'], task['project_id'], assignment_id, task['key_type'],
                    task['key_text'], 'Unassigned', None, task['user'])
            g.c.execute(WRITE['TASK_AUDIT'], bind)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    if del_assignment:
        try:
            stmt = "DELETE from assignment WHERE id=%s"
            bind = (assignment_id)
            g.c.execute(stmt, (assignment_id))
            result['rest']['row_count'] += g.c.rowcount
            result['rest']['sql_statement'] = g.c.mogrify(stmt, bind)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * Task endpoints                                                            *
# *****************************************************************************
@app.route('/tasks/<string:protocol>/<string:project_name>', methods=['OPTIONS', 'POST'])
@app.route('/tasks/<string:protocol>/<string:project_name>/<string:assignment_name>',
           methods=['OPTIONS', 'POST'])
def new_tasks_for_project(protocol, project_name, assignment_name=None):
    '''
    Generate one or more new tasks for a new or existing project
    Given a JSON payload containing specifics, generate new tasks for a
     new or existing project and return the task IDs.
     Parameters may be passed in as JSON.
     The "tasks" structure is a dictionary keyed by key text. Each key text will
     have a dictionary as a value. This [possibly empty] dictionary will
     contain task properties for the task. Allowable task properties are determined
     by the project protocol (task_insert_props).
    ---
    tags:
      - Task
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
      - in: query
        name: tasks
        schema:
          type: string
        required: true
        description: a dictionary of tasks (identified by keys such as body IDs)
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
        description: project neuron "post" value (informational only)
      - in: query
        name: pre
        schema:
          type: string
        required: false
        description: project neuron "pre" value (informational only)
      - in: query
        name: roi
        schema:
          type: string
        required: false
        description: project neuron ROI value (informational only)
      - in: query
        name: size
        schema:
          type: string
        required: false
        description: project neuron "size" value (informational only)
    responses:
      200:
          description: Project/tasks generated
      404:
          description: Project/tasks not generated
    '''
    result = initialize_result()
    # Get payload
    ipd = receive_payload(result)
    ipd['protocol'] = protocol
    ipd['project_name'] = project_name
    project = get_project_by_name_or_id(project_name)
    constructor = globals()[protocol.capitalize()]
    projectins = constructor()
    error = call_task_parser(projectins, ipd)
    if error:
        raise InvalidUsage(error)
    if project:
        if project['protocol'] != protocol:
            raise InvalidUsage("Additional tasks for an existing project " \
                               + "must be in the same protocol")
    else:
        ipd['priority'] = ipd['priority'] if 'priority' in ipd else 10
        insert_project(ipd, result)
        project = dict()
        project['id'] = result['rest']['inserted_id']
        project['protocol'] = protocol
    if hasattr(projectins, 'validate_tasks'):
        error = projectins.validate_tasks(ipd['tasks'])
        if error:
            raise InvalidUsage(error)
    # Add project properties from input parameters
    for parm in projectins.optional_properties:
        if parm in ipd:
            update_property(project['id'], 'project', parm, ipd[parm])
            result['rest']['row_count'] += g.c.rowcount
    # Are these tasks part of an assignment?
    assignment_id = None
    if assignment_name:
        assignment_id, this_user = create_assignment_from_tasks(project, assignment_name,
                                                                ipd, result)
    else:
        this_user = result['rest']['user']
    # Create the tasks
    background = len(ipd['tasks']) > app.config['FOREGROUND_TASK_LIMIT']
    if background:
        g.db.commit()
        pro = Process(target=create_tasks_from_json,
                      args=(ipd, project['id'], projectins.unit, projectins.task_insert_props,
                            assignment_id, result, this_user))
        print("Starting create_tasks_from_json in background")
        pro.start()
        result['rest']['tasks_inserted'] = -1
    else:
        create_tasks_from_json(ipd, project['id'], projectins.unit,
                               projectins.task_insert_props, assignment_id, result, this_user)
    return generate_response(result)


@app.route('/task/properties/<string:task_id>', methods=['OPTIONS', 'POST'])
def update_task_property(task_id):
    '''
    Update task properties
    Insert or update one or more task properties. Properties (one or more) are
    specified as key/value pairs as either form data or JSON.
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
        name: (key)
        schema:
          type: string
        required: true
        description: property type
      - in: query
        name: (value)
        schema:
          type: string
        required: true
        description: property value
    responses:
      200:
          description: Task properties inserted/updated
      404:
          description: Task properties inserted/updated
    '''
    result = initialize_result()
    # Get payload
    ipd = receive_payload(result)
    for key in ipd:
        update_property(task_id, 'task', key, ipd[key])
    g.db.commit()
    return generate_response(result)


@app.route('/tasks/eligible/<string:protocol>', methods=['GET'])
def get_eligible_tasks(protocol):
    '''
    Get eligible tasks for a protocol
    Given a protocol, return a list of eligible (not started) tasks.
     Specific columns from the table can be returned with the _columns key.
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
    sql = 'ELIGIBLE_' + protocol.upper()
    if not sql in READ:
        raise InvalidUsage("No SQL statement defined for protocol %s" % (protocol), 500)
    execute_sql(result, READ[sql], 'data')
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
    execute_sql(result, 'SELECT * FROM task_vw', 'temp', task_id)
    get_task_properties(result)
    del result['temp']
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
    execute_sql(result, 'SELECT * FROM task_vw', 'temp')
    get_task_properties(result)
    del result['temp']
    return generate_response(result)


@app.route('/task/<string:task_id>/start', methods=['OPTIONS', 'POST'])
def start_task_by_id(task_id): # pragma: no cover
    '''
    Start a task
    The task to start must have an assignment, and must not have already
     been started. If the assignment is not started, it will be started
     automatically.
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
    start_task(ipd, result, result['rest']['user'])
    g.db.commit()
    return generate_response(result)


@app.route('/task/<string:task_id>/complete', methods=['OPTIONS', 'POST'])
def complete_task_by_id(task_id): # pragma: no cover
    '''
    Complete a task
    The task to complete must be started, and must not have already
     been completed. If this is the last task in an assignment, the
     assignment will be completed.
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
        name: disposition
        schema:
          type: string
        required: false
        description: disposition [Complete]
      - in: query
        name: note
        schema:
          type: string
        required: false
        description: note
      - in: query
        name: complete_assignment
        schema:
          type: string
        required: false
        description: if a non-zero value the assignment will be completed if this was the last task
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
    g.db.commit()
    return generate_response(result)


@app.route('/run_search', methods=['OPTIONS', 'POST'])
def run_search():
    '''
    Search tasks
    Search tasks by key text.
    ---
    tags:
      - Task
    parameters:
      - in: query
        name: key_type
        schema:
          type: string
        required: true
        description: key type (display term)
      - in: query
        name: key_text
        schema:
          type: string
        required: true
        description: key text
    responses:
      200:
          description: Task table
      500:
          description: Error
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['key_type', 'key_text'])
    if ipd['key_type'] == 'task_id':
        sql = 'SELECT id,protocol,project,assignment,key_type_display,key_text ' \
              + 'FROM task_vw WHERE id=%s'
        bind = (ipd['key_text'], )
    else:
        prefix = 'SELECT id,protocol,project,assignment,key_type_display,key_text ' \
                 + 'FROM task_vw WHERE key_text=%s'
        if ipd['key_type'] == 'body':
            sql = prefix + " OR key_text LIKE %s OR key_text LIKE %s"
            bind = (ipd['key_text'], ipd['key_text'] + '_%', '%_' + ipd['key_text'])
        elif ipd['key_type'] == 'xyz':
            sql = prefix
            bind = (ipd['key_text'])
    sql += ' ORDER BY 2,3,4,6'
    result['data'] = 'No tasks found'
    try:
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    if rows:
        result['data'] = '''
        <table id="tasks" class="tablesorter standard">
        <thead>
        <tr><th>Task ID</th><th>Protocol</th><th>Project</th><th>Assignment</th><th>Key type</th><th>Key text</th></tr>
        </thead>
        <tbody>
        '''
        template = "<tr>" + ''.join('<td style="text-align: center">%s</td>') * 1 \
                   + ''.join('<td>%s</td>')*5 + "</tr>"
        for row in rows:
            tlink = '<a href="/task/%s">%s</a>' % tuple([row['id']] * 2)
            plink = '<a href="/project/%s">%s</a>' % tuple([row['project']] * 2)
            alink = '<a href="/assignment/%s">%s</a>' % tuple([row['assignment']] * 2) \
                    if row['assignment'] else ''
            result['data'] += template % (tlink, app.config['PROTOCOLS'][row['protocol']],
                                          plink, alink, row['key_type_display'], row['key_text'])
        result['data'] += '</tbody></table>'
    return generate_response(result)


@app.route('/task_audits/columns', methods=['GET'])
def get_task_audit_columns():
    '''
    Get columns from task_audit_vw table
    Show the columns in the task_audit_vw table, which may be used to filter
     results for the /task_audits endpoint.
    ---
    tags:
      - Task
    responses:
      200:
          description: Columns in task_audit_vw table
    '''
    result = initialize_result()
    show_columns(result, "task_audit_vw")
    return generate_response(result)


@app.route('/task_audits', methods=['GET'])
def get_task_audit_info():
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
    execute_sql(result, 'SELECT * FROM task_audit_vw', 'temp')
    get_task_properties(result)
    del result['temp']
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
# * User endpoints                                                            *
# *****************************************************************************
@app.route('/users/columns', methods=['GET'])
def get_user_columns():
    '''
    Get columns from user_vw table
    Show the columns in the user_vw table, which may be used to filter
     results for the /users endpoint.
    ---
    tags:
      - User
    responses:
      200:
          description: Columns in user_vw table
    '''
    result = initialize_result()
    show_columns(result, "user_vw")
    return generate_response(result)


@app.route('/users', methods=['GET'])
def get_users():
    '''
    Get users
    Show users. The caller can filter on any of
     the columns in the user_vw table. Inequalities (!=) and
     some relational operations (&lt;= and &gt;=) are supported. Wildcards are
     supported (use "*"). The returned list may be ordered by specifying a
     column with the _sort key. Multiple columns should be separated by a
     comma.
    ---
    tags:
      - User
    responses:
      200:
          description: All users
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM user_vw', 'data')
    return generate_response(result)


@app.route('/adduser', methods=['OPTIONS', 'POST'])
def add_user(): # pragma: no cover
    '''
    Add user
    ---
    tags:
      - User
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: User name (gmail address)
      - in: query
        name: janelia_id
        schema:
          type: string
        required: true
        description: Janelia ID
      - in: query
        name: permissions
        schema:
          type: list
        required: false
        description: List of permissions
    responses:
      200:
          description: User added
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['name', 'janelia_id'])
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to add a user")
    try:
        data = call_responder('config', 'config/workday/' + ipd['janelia_id'])
    except Exception as err:
        raise err
    if not data:
        raise InvalidUsage('User %s not found in Workday' % (ipd['name']))
    work = data['config']
    try:
        bind = (ipd['name'], work['first'], work['last'],
                ipd['janelia_id'], work['email'], work['organization'])
        g.c.execute(WRITE['INSERT_USER'], bind)
    except pymysql.IntegrityError:
        raise InvalidUsage("User %s is already in the database" % (ipd['name']))
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    result['rest']['row_count'] = g.c.rowcount
    result['rest']['inserted_id'] = g.c.lastrowid
    result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_USER'], bind)
    if 'permissions' in ipd and type(ipd['permissions']).__name__ == 'list':
        add_user_permissions(result, ipd['name'], ipd['permissions'])
    print("Added user " + ipd['janelia_id'])
    g.db.commit()
    publish_cdc(result, {"table": "user", "operation": "insert"})
    return generate_response(result)


@app.route('/user_permissions', methods=['OPTIONS', 'POST'])
def add_user_permission(): # pragma: no cover
    '''
    Add user permissions
    ---
    tags:
      - User
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: User name (gmail address)
      - in: query
        name: permissions
        schema:
          type: list
        required: true
        description: List of permissions
    responses:
      200:
          description: User permission(s) added
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['name', 'permissions'])
    if not check_permission(result['rest']['user'], ['admin', 'super']):
        raise InvalidUsage("You don't have permission to change user permissions")
    if type(ipd['permissions']).__name__ != 'list':
        raise InvalidUsage('Permissions must be specified as a list')
    result['rest']['row_count'] = 0
    add_user_permissions(result, ipd['name'], ipd['permissions'])
    g.db.commit()
    return generate_response(result)


@app.route('/user_permissions', methods=['OPTIONS', 'DELETE'])
def delete_user_permission(): # pragma: no cover
    '''
    Delete user permissions
    ---
    tags:
      - User
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: User name (gmail address)
      - in: query
        name: permissions
        schema:
          type: list
        required: true
        description: List of permissions
    responses:
      200:
          description: User permission(s) deleted
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['name', 'permissions'])
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to delete user permissions")
    if type(ipd['permissions']).__name__ != 'list':
        raise InvalidUsage('Permissions must be specified as a list')
    result['rest']['row_count'] = 0
    user_id = get_user_id(ipd['name'])
    for permission in ipd['permissions']:
        sql = "DELETE FROM user_permission WHERE user_id=%s AND permission=%s"
        try:
            bind = (user_id, permission)
            g.c.execute(sql, bind)
            result['rest']['row_count'] += g.c.rowcount
            publish_cdc(result, {"table": "user_permission", "operation": "delete"})
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    g.db.commit()
    return generate_response(result)


# *****************************************************************************


if __name__ == '__main__':
    app.run(debug=True)
