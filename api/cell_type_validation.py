''' Cell_type_validation protocol
'''

import json

class Cell_type_validation:
    '''
    Cell_type_validation protocol object
    '''
    def __init__(self):
        '''
        Initialize a Cell_type_validation object
        Keyword arguments:
          self: object
        '''
        self.num_tasks = 100
        self.task_populate_method = 'json_upload'
        self.unit = 'multibody'
        self.optional_properties = ['note', 'group', 'source']
        self.allowable_filters = []
        # self.no_assignment = True
        self.required_task_props = ['body ID A', 'body ID B', 'match_score', 'task result id', 'task type']
        self.task_insert_props = ['body ID A', 'body ID B', 'match_score', 'task result id', 'task type', 'debug']

    def parse_tasks(self, ipd):
        '''
        Given a task list, put it in a format we can use
        Keyword arguments:
          self: object
          ipd: input parameters
        '''
        if 'task list' not in ipd:
            return "cell_type_validation requires a task list"
        elif not isinstance(ipd['task list'], (list)):
            return "tasks payload must be a JSON list"
        ipd['tasks'] = dict()
        for task in ipd['task list']:
            name = '_'.join([str(task['body ID A']), str(task['body ID B'])])
            ipd['tasks'][name] = {}
            for i in self.task_insert_props:
                if i in task:
                    if i == 'debug':
                        task[i] = json.dumps(task[i])
                    ipd['tasks'][name][i] = task[i]
                elif i in self.required_task_props:
                    return "Missing %s for task %s" % (i, name)
        return

