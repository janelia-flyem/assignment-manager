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
        self.num_tasks = 1
        self.task_populate_method = None
        self.unit = 'xyz'
        self.optional_properties = ['note', 'group', 'source']
        self.allowable_filters = []
        # self.no_assignment = True
        self.allowable_todo_types = ['diagnostic', 'irrelevant', 'merge', 'no_soma', 'split',
                                     'svsplit', 'trace_to_soma']
        self.required_task_props = ['priority', 'todo_type']
        self.task_insert_props = ['priority', 'todo_type']


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
