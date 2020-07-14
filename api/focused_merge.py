''' Focused merge protocol
'''

import json

class Focused_merge:
    '''
    Focused merge protocol object
    '''
    def __init__(self):
        '''
        Initialize a Focused merge object
        Keyword arguments:
          self: object
        '''
        self.num_tasks = 250
        self.task_populate_method = 'json_upload'
        self.unit = 'multibody'
        self.optional_properties = ['note', 'group', 'source']
        self.allowable_filters = []
        # self.no_assignment = True 
        self.required_task_props = ['supervoxel ID 1', 'supervoxel ID 2', 'task type', 'supervoxel point 1', 'supervoxel point 2']
        self.task_insert_props = ['supervoxel ID 1', 'supervoxel ID 2', 'task type', 'supervoxel point 1', 'supervoxel point 2' ]

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
            name = '_'.join([str(task['supervoxel ID 1']), str(task['supervoxel ID 2'])])
            ipd['tasks'][name] = {}
            for i in self.task_insert_props:
                if i in task:
                    if i == 'debug':
                        task[i] = json.dumps(task[i])
                    ipd['tasks'][name][i] = task[i]
                elif i in self.required_task_props:
                    return "Missing %s for task %s" % (i, name)
        return

    def validate_tasks(self, tasks):
        '''
        Validate a given list of tasks
        Keyword arguments:
          self: object
          tasks: list of tasks
        '''
        for key in tasks:
            for parm in self.required_task_props:
                if parm not in tasks[key]:
                    return "Missing task property %s for task %s" % (parm, key)            
        return None
