from datetime import datetime
from flask import g
import assignment_utilities
from assignment_utilities import InvalidUsage, sql_error, update_property

WRITE = {
    'INSERT_TASK': "INSERT INTO task (name,project_id,assignment_id,key_type_id,key_text,"
                   + "user) VALUES (%s,%s,%s,getCvTermId('key',%s,NULL),%s,%s)",
    'TASK_AUDIT': "INSERT INTO task_audit (task_id,project_id,assignment_id,key_type_id,key_text,"
                  + "disposition,user) VALUES (%s,%s,%s,getCvTermId('key',%s,NULL),%s,%s,%s)",
    'TASK_PROP' : "INSERT INTO task_property (task_id,type_id,value) VALUES "
                  + "(%s,getCvTermId('task',%s,NULL),%s) ON DUPLICATE KEY UPDATE value=%s"
}


def generate_tasks(result, key_type, task_insert_props, existing_project):
    ''' Generate and persist a list of tasks for a project
        Keyword arguments:
          result: result dictionary
          key_type: key type
          task_insert_props: project properties to persist
          existing_project: indicates if this is a new or existing project
    '''
    perfstart = datetime.now()
    ignored = inserted = 0
    existing_task = dict()
    existing_task_id = dict()
    project_id = result['rest']['inserted_id']
    if existing_project:
        # Find existing tasks and put them in the existing_task dictionary
        try:
            g.c.execute("SELECT id,assignment_id,key_text FROM task WHERE project_id=%s", (project_id))
            existing = g.c.fetchall()
            for extask in existing:
                existing_task[extask['key_text']] = extask['assignment_id']
                existing_task_id[extask['key_text']] = extask['id']
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    insert_list = []
    query_task = dict()
    inserted_key = dict()
    for task in result['tasks']:
        key = str(task[key_type])
        query_task[key] = task
        if key in existing_task:
            ignored += 1
        else:
            name = "%d.%s" % (result['rest']['inserted_id'], key)
            bind = (name, result['rest']['inserted_id'], None, key_type,
                    key, result['rest']['user'],)
            insert_list.append(bind)
            inserted_key[key] = 1
    if insert_list:
        try:
            g.c.executemany(WRITE['INSERT_TASK'], insert_list)
            result['rest']['row_count'] += g.c.rowcount
            inserted = g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    # Insert/update task properties
    existing_task = dict()
    try:
        g.c.execute("SELECT id,key_text FROM task WHERE project_id=%s", (project_id))
        existing = g.c.fetchall()
        for extask in existing:
            existing_task[extask['key_text']] = extask['id']
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    # existing_task now contains key -> task ID
    insert_list = []
    audit_list = []
    proprecs = {'insert': 0, 'update': 0}
    print(existing_task)
    for key in existing_task:
        if key in query_task:
            operation = 'update'
            if key in inserted_key:
                print(key)
                print(existing_task[key])
                bind = (existing_task[key], project_id, None, key_type, key,
                        'Created', result['rest']['user'])
                audit_list.append(bind)
                operation = 'insert'
            for prop in task_insert_props:
                if prop in query_task[key]:
                    value = query_task[key][prop]
                    bind = (existing_task[key], prop, value, value)
                    insert_list.append(bind)
                    proprecs[operation] += 1
    if insert_list:
        print("Task properties to insert/update: %s" % len(insert_list))
        try:
            g.c.executemany(WRITE['TASK_PROP'], insert_list)
            result['rest']['row_count'] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        try:
            g.c.executemany(WRITE['TASK_AUDIT'], audit_list)
            result['rest']['row_count'] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    result['rest']['elapsed_task_generation'] = str(datetime.now() - perfstart)
    if ignored:
        result['rest']['tasks_skipped'] = ignored
    if inserted:
        result['rest']['tasks_inserted'] = inserted
    if proprecs['insert']:
        result['rest']['task_properties_inserted'] = proprecs['insert']
    if proprecs['update']:
        result['rest']['task_properties_to_update'] = proprecs['update']
    g.db.commit()


def create_tasks_from_json(ipd, project_id, key_type, task_insert_props, assignment_id, result):
    ''' Create and persist a list of task from JSON input
        Keyword arguments:
          ipd: input parameters
          project_id: project ID
          key_type: key type
          task_insert_props: project properties to persist
          assignment_id: assignment ID
          result: result dictionary
    '''
    insert_list = []
    # Insert tasks
    for key in ipd['tasks']:
        try:
            g.c.execute("SELECT * FROM task_vw WHERE project_id=%s AND key_type=%s AND key_text=%s", (project_id, key_type, key))
            task = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        if task:
            raise InvalidUsage("Task exists for %s %s in project %s" \
                               % (key_type, key, project_id))
        if 'name' in ipd['tasks'][key]:
            name = ipd['tasks'][key]['name']
        else:
            name = "%d.%s" % (project_id, key)
        bind = (name, project_id, assignment_id, key_type, key, result['rest']['user'])
        insert_list.append(bind)
    if insert_list:
        try:
            g.c.executemany(WRITE['INSERT_TASK'], insert_list)
            result['rest']['row_count'] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    result['rest']['tasks_inserted'] = len(insert_list)
    # Select tasks to get IDs and build list of properties to insert
    result['tasks'] = dict()
    insertprop_list = []
    try:
        g.c.execute("SELECT * FROM task WHERE project_id=%s", (project_id))
        existing = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    audit_list = []
    for etask in existing:
        key = etask['key_text']
        # Skip this one if it wasn't just inserted
        if key not in ipd['tasks']:
            continue
        result['tasks'].update({key: {"id": etask['id']}})
        bind = (etask['id'], etask['project_id'], etask['assignment_id'], key_type,
                etask['key_text'], 'Created', etask['user'])
        audit_list.append(bind)
        # Task properties
        for parm in task_insert_props:
            if parm in ipd['tasks'][key]:
                bind = (etask['id'], parm, ipd['tasks'][key][parm], ipd['tasks'][key][parm])
                insertprop_list.append(bind)
                result['tasks'][key][parm] = ipd['tasks'][key][parm]
    if insertprop_list:
        print("Task properties to insert: %s" % len(insertprop_list))
        try:
            g.c.executemany(WRITE['TASK_PROP'], insertprop_list)
            result['rest']['row_count'] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
    # Update task_audit
    if audit_list:
        try:
            g.c.executemany(WRITE['TASK_AUDIT'], audit_list)
            result['rest']['row_count'] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
