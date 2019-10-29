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


    def parse_tasks(self, ipd):
        '''
        Given a tasks list, put it in a format we can use
          self: object
          ipd: input parameters
        '''
        if 'points' not in ipd:
            return "connection_validation requires a task list"
        elif 'body_id' not in ipd:
            return "connection_validation protocol requires a body_id"
        elif not isinstance(ipd['points'], (list)):
            return "points payload must be an array of arrays"
        ipd['tasks'] = dict()
        if 'source' not in ipd and 'software' in ipd and ipd['software']:
            ipd['source'] = ipd['software']
        for pnt in ipd['points']:
            name = '_'.join([str(i) for i in pnt])
            if 'body_id' in ipd:
                name = '_'.join([str(ipd['body_id']), name])
            ipd['tasks'][name] = {}
        return None

