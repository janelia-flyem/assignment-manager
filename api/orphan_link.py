from assignment_utilities import call_responder

class Orphan_link:

    def __init__(self):
        self.num_tasks = 100
        self.task_populate_method = 'query_neuprint'
        self.unit = 'body_id'
        self.cypher_unit = 'bodyId'
        self.allowable_filters = ['post', 'pre', 'size']
        self.optional_properties = ['roi', 'status', 'note']

    def cypher(self, result, ipd):
        '''
        Given an optional ROI and status, generate the Cypher query
        '''
        assert 'roi' in ipd and ipd['roi'], \
               "Cannot generate orphan_link Cypher query: missing ROI"
        in_list = ipd['roi'].split(',')
        clause_list = []
        for this_val in in_list:
            clause_list.append('n.`' + this_val + '`=true')
        roi_clause = '(' + ' OR '.join(clause_list) + ') AND '
        status_clause = "(n.status=\"0.5assign\" or NOT EXISTS(n.status))"
        if 'status' in ipd:
            in_list = ipd['status'].split(',')
            clause_list = []
            for this_val in in_list:
                clause_list.append("n.status=\"" + this_val + "\"")
            status_clause = '(' + ' OR '.join(clause_list) + ')'
        else:
            ipd['status'] = ''
        payload = {"cypher" : "MATCH (n:`hemibrain-Neuron`) WHERE " + roi_clause \
                   + status_clause + " RETURN n ORDER BY n.size DESC"}
        result['rest']['cypher'] = payload['cypher']
        try:
            response = call_responder('neuprint', 'custom/custom', payload)
        except Exception as err:
            raise err
        return response
