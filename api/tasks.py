from datetime import datetime
from flask import g
import assignment_utilities
from assignment_utilities import InvalidUsage, get_key_type_id, sql_error

WRITE = {
    'INSERT_TASK': "INSERT INTO task (name,project_id,key_type_id,key_text,"
                   + "user) VALUES (%s,%s,getCvTermId('key',%s,NULL),%s,%s)",
    'TASK_AUDIT': "INSERT INTO task_audit (project_id,assignment_id,key_type_id,key_text,"
                  + "disposition,user) VALUES (%s,%s,%s,%s,%s,%s)",
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
    #key_type = projectins.unit
    ignored = inserted = 0
    existing_task = dict()
    project_id = result['rest']['inserted_id']
    if existing_project:
        # Find existing tasks and put them in the existing_task dictionary
        try:
            g.c.execute("SELECT assignment_id,key_text FROM task WHERE project_id=%s", (project_id))
            existing = g.c.fetchall()
            for extask in existing:
                existing_task[extask['key_text']] = extask['assignment_id']
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
            bind = (name, result['rest']['inserted_id'], key_type,
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
    stmt = "INSERT INTO task_property (task_id,type_id,value) VALUES " \
           + "(%s,getCvTermId('task',%s,NULL),%s) ON DUPLICATE KEY UPDATE value=%s"
    for key in existing_task:
        if key in query_task:
            if key in inserted_key:
                bind = (project_id, None, get_key_type_id(key_type),
                        key, 'Inserted', result['rest']['user'])
                audit_list.append(bind)
            for prop in task_insert_props:
                if prop in query_task[key]:
                    value = query_task[key][prop]
                    bind = (existing_task[key], prop, value, value)
                    insert_list.append(bind)
    print("Task properties to insert: %s" % len(insert_list))
    if insert_list:
        try:
            g.c.executemany(stmt, insert_list)
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
    g.db.commit()
