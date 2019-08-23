from assignment_utilities import call_responder
from datetime import datetime

class Cleave:

    def __init__(self):
        self.num_tasks = 100
        self.task_populate_method = 'query_neuprint'
        self.unit = 'body_id'
        self.cypher_unit = 'bodyId'
        self.allowable_filters = []
        self.optional_properties = ['size', 'roi', 'status', 'note', 'group']
        self.task_insert_props = ['cluster_name', 'post', 'pre', 'status']

    def cypher(self, result, ipd, source):
        '''
        Given a size, and optional ROI and status, generate the Cypher query
        '''
        perfstart = datetime.now()
        assert 'size' in ipd and ipd['size'], \
               "Cannot generate orphan_link Cypher query: missing ROI"
        size_clause = "(n.size>=" + str(ipd['size']) + ")"
        roi_clause = where_clause = ''
        if 'roi' in ipd:
            in_list = ipd['roi'].split(',')
            clause_list = []
            for this_val in in_list:
                clause_list.append('n.`' + this_val + '`=true')
            roi_clause = ' AND (' + ' OR '.join(clause_list) + ')'
        else:
            ipd['roi'] = ''
        status_clause = " AND (n.status=\"0.5assign\" OR n.status=\"Leaves\" OR NOT EXISTS(n.status))"
        if 'status' in ipd:
            in_list = ipd['status'].split(',')
            clause_list = []
            for this_val in in_list:
                clause_list.append("n.status=\"" + this_val + "\"")
            status_clause = ' AND (' + ' OR '.join(clause_list) + ')'
        else:
            ipd['status'] = ''
        where_clause = roi_clause + status_clause
        payload = {"cypher" : "MATCH (n:`" + source + "`) WHERE " + size_clause \
                   + where_clause + " RETURN n ORDER BY n.size DESC"}
        result['rest']['cypher'] = payload['cypher']
        try:
            response = call_responder('neuprint', 'custom/custom', payload)
        except Exception as err:
            raise err
        result['rest']['elapsed_neuprint_query'] = str(datetime.now() - perfstart)
        return response
