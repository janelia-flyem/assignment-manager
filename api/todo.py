''' ToDo protocol
'''

class Todo:
    '''
    ToDo protocol object
    '''
    def __init__(self):
        '''
        Initialize a ToDo object
        Keyword arguments:
          self: object
        '''
        self.num_tasks = 100
        self.task_populate_method = 'json_upload'
        self.unit = 'xyz'
        self.optional_properties = ['note', 'group', 'source']
        self.allowable_filters = []
        # self.no_assignment = True
        self.allowable_todo_types = ['diagnostic', 'irrelevant', 'merge', 'no_soma', 'to split',
                                     'svsplit', 'trace_to_soma']
        self.required_task_props = ['priority', 'todo_type', 'todo_user']
        self.task_insert_props = ['priority', 'todo_type', 'todo_user']


    def parse_tasks(self, ipd):
        '''
        Given a tasks list, put it in a format we can use
          self: object
          ipd: input parameters
        '''
        if 'points' not in ipd:
            return "todo requires a task list"
        elif not isinstance(ipd['points'], (list)):
            return "points payload must be an array of dictionaries"
        ipd['tasks'] = dict()
        if 'source' not in ipd and 'software' in ipd and ipd['software']:
            ipd['source'] = ipd['software']
        for pnt in ipd['points']:
            name = '_'.join([str(i) for i in pnt['Pos']])
            if 'Prop' in pnt:
                for field in ['action', 'user']:
                    if field not in pnt['Prop']:
                        return "point Prop payload must contain a %s entry" % (field)
            else:
                return "point payload must contain a Prop entry"
            priority = pnt['priority'] if 'priority' in pnt else "0"
            ipd['tasks'][name] = {"todo_type": pnt['Prop']['action'],
                                  "priority": priority,
                                  "todo_user": pnt['Prop']['user']}
        return None


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
            if tasks[key]['todo_type'] not in self.allowable_todo_types:
                return "Invalid task type %s for task %s" % (tasks[key]['todo_type'], key)
        return None
