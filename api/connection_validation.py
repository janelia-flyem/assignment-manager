''' Connection_validation protocol
'''

class Connection_validation:
    '''
    Connection_validation protocol object
    '''
    def __init__(self):
        '''
        Initialize a Connection_validation object
        Keyword arguments:
          self: object
        '''
        self.num_tasks = 100
        self.task_populate_method = 'json_upload'
        self.unit = 'body_xyz'
        self.optional_properties = ['note', 'group', 'source']
        self.allowable_filters = []
        # self.no_assignment = True
        self.required_task_props = []
        self.task_insert_props = []
