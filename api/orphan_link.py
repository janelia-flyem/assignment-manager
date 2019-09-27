from assignment_utilities import call_responder
from datetime import datetime

class Orphan_link:

    def __init__(self):
        self.num_tasks = 100
        self.task_populate_method = 'query_neuprint'
        self.unit = 'body_id'
        self.cypher_unit = 'bodyId'
        self.allowable_filters = ['post', 'pre', 'size']
        self.optional_properties = ['roi', 'status', 'note', 'group']
        self.task_insert_props = ['cluster_name', 'post', 'pre', 'status']

    def cypher(self, result, ipd, source, count_only=False):
        '''
        Given an optional ROI and status, generate the Cypher query
          self: object
          result: result dictionary
          ipd: input parameters
          source: neuprint source
        '''
        perfstart = datetime.now()
        assert 'roi' in ipd and ipd['roi'], \
               "Cannot generate orphan_link Cypher query: missing ROI"
        clauses = []
        filt_clause = ''
        clause_list = []
        for filt in self.allowable_filters:
            if filt in ipd and ipd[filt]:
                clause_list.append("(n.%s>=%s)" % (filt, str(ipd[filt])))
        if (len(clause_list)):
            filt_clause = '(' + ' AND '.join(clause_list) + ')'
            clauses.append(filt_clause)
        roi_clause = ''
        if 'roi' in ipd:
            in_list = ipd['roi'].split(',')
            clause_list = []
            for this_val in in_list:
                clause_list.append('n.`' + this_val + '`=true')
            roi_clause = '(' + ' OR '.join(clause_list) + ')' 
        else:
            ipd['roi'] = ''
        clauses.append(roi_clause)
        status_clause = "(n.status=\"0.5assign\" or NOT EXISTS(n.status))"
        if 'status' in ipd and ipd['status']:
            in_list = ipd['status'].split(',')
            clause_list = []
            for this_val in in_list:
                clause_list.append("n.status=\"" + this_val + "\"")
            status_clause = '(' + ' OR '.join(clause_list) + ')'
        else:
            ipd['status'] = ''
        clauses.append(status_clause)
        where_clause = ' AND '.join(clauses)
        suffix = " RETURN COUNT(n)" if count_only else " RETURN n ORDER BY n.size DESC"
        payload = {"cypher" : "MATCH (n:`" + source + "`) WHERE " + where_clause \
                   + suffix}
        result['rest']['cypher'] = payload['cypher']
        print(payload['cypher'])
        try:
            response = call_responder('neuprint', 'custom/custom', payload)
        except Exception as err:
            raise err
        result['rest']['elapsed_neuprint_query'] = str(datetime.now() - perfstart)
        return response
